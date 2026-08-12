"""
Lottery V2 waterfall runner — single unified draw across ranked tiers.

Does not touch permit_applications or the live per-tier lottery.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lottery_v2 import LotteryV2Application, LotteryV2AuditLog, LotteryV2Cycle
from app.models.permit import Permit
from app.models.permit_type import PermitType
from app.services.email import (
    branded_email_shell,
    extract_first_name,
    send_email,
    send_lottery_selection_email,
)
from app.services.lottery import distribute_capacity

logger = logging.getLogger(__name__)

# Campus → existing permit type codes (capacity/pricing/lots live on those rows)
# Campus / path → existing permit type codes (capacity/pricing/lots live on those rows)
CAMPUS_TIER_CODES: dict[str, list[str]] = {
    "north": [
        "north_premium_resident",
        "north_guaranteed_resident",
        "steel_field_resident",
    ],
    "south": [
        "south_premium_resident",
        "south_guaranteed_resident",
    ],
    # Commuter path is purchase (not lottery), but shares this intake workflow
    "commuter": [
        "premium_commuter",
        "commuter_undergrad",
        "commuter_grad",
    ],
}

ALL_V2_TIER_CODES = [c for codes in CAMPUS_TIER_CODES.values() for c in codes]
LOTTERY_TIER_CODES = [
    c for path, codes in CAMPUS_TIER_CODES.items() if path != "commuter" for c in codes
]


@dataclass
class TierCapacity:
    """Mutable remaining capacity for one permit type during a draw."""

    permit_type_id: uuid.UUID
    code: str
    label: str
    price: Any
    remaining: int
    lot_order: list[str]
    lot_remaining: dict[str, int]


@dataclass
class WaterfallApplicant:
    """Lightweight applicant used by the pure placement engine."""

    id: Any
    class_year: int
    created_at: datetime
    tier_preferences: list[Any]
    student_email: str = ""
    student_name: str = ""
    lot_preferences: list[str] = field(default_factory=list)


@dataclass
class Placement:
    app_id: Any
    status: str  # selected | waitlisted
    lottery_rank: int | None = None
    waitlist_position: int | None = None
    assigned_permit_type_id: Any | None = None
    assigned_lot: str | None = None


def class_year_eligible(pt: PermitType, class_year: int) -> bool:
    """Apply min_class_year / allow_freshmen rules from the permit type."""
    if pt.min_class_year is not None and class_year < pt.min_class_year:
        return False
    # Freshmen = current calendar year's incoming class heuristic: class_year >= now+3
    # Keep simple: if allow_freshmen is False and min_class_year is set, min already covers it.
    # If allow_freshmen is False with no min, treat as no extra restriction beyond min.
    if not pt.allow_freshmen and pt.min_class_year is None:
        # No explicit floor — still allow all years for staging unless configured.
        pass
    return True


def _as_uuid(value: Any) -> uuid.UUID | None:
    """Normalize UUID / string UUID values from PG arrays and JSON."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _normalize_preferences(prefs: list[Any] | None) -> list[uuid.UUID]:
    out: list[uuid.UUID] = []
    seen: set[uuid.UUID] = set()
    for raw in prefs or []:
        uid = _as_uuid(raw)
        if uid is None or uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    return out


def waterfall_place(
    applicants: list[WaterfallApplicant],
    tiers: dict[Any, TierCapacity],
) -> tuple[list[Placement], list[Placement], list[str]]:
    """Pure waterfall placement.

    Sort by (class_year ASC, created_at ASC). For each student, try ranked
    tiers until one has remaining capacity; assign a lot within that tier.
    Returns (selected, waitlisted, warnings).
    """
    # Accept both UUID and string keys in the tiers map
    tiers_by_id: dict[uuid.UUID, TierCapacity] = {}
    for key, tier in tiers.items():
        uid = _as_uuid(key) or _as_uuid(getattr(tier, "permit_type_id", None))
        if uid is not None:
            tiers_by_id[uid] = tier

    ordered = sorted(applicants, key=lambda a: (a.class_year, a.created_at))
    selected: list[Placement] = []
    waitlisted: list[Placement] = []
    warnings: list[str] = []
    rank = 0

    for app in ordered:
        placed = False
        for ptid in _normalize_preferences(app.tier_preferences):
            tier = tiers_by_id.get(ptid)
            if not tier or tier.remaining <= 0:
                continue

            lot = _pick_lot(tier, app.lot_preferences)
            if lot is None:
                warnings.append(
                    f"Tier {tier.code} has spots but no lot capacity for applicant {app.id}"
                )
                continue

            tier.remaining -= 1
            tier.lot_remaining[lot] = tier.lot_remaining.get(lot, 0) - 1
            rank += 1
            selected.append(
                Placement(
                    app_id=app.id,
                    status="selected",
                    lottery_rank=rank,
                    assigned_permit_type_id=ptid,
                    assigned_lot=lot,
                )
            )
            placed = True
            break

        if not placed:
            waitlisted.append(
                Placement(
                    app_id=app.id,
                    status="waitlisted",
                    waitlist_position=len(waitlisted) + 1,
                    lottery_rank=None,
                )
            )

    # Assign lottery_rank for waitlisted after selected (for display continuity)
    for i, p in enumerate(waitlisted):
        p.lottery_rank = rank + i + 1
        p.waitlist_position = i + 1

    return selected, waitlisted, warnings


