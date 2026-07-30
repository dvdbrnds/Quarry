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
}

ALL_V2_TIER_CODES = [c for codes in CAMPUS_TIER_CODES.values() for c in codes]


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


def waterfall_place(
    applicants: list[WaterfallApplicant],
    tiers: dict[Any, TierCapacity],
) -> tuple[list[Placement], list[Placement], list[str]]:
    """Pure waterfall placement.

    Sort by (class_year ASC, created_at ASC). For each student, try ranked
    tiers until one has remaining capacity; assign a lot within that tier.
    Returns (selected, waitlisted, warnings).
    """
    ordered = sorted(applicants, key=lambda a: (a.class_year, a.created_at))
    selected: list[Placement] = []
    waitlisted: list[Placement] = []
    warnings: list[str] = []
    rank = 0

    for app in ordered:
        placed = False
        for ptid in app.tier_preferences:
            tier = tiers.get(ptid)
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
    for ptid in applicant.tier_preferences:
        tier = tiers.get(ptid)
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
    """Build remaining capacity map from live permit types and active permits."""
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
        remaining = max(0, (pt.max_capacity or 0) - active_count)
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
        raise ValueError("Close the application window before running the draw.")

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

    # Load all v2 permit types for capacity
    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(ALL_V2_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    tiers = await build_tier_capacities(db, list(pts))

    applicants = [
        WaterfallApplicant(
            id=a.id,
            class_year=a.class_year or 9999,
            created_at=a.created_at or datetime.now(timezone.utc),
            tier_preferences=list(a.tier_preferences or []),
            student_email=a.student_email,
            student_name=a.student_name,
        )
        for a in citation_clean
    ]

    selected, waitlisted, warnings = waterfall_place(applicants, tiers)

    offer_days = cycle.offer_window_days or 5
    offer_expires = datetime.now(timezone.utc) + timedelta(days=offer_days)
    app_by_id = {a.id: a for a in citation_clean}
    pt_by_id = {pt.id: pt for pt in pts}

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
        pt = pt_by_id.get(p.assigned_permit_type_id)
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
        "warnings": warnings,
        "run_at": now.isoformat(),
        "run_by": run_by,
    }


async def promote_from_waitlist(
    db: AsyncSession,
    cycle_id: uuid.UUID,
) -> LotteryV2Application | None:
    """After a decline, try to place the next waitlisted applicant via waterfall."""
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

    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(ALL_V2_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    tiers = await build_tier_capacities(db, list(pts))

    # Subtract already-selected (not yet accepted) from remaining capacity
    selected_apps = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle_id,
                LotteryV2Application.status.in_(["selected", "accepted"]),
            )
        )
    ).scalars().all()
    for app in selected_apps:
        if not app.assigned_permit_type_id:
            continue
        tier = tiers.get(app.assigned_permit_type_id)
        if not tier:
            continue
        tier.remaining = max(0, tier.remaining - 1)
        if app.assigned_lot and app.assigned_lot in tier.lot_remaining:
            tier.lot_remaining[app.assigned_lot] = max(
                0, tier.lot_remaining[app.assigned_lot] - 1
            )

    promoted: LotteryV2Application | None = None
    remaining_waitlist = list(waitlisted)
    for app in waitlisted:
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
                        portal_url=f"{settings.student_facing_url.rstrip('/')}/parking/lottery-v2",
                        assigned_lot=app.assigned_lot,
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
    for app, pt in selected:
        if not app.student_email or app.is_test_entry:
            continue
        try:
            await send_lottery_selection_email(
                recipient_email=app.student_email,
                student_name=app.student_name,
                permit_type_label=pt.label,
                price=str(pt.price),
                deadline=offer_expires.strftime("%B %d, %Y"),
                portal_url=f"{settings.student_facing_url.rstrip('/')}/parking/lottery-v2",
                assigned_lot=app.assigned_lot,
            )
        except Exception as e:
            logger.error("Failed to notify selected v2 applicant %s: %s", app.id, e)


async def _notify_waitlisted(waitlisted: list[LotteryV2Application]) -> None:
    school = settings.school_name or "Campus"
    from app.services.email import get_department_name

    dept = await get_department_name()
    for idx, app in enumerate(waitlisted):
        if not app.student_email or app.is_test_entry:
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
            await send_email(
                to=[app.student_email],
                subject="Parking Permit Waitlisted",
                body_html=body_html,
                body_text=body_text,
            )
        except Exception as e:
            logger.error("Failed to notify waitlisted v2 applicant %s: %s", app.id, e)