def _pick_lot(tier: TierCapacity, preferences: list[str]) -> str | None:
    """Assign highest-preference lot with remaining capacity, else first available."""
    order = preferences if preferences else tier.lot_order
    for lot in order:
        if lot in tier.lot_remaining and tier.lot_remaining[lot] > 0:
            return lot
    for lot in tier.lot_order:
        if tier.lot_remaining.get(lot, 0) > 0:
            return lot
    # Spots remain at tier level but lots exhausted — fall back to first lot name
    if tier.lot_order and tier.remaining > 0:
        return tier.lot_order[0]
    return None


def try_place_one(
    applicant: WaterfallApplicant,
    tiers: dict[Any, TierCapacity],
) -> Placement | None:
    """Attempt waterfall placement for a single waitlisted applicant (decline backfill)."""
    tiers_by_id: dict[uuid.UUID, TierCapacity] = {}
    for key, tier in tiers.items():
        uid = _as_uuid(key) or _as_uuid(getattr(tier, "permit_type_id", None))
        if uid is not None:
            tiers_by_id[uid] = tier

    for ptid in _normalize_preferences(applicant.tier_preferences):
        tier = tiers_by_id.get(ptid)
        if not tier or tier.remaining <= 0:
            continue
        lot = _pick_lot(tier, applicant.lot_preferences)
        if lot is None:
            continue
        tier.remaining -= 1
        tier.lot_remaining[lot] = tier.lot_remaining.get(lot, 0) - 1
        return Placement(
            app_id=applicant.id,
            status="selected",
            assigned_permit_type_id=ptid,
            assigned_lot=lot,
        )
    return None


async def build_tier_capacities(
    db: AsyncSession,
    permit_types: list[PermitType],
) -> dict[uuid.UUID, TierCapacity]:
    """Build remaining capacity map from live permit types, active permits, AND outstanding lottery offers."""
    tiers: dict[uuid.UUID, TierCapacity] = {}
    for pt in permit_types:
        active_count = (
            await db.execute(
                select(func.count())
                .select_from(Permit)
                .where(
                    Permit.permit_type == pt.code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

        offer_count = (
            await db.execute(
                select(func.count())
                .select_from(LotteryV2Application)
                .where(
                    LotteryV2Application.assigned_permit_type_id == pt.id,
                    LotteryV2Application.status == "selected",
                )
            )
        ).scalar() or 0

        committed = active_count + offer_count
        public_capacity = (pt.max_capacity or 0) - (pt.reserved_spots or 0)
        remaining = max(0, public_capacity - committed)
        lots = list(pt.lot_assignments or [])
        lot_caps = distribute_capacity(remaining, lots) if lots else {}
        tiers[pt.id] = TierCapacity(
            permit_type_id=pt.id,
            code=pt.code,
            label=pt.label,
            price=pt.price,
            remaining=remaining,
            lot_order=lots,
            lot_remaining=dict(lot_caps),
        )
    return tiers


async def run_waterfall_draw(
    db: AsyncSession,
    cycle_id: uuid.UUID,
    run_by: str,
    *,
    include_test_entries: bool = True,
    send_notifications: bool = True,
) -> dict:
    """Execute the full waterfall draw for a cycle and persist results."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise ValueError("Cycle not found")
    if cycle.status == "drawn" and cycle.drawn_at:
        raise ValueError(
            f"Cycle already drawn at {cycle.drawn_at}. Reset before re-running."
        )
    if cycle.status == "open":
        # Auto-close when triggered by threshold or deadline
        cycle.status = "closed"
        cycle.closes_at = datetime.now(timezone.utc)
        await db.flush()

    apps_result = await db.execute(
        select(LotteryV2Application).where(
            LotteryV2Application.cycle_id == cycle_id,
            LotteryV2Application.status == "pending",
        )
    )
    all_apps = list(apps_result.scalars().all())
    total = len(all_apps)

    filtered_test = 0
    eligible_orm: list[LotteryV2Application] = []
    for app in all_apps:
        if app.is_test_entry and not include_test_entries:
            filtered_test += 1
            continue
        eligible_orm.append(app)

    # One application per email — keep earliest; mark extras ineligible
    filtered_duplicates = 0
    by_email: dict[str, list[LotteryV2Application]] = {}
    for app in eligible_orm:
        key = (app.student_email or "").strip().lower() or f"sub:{app.student_sub}"
        by_email.setdefault(key, []).append(app)
    deduped: list[LotteryV2Application] = []
    for key, group in by_email.items():
        group_sorted = sorted(
            group, key=lambda a: a.created_at or datetime.now(timezone.utc)
        )
        deduped.append(group_sorted[0])
        for extra in group_sorted[1:]:
            extra.status = "ineligible"
            note = (
                f"Duplicate application for {key}; kept earliest "
                f"({group_sorted[0].id})."
            )
            extra.admin_notes = (
                f"{extra.admin_notes}\n{note}".strip() if extra.admin_notes else note
            )
            filtered_duplicates += 1
    eligible_orm = deduped

    # Unpaid citations filter
    filtered_citations = 0
    citation_clean: list[LotteryV2Application] = []
    for app in eligible_orm:
        if app.plate:
            unpaid = (
                await db.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM tickets
                        WHERE UPPER(plate) = UPPER(:plate)
                          AND status NOT IN ('paid', 'voided', 'resolved_permit')
                        """
                    ),
                    {"plate": app.plate},
                )
            ).scalar() or 0
            if unpaid > 0:
                app.status = "ineligible"
                app.admin_notes = (
                    f"Blocked: {unpaid} unpaid citation(s). "
                    "Pay outstanding fines to become eligible."
                )
                filtered_citations += 1
                continue
        citation_clean.append(app)

    # Capacity = live remaining minus seats already offered in this cycle
    # (protects against partial/re-entrant draws)
    tiers = await _tiers_with_offers_reserved(db, cycle_id)
    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(LOTTERY_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    pt_by_id = {pt.id: pt for pt in pts}

    applicants = [
        WaterfallApplicant(
            id=a.id,
            class_year=a.class_year or 9999,
            created_at=a.created_at or datetime.now(timezone.utc),
            tier_preferences=_normalize_preferences(a.tier_preferences),
            student_email=a.student_email,
            student_name=a.student_name,
        )
        for a in citation_clean
    ]

    selected, waitlisted, warnings = waterfall_place(applicants, tiers)

    if filtered_duplicates:
        warnings.append(
            f"Skipped {filtered_duplicates} duplicate application(s) (same email)."
        )

    offer_days = cycle.offer_window_days or 5
    offer_expires = datetime.now(timezone.utc) + timedelta(days=offer_days)
    app_by_id = {a.id: a for a in citation_clean}

    selected_for_notify: list[tuple[LotteryV2Application, PermitType]] = []
    waitlisted_for_notify: list[LotteryV2Application] = []

    for p in selected:
        app = app_by_id[p.app_id]
        app.status = "selected"
        app.lottery_rank = p.lottery_rank
        app.assigned_permit_type_id = p.assigned_permit_type_id
        app.assigned_lot = p.assigned_lot
        app.offer_expires_at = offer_expires
        app.waitlist_position = None
        pt_id = _as_uuid(p.assigned_permit_type_id)
        pt = pt_by_id.get(pt_id) if pt_id else None
        if pt:
            selected_for_notify.append((app, pt))

    for p in waitlisted:
        app = app_by_id[p.app_id]
        app.status = "waitlisted"
        app.lottery_rank = p.lottery_rank
        app.waitlist_position = p.waitlist_position
        app.assigned_permit_type_id = None
        app.assigned_lot = None
        waitlisted_for_notify.append(app)

    now = datetime.now(timezone.utc)
    cycle.status = "drawn"
    cycle.drawn_at = now
    cycle.drawn_by = run_by

    placements_detail = [
        {
            "application_id": str(p.app_id),
            "status": p.status,
            "lottery_rank": p.lottery_rank,
            "waitlist_position": p.waitlist_position,
            "assigned_permit_type_id": str(p.assigned_permit_type_id)
            if p.assigned_permit_type_id
            else None,
            "assigned_lot": p.assigned_lot,
        }
        for p in selected + waitlisted
    ]

    audit = LotteryV2AuditLog(
        cycle_id=cycle_id,
        strategy="seniority_timestamp_waterfall",
        total_applicants=total,
        eligible_applicants=len(citation_clean),
        selected_count=len(selected),
        waitlisted_count=len(waitlisted),
        filtered_test_entries=filtered_test,
        filtered_unpaid_citations=filtered_citations,
        run_at=now,
        run_by=run_by,
        details={"placements": placements_detail},
        warnings="\n".join(warnings) if warnings else None,
    )
    db.add(audit)
    await db.flush()

    if send_notifications:
        await _notify_selected(selected_for_notify, offer_expires)
        await _notify_waitlisted(waitlisted_for_notify)

    # Log undersubscribed tiers — admin can manually open direct purchase if desired
    for pt in pts:
        tier = tiers.get(pt.id)
        if not tier:
            continue
        if tier.remaining > 0:
            logger.info(
                "Tier %s has %d spots remaining after draw — admin may open direct purchase manually",
                pt.code, tier.remaining,
            )
            warnings.append(
                f"{pt.label} has {tier.remaining} spot(s) remaining after placing all applicants."
            )
    await db.flush()

    logger.info(
        "Lottery V2 draw complete for cycle %s: %d selected, %d waitlisted",
        cycle_id,
        len(selected),
        len(waitlisted),
    )

    return {
        "cycle_id": str(cycle_id),
        "total_applicants": total,
        "eligible_applicants": len(citation_clean),
        "selected_count": len(selected),
        "waitlisted_count": len(waitlisted),
        "filtered_test_entries": filtered_test,
        "filtered_unpaid_citations": filtered_citations,
        "filtered_duplicates": filtered_duplicates,
        "warnings": warnings,
        "run_at": now.isoformat(),
        "run_by": run_by,
    }


async def _tiers_with_offers_reserved(
    db: AsyncSession,
    cycle_id: uuid.UUID,
) -> dict[uuid.UUID, TierCapacity]:
    """Live remaining capacity — build_tier_capacities already accounts for
    active permits AND all selected offers globally, so no further adjustment needed."""
    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(LOTTERY_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    return await build_tier_capacities(db, list(pts))


async def _renumber_waitlist(db: AsyncSession, cycle_id: uuid.UUID) -> None:
    waitlisted = (
        await db.execute(
            select(LotteryV2Application)
            .where(
                LotteryV2Application.cycle_id == cycle_id,
                LotteryV2Application.status == "waitlisted",
            )
            .order_by(
                LotteryV2Application.waitlist_position.asc().nullslast(),
                LotteryV2Application.created_at.asc(),
            )
        )
    ).scalars().all()
    for i, app in enumerate(waitlisted, 1):
        app.waitlist_position = i


async def try_place_application(
    db: AsyncSession,
    app: LotteryV2Application,
    *,
    send_notification: bool = True,
) -> bool:
    """Try to place one pending/waitlisted app into remaining capacity. Returns True if selected."""
    if app.status not in ("pending", "waitlisted"):
        return False
    cycle = await db.get(LotteryV2Cycle, app.cycle_id)
    if not cycle:
        return False

    tiers = await _tiers_with_offers_reserved(db, app.cycle_id)
    applicant = WaterfallApplicant(
        id=app.id,
        class_year=app.class_year or 9999,
        created_at=app.created_at or datetime.now(timezone.utc),
        tier_preferences=_normalize_preferences(app.tier_preferences),
        student_email=app.student_email,
        student_name=app.student_name,
    )
    placement = try_place_one(applicant, tiers)
    if not placement:
        return False

    offer_days = cycle.offer_window_days or 5
    app.status = "selected"
    app.assigned_permit_type_id = placement.assigned_permit_type_id
    app.assigned_lot = placement.assigned_lot
    app.waitlist_position = None
    app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=offer_days)
    note = f"Placed into open capacity at {datetime.now(timezone.utc).isoformat()}"
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note

    await _renumber_waitlist(db, app.cycle_id)
    await db.flush()

    pt = await db.get(PermitType, placement.assigned_permit_type_id)
    if (
        send_notification
        and pt
        and app.student_email
        and not app.is_test_entry
        and app.offer_expires_at
    ):
        try:
            await send_lottery_selection_email(
                recipient_email=app.student_email,
                student_name=app.student_name,
                permit_type_label=pt.label,
                price=str(pt.price),
                deadline=app.offer_expires_at.strftime("%B %d, %Y"),
                portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
                assigned_lot=app.assigned_lot,
                lot_assignments=list(pt.lot_assignments or []),
            )
        except Exception as e:
            logger.error("Failed to notify placed applicant %s: %s", app.id, e)
    return True


def _email_key(app: LotteryV2Application) -> str:
    return (app.student_email or "").strip().lower() or f"sub:{app.student_sub}"


def _seniority_key(app: LotteryV2Application) -> tuple:
    return (
        app.class_year if app.class_year is not None else 9999,
        app.created_at or datetime.now(timezone.utc),
        app.lottery_rank if app.lottery_rank is not None else 10_000,
    )


async def _renumber_winner_ranks(db: AsyncSession, cycle_id: uuid.UUID) -> None:
    """Assign contiguous lottery_rank values for current winners (display + ordering)."""
    winners = list(
        (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status.in_(["selected", "accepted"]),
                )
            )
        ).scalars().all()
    )
    winners.sort(key=_seniority_key)
    for i, app in enumerate(winners, 1):
        app.lottery_rank = i


async def repair_cycle_placements(
    db: AsyncSession,
    cycle_id: uuid.UUID,
    *,
    send_notifications: bool = True,
) -> dict:
    """Fix a drawn cycle so placements match capacity and unique students.

    1. Collapse duplicate selected/accepted rows per email
    2. Supersede waitlist rows for emails that already won
    3. Demote excess *selected* offers over live remaining capacity; re-place via waterfall
    4. Place remaining true waitlisted into open seats
    5. Renumber waitlist + winner ranks for a clean admin view
    """
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise ValueError("Cycle not found")

    apps = list(
        (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id
                )
            )
        ).scalars().all()
    )

    # ── 1. Collapse duplicate selected/accepted rows per email ───────────────
    winners = [a for a in apps if a.status in ("selected", "accepted")]
    by_email: dict[str, list[LotteryV2Application]] = {}
    for app in winners:
        by_email.setdefault(_email_key(app), []).append(app)

    duplicates_demoted = 0
    for _key, group in by_email.items():
        if len(group) < 2:
            continue
        group_sorted = sorted(
            group,
            key=lambda a: (
                0 if a.status == "accepted" else 1,
                *_seniority_key(a),
            ),
        )
        keep = group_sorted[0]
        for extra in group_sorted[1:]:
            if extra.status == "accepted":
                continue  # never demote an accepted/paid permit
            extra.status = "superseded"
            extra.assigned_permit_type_id = None
            extra.assigned_lot = None
            extra.offer_expires_at = None
            extra.lottery_rank = None
            extra.waitlist_position = None
            note = (
                f"Repair: duplicate offer superseded; kept {keep.id} "
                f"({keep.status})."
            )
            extra.admin_notes = (
                f"{extra.admin_notes}\n{note}".strip() if extra.admin_notes else note
            )
            duplicates_demoted += 1

    await db.flush()

    # Refresh winner set after demotions
    winner_emails = {
        _email_key(a)
        for a in (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status.in_(["selected", "accepted"]),
                )
            )
        ).scalars().all()
    }

    # ── 2. Supersede phantom waitlist rows (same email already won) ───────────
    waitlisted_rows = list(
        (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status == "waitlisted",
                )
            )
        ).scalars().all()
    )
    superseded_waitlist = 0
    for app in waitlisted_rows:
        email = _email_key(app)
        if email in winner_emails:
            app.status = "superseded"
            app.waitlist_position = None
            app.lottery_rank = None
            note = "Repair: superseded — student already has a selected/accepted offer."
            app.admin_notes = (
                f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
            )
            superseded_waitlist += 1

    await db.flush()

    # ── 3. Enforce live remaining capacity on un-accepted selected offers ─────
    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(LOTTERY_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    base_tiers = await build_tier_capacities(db, list(pts))
    capacity_demoted = 0
    demoted_for_replace: list[LotteryV2Application] = []

    selected_apps = list(
        (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status == "selected",
                )
            )
        ).scalars().all()
    )
    by_tier: dict[uuid.UUID, list[LotteryV2Application]] = {}
    for app in selected_apps:
        ptid = _as_uuid(app.assigned_permit_type_id)
        if ptid:
            by_tier.setdefault(ptid, []).append(app)

    for ptid, group in by_tier.items():
        tier = base_tiers.get(ptid)
        if not tier:
            continue
        seats = max(0, tier.remaining)  # max_capacity − active permits
        group_sorted = sorted(group, key=_seniority_key)
        excess = group_sorted[seats:]
        for app in excess:
            app.status = "waitlisted"
            app.assigned_permit_type_id = None
            app.assigned_lot = None
            app.offer_expires_at = None
            app.lottery_rank = None
            note = (
                f"Repair: demoted over capacity for {tier.label} "
                f"(seats remaining vs active={seats})."
            )
            app.admin_notes = (
                f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
            )
            demoted_for_replace.append(app)
            capacity_demoted += 1

    await db.flush()

    # Re-place capacity-demoted into lower prefs before general waitlist
    newly_selected = 0
    newly_selected_emails: list[str] = []
    demoted_for_replace.sort(key=_seniority_key)
    for app in demoted_for_replace:
        email = _email_key(app)
        # They were just demoted — drop them from the winner set so re-place works
        # instead of immediately marking them superseded as "already won".
        winner_emails.discard(email)
        placed = await try_place_application(
            db, app, send_notification=send_notifications
        )
        if placed:
            newly_selected += 1
            newly_selected_emails.append(app.student_email or "")
            winner_emails.add(email)

    # ── 4. Place remaining true waitlisted into open seats ────────────────────
    waitlisted = [
        a
        for a in (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status == "waitlisted",
                )
            )
        ).scalars().all()
    ]
    waitlisted.sort(
        key=lambda a: (
            a.waitlist_position if a.waitlist_position is not None else 10_000,
            a.created_at or datetime.now(timezone.utc),
        )
    )

    skipped_already_won = 0
    for app in waitlisted:
        email = _email_key(app)
        if email in winner_emails:
            app.status = "superseded"
            app.waitlist_position = None
            note = "Repair: superseded — student already has a selected/accepted offer."
            app.admin_notes = (
                f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
            )
            skipped_already_won += 1
            continue
        placed = await try_place_application(
            db, app, send_notification=send_notifications
        )
        if placed:
            newly_selected += 1
            newly_selected_emails.append(app.student_email or "")
            winner_emails.add(email)

    await _renumber_waitlist(db, cycle_id)
    await _renumber_winner_ranks(db, cycle_id)
    await db.flush()

    remaining_waitlisted = (
        await db.execute(
            select(func.count())
            .select_from(LotteryV2Application)
            .where(
                LotteryV2Application.cycle_id == cycle_id,
                LotteryV2Application.status == "waitlisted",
            )
        )
    ).scalar() or 0

    return {
        "cycle_id": str(cycle_id),
        "duplicates_demoted": duplicates_demoted,
        "superseded_waitlist": superseded_waitlist + skipped_already_won,
        "capacity_demoted": capacity_demoted,
        "newly_selected": newly_selected,
        "newly_selected_emails": newly_selected_emails,
        "skipped_already_won": skipped_already_won,
        "remaining_waitlisted": remaining_waitlisted,
    }


async def bump_waitlist_to_top(
    db: AsyncSession,
    application_id: uuid.UUID,
) -> LotteryV2Application:
    """Move a waitlisted applicant to position #1."""
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise ValueError("Application not found")
    if app.status != "waitlisted":
        raise ValueError(f"Only waitlisted applicants can be bumped (status is '{app.status}')")

    others = (
        await db.execute(
            select(LotteryV2Application)
            .where(
                LotteryV2Application.cycle_id == app.cycle_id,
                LotteryV2Application.status == "waitlisted",
                LotteryV2Application.id != app.id,
            )
            .order_by(
                LotteryV2Application.waitlist_position.asc().nullslast(),
                LotteryV2Application.created_at.asc(),
            )
        )
    ).scalars().all()

    app.waitlist_position = 1
    note = f"Admin bumped to top of waitlist at {datetime.now(timezone.utc).isoformat()}"
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
    for i, other in enumerate(others, 2):
        other.waitlist_position = i

    await db.flush()
    return app


async def manual_select_application(
    db: AsyncSession,
    application_id: uuid.UUID,
    *,
    permit_type_id: uuid.UUID | None = None,
    send_notification: bool = True,
    admin_label: str = "admin",
    allow_any_type: bool = True,
    force_capacity: bool = False,
) -> LotteryV2Application:
    """Manually select an applicant into a permit type and email an offer."""
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise ValueError("Application not found")
    if app.status == "accepted":
        raise ValueError("Application is already accepted — cannot change the offer")
    if app.status not in ("waitlisted", "pending", "superseded", "expired", "declined", "selected"):
        raise ValueError(
            f"Can only offer waitlisted/pending/superseded/selected applicants (status is '{app.status}')"
        )

    cycle = await db.get(LotteryV2Cycle, app.cycle_id)
    if not cycle:
        raise ValueError("Cycle not found")

    if permit_type_id is None:
        raise ValueError("Choose a permit type for the offer")

    pt = await db.get(PermitType, permit_type_id)
    if not pt or not pt.is_active:
        raise ValueError("Invalid or inactive permit type")

    # Reassigning an existing selected offer — clear prior seat first
    if app.status == "selected":
        app.assigned_permit_type_id = None
        app.assigned_lot = None
        app.offer_expires_at = None
        app.status = "waitlisted"
        await db.flush()

    prefs = list(app.tier_preferences or [])
    if permit_type_id not in prefs:
        if not allow_any_type:
            raise ValueError("Chosen permit type is not in this applicant's preferences")
        prefs = [permit_type_id] + prefs
        app.tier_preferences = prefs

    tiers = await _tiers_with_offers_reserved(db, app.cycle_id)
    if permit_type_id not in tiers:
        built = await build_tier_capacities(db, [pt])
        if permit_type_id in built:
            tiers[permit_type_id] = built[permit_type_id]

    tier = tiers.get(permit_type_id)
    if not tier:
        raise ValueError(f"No capacity config for {pt.label}")
    if tier.remaining <= 0 and not force_capacity:
        raise ValueError(
            f"{pt.label} has no open seats. Enable force capacity to offer anyway."
        )

    if force_capacity and tier.remaining <= 0:
        lot = (list(pt.lot_assignments or []) or [None])[0]
        app.status = "selected"
        app.assigned_permit_type_id = permit_type_id
        app.assigned_lot = lot
        app.waitlist_position = None
        forced = True
    else:
        applicant = WaterfallApplicant(
            id=app.id,
            class_year=app.class_year,
            created_at=app.created_at or datetime.now(timezone.utc),
            tier_preferences=[permit_type_id],
            student_email=app.student_email,
            student_name=app.student_name,
        )
        placement = try_place_one(applicant, tiers)
        if not placement:
            raise ValueError(f"No remaining capacity in {pt.label}")
        app.status = "selected"
        app.assigned_permit_type_id = placement.assigned_permit_type_id
        app.assigned_lot = placement.assigned_lot
        app.waitlist_position = None
        forced = False

    offer_days = cycle.offer_window_days or 5
    app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=offer_days)
    note = (
        f"Offer sent by {admin_label} at {datetime.now(timezone.utc).isoformat()}"
        f" → {pt.label} ({app.assigned_lot or 'lot TBD'})"
        + (" [forced over capacity]" if forced else "")
    )
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note

    await _renumber_waitlist(db, app.cycle_id)
    await db.flush()

    if (
        send_notification
        and pt
        and app.student_email
        and not app.is_test_entry
        and app.offer_expires_at
    ):
        try:
            await send_lottery_selection_email(
                recipient_email=app.student_email,
                student_name=app.student_name,
                permit_type_label=pt.label,
                price=str(pt.price),
                deadline=app.offer_expires_at.strftime("%B %d, %Y"),
                portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
                assigned_lot=app.assigned_lot,
                lot_assignments=list(pt.lot_assignments or []),
            )
        except Exception as e:
            logger.error("Failed to notify manually selected applicant %s: %s", app.id, e)

    return app



async def promote_from_waitlist(
    db: AsyncSession,
    cycle_id: uuid.UUID,
    force: bool = False,
) -> LotteryV2Application | None:
    """After a decline, try to place the next waitlisted applicant via waterfall.
    
    If force=True, ignores auto_advance_waitlist flag (for manual admin advances).
    """
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        return None

    waitlisted = (
        await db.execute(
            select(LotteryV2Application)
            .where(
                LotteryV2Application.cycle_id == cycle_id,
                LotteryV2Application.status == "waitlisted",
            )
            .order_by(LotteryV2Application.waitlist_position.asc())
        )
    ).scalars().all()

    if not waitlisted:
        return None

    winner_emails = {
        _email_key(a)
        for a in (
            await db.execute(
                select(LotteryV2Application).where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status.in_(["selected", "accepted"]),
                )
            )
        ).scalars().all()
    }

    tiers = await _tiers_with_offers_reserved(db, cycle_id)

    # Exclude tiers that have auto-advance disabled (unless forced by admin)
    if not force:
        pts_all = (
            await db.execute(select(PermitType).where(PermitType.auto_advance_waitlist.is_(False)))
        ).scalars().all()
        frozen_type_ids = {pt.id for pt in pts_all}
        for tid in frozen_type_ids:
            tiers.pop(tid, None)

    promoted: LotteryV2Application | None = None
    remaining_waitlist = list(waitlisted)
    for app in waitlisted:
        email = _email_key(app)
        if email in winner_emails:
            # Skip without superseding — leave their waitlist row intact
            remaining_waitlist = [a for a in remaining_waitlist if a.id != app.id]
            continue
        applicant = WaterfallApplicant(
            id=app.id,
            class_year=app.class_year,
            created_at=app.created_at or datetime.now(timezone.utc),
            tier_preferences=list(app.tier_preferences or []),
            student_email=app.student_email,
            student_name=app.student_name,
        )
        placement = try_place_one(applicant, tiers)
        if placement:
            offer_days = cycle.offer_window_days or 5
            app.status = "selected"
            app.assigned_permit_type_id = placement.assigned_permit_type_id
            app.assigned_lot = placement.assigned_lot
            app.waitlist_position = None
            app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=offer_days)
            promoted = app
            remaining_waitlist = [a for a in waitlisted if a.id != app.id]
            pt = await db.get(PermitType, placement.assigned_permit_type_id)
            if pt and app.student_email and not app.is_test_entry:
                try:
                    await send_lottery_selection_email(
                        recipient_email=app.student_email,
                        student_name=app.student_name,
                        permit_type_label=pt.label,
                        price=str(pt.price),
                        deadline=app.offer_expires_at.strftime("%B %d, %Y"),
                        portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
                        assigned_lot=app.assigned_lot,
                        lot_assignments=list(pt.lot_assignments or []),
                    )
                except Exception as e:
                    logger.error("Failed to notify promoted applicant %s: %s", app.id, e)
            break

    for i, app in enumerate(remaining_waitlist, 1):
        app.waitlist_position = i

    await db.flush()
    return promoted


async def _notify_selected(
    selected: list[tuple[LotteryV2Application, PermitType]],
    offer_expires: datetime,
) -> None:
    failed_count = 0
    for app, pt in selected:
        if not app.student_email or app.is_test_entry:
            continue
        try:
            sent = await send_lottery_selection_email(
                recipient_email=app.student_email,
                student_name=app.student_name,
                permit_type_label=pt.label,
                price=str(pt.price),
                deadline=offer_expires.strftime("%B %d, %Y"),
                portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
                assigned_lot=app.assigned_lot,
                lot_assignments=list(pt.lot_assignments or []),
            )
            if not sent:
                failed_count += 1
                logger.error(
                    "Lottery offer email FAILED for %s (%s) — student may miss their offer window",
                    app.student_email, app.student_name,
                )
        except Exception as e:
            failed_count += 1
            logger.error("Failed to notify selected v2 applicant %s: %s", app.id, e)

    if failed_count > 0:
        logger.error(
            "LOTTERY NOTIFICATION SUMMARY: %d/%d offer emails FAILED to send — check notification health",
            failed_count, len([s for s in selected if s[0].student_email and not s[0].is_test_entry]),
        )


async def _notify_waitlisted(waitlisted: list[LotteryV2Application]) -> dict:
    school = settings.school_name or "Campus"
    from app.services.email import get_department_name

    dept = await get_department_name()
    sent = 0
    failed = 0
    skipped = 0
    for idx, app in enumerate(waitlisted):
        if not app.student_email or app.is_test_entry:
            skipped += 1
            continue
        try:
            position = app.waitlist_position or (idx + 1)
            first_name = extract_first_name(app.student_name)
            inner = (
                f'<h2 style="color:{settings.brand_primary_color};margin:0 0 8px;font-size:20px;">'
                f"Waitlisted &mdash; Parking Lottery</h2>"
                f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name}, '
                f"thank you for applying for a parking permit.</p>"
                '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;'
                'border-radius:8px;margin:20px 0;">'
                '<tr><td colspan="2" style="padding:12px 16px 4px;font-size:11px;color:#999;'
                'text-transform:uppercase;letter-spacing:1px;">Waitlist Status</td></tr>'
                '<tr style="border-bottom:1px solid #eee;">'
                '<td style="padding:10px 16px;color:#666;font-size:14px;">Your Position</td>'
                f'<td style="padding:10px 16px;font-weight:600;font-size:16px;'
                f'color:{settings.brand_primary_color};">#{position}</td></tr>'
                "</table>"
                '<p style="color:#333;font-size:14px;line-height:1.6;">You were not placed '
                "in any of your ranked tiers, but you are on the waitlist. If a selected "
                "student declines, you may receive an offer.</p>"
            )
            body_html = await branded_email_shell(school, inner)
            body_text = (
                f"WAITLISTED — Parking Lottery\n\n"
                f"Dear {first_name},\n\n"
                f"You were placed on the waitlist at position #{position}.\n\n"
                f"{school} {dept}"
            )
            ok = await send_email(
                to=[app.student_email],
                subject="Parking Permit Waitlisted",
                body_html=body_html,
                body_text=body_text,
            )
            if ok:
                sent += 1
            else:
                failed += 1
        except Exception as e:
            failed += 1
            logger.error("Failed to notify waitlisted v2 applicant %s: %s", app.id, e)
    return {"sent": sent, "failed": failed, "skipped": skipped}


async def notify_waitlisted_applicants(db: AsyncSession, cycle_id: uuid.UUID) -> dict:
    """Renumber then email everyone currently waitlisted on a cycle."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise ValueError("Cycle not found")

    await _renumber_waitlist(db, cycle_id)
    await db.flush()

    waitlisted = list(
        (
            await db.execute(
                select(LotteryV2Application)
                .where(
                    LotteryV2Application.cycle_id == cycle_id,
                    LotteryV2Application.status == "waitlisted",
                )
                .order_by(
                    LotteryV2Application.waitlist_position.asc().nullslast(),
                    LotteryV2Application.created_at.asc(),
                )
            )
        ).scalars().all()
    )
    result = await _notify_waitlisted(waitlisted)
    return {
        "cycle_id": str(cycle_id),
        "waitlisted_count": len(waitlisted),
        **result,
    }


async def complete_upgrade(
    db: AsyncSession,
    app: LotteryV2Application,
    new_pt: PermitType,
) -> Permit:
    """Complete an upgrade: revoke old permit, issue new one, advance old tier's waitlist."""
    from app.services.permit_numbering import next_permit_number
    from app.services.timeutils import today_local

    # Resolve the old permit type code for targeted search
    old_pt_code: str | None = None
    if app.existing_permit_type_id:
        old_pt_obj = await db.get(PermitType, app.existing_permit_type_id)
        if old_pt_obj:
            old_pt_code = old_pt_obj.code

    # Find and revoke the old permit — prefer matching by type code for accuracy
    old_permit = None
    if old_pt_code:
        old_permit = (
            await db.execute(
                select(Permit).where(
                    Permit.email == app.student_email,
                    Permit.permit_type == old_pt_code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                ).order_by(Permit.created_at.desc())
            )
        ).scalars().first()

    # Fallback: any active permit for this email
    if not old_permit:
        old_permit = (
            await db.execute(
                select(Permit).where(
                    Permit.email == app.student_email,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                ).order_by(Permit.created_at.desc())
            )
        ).scalars().first()

    # Revoke old permit if still active (may already be revoked by admin-upgrade)
    old_permit_type_code = old_pt_code
    if old_permit:
        old_permit_type_code = old_permit.permit_type
        old_permit.status = "upgraded"

    # Issue the new permit
    lot_assignment = ", ".join(new_pt.lot_assignments) if new_pt.lot_assignments else ""
    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=app.student_name,
        email=app.student_email or None,
        phone=app.phone or "",
        sms_opt_in=bool(app.sms_opt_in),
        plates=[app.plate],
        permit_type=new_pt.code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=new_pt.valid_days),
        status="active",
    )
    db.add(new_permit)

    # Mark the upgrade application as accepted
    app.status = "accepted"
    upgrade_note = (
        f"Upgrade completed at {datetime.now(timezone.utc).isoformat()} — "
        f"{new_pt.label} (from {old_permit_type_code or 'unknown'})"
    )
    app.admin_notes = f"{app.admin_notes}\n{upgrade_note}".strip() if app.admin_notes else upgrade_note

    await db.flush()

    # Advance the waitlist on the OLD tier (the vacated seat)
    if old_permit_type_code:
        old_pt_for_waitlist = (
            await db.execute(
                select(PermitType).where(PermitType.code == old_permit_type_code)
            )
        ).scalar_one_or_none()
        if old_pt_for_waitlist:
            await promote_from_waitlist(db, app.cycle_id)

    await db.flush()
    return new_permit
