"""Lottery V2 API — single-entry waterfall lottery (production).

Uses dedicated lottery_v2_* tables. Does not write to the legacy per-tier
permit_applications lottery tables.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, get_current_user_or_impersonated, require_admin
from ..config import settings
from ..database import get_db
from ..models.lottery_v2 import LotteryV2Application, LotteryV2AuditLog, LotteryV2Cycle
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..services.lottery_v2_runner import (
    ALL_V2_TIER_CODES,
    CAMPUS_TIER_CODES,
    LOTTERY_TIER_CODES,
    bump_waitlist_to_top,
    build_tier_capacities,
    class_year_eligible,
    manual_select_application,
    promote_from_waitlist,
    repair_cycle_placements,
    run_waterfall_draw,
    try_place_application,
    notify_waitlisted_applicants,
)
from ..services.permit_numbering import next_permit_number
from ..services.timeutils import today_local
from ..services.lot_assignment import permit_lot_matches

logger = logging.getLogger("quarry.lottery_v2")

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────


class CycleCreate(BaseModel):
    name: str = "Parking Lottery"
    offer_window_days: int = 5


class CycleRead(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    opens_at: datetime | None
    closes_at: datetime | None
    offer_window_days: int
    drawn_at: datetime | None
    drawn_by: str | None
    auto_draw_threshold: float | None = None
    auto_draw_at: datetime | None = None
    application_count: int = 0

    class Config:
        from_attributes = True


class TierRead(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    price: Decimal
    list_price: Decimal | None = None
    discount_amount: Decimal | None = None
    discount_label: str | None = None
    max_capacity: int
    remaining: int
    lot_assignments: list[str]
    min_class_year: int | None
    campus: str
    requires_lottery: bool = False
    is_purchasable_online: bool = False


class ApplicationSubmit(BaseModel):
    campus: str = Field(..., pattern="^(north|south)$")
    class_year: int
    plate: str
    plate_state: str = ""
    phone: str = Field(..., min_length=7)
    sms_opt_in: bool = False
    student_name: str | None = None
    tier_preferences: list[uuid.UUID] = Field(..., min_length=1)
    is_upgrade: bool = False


class ApplicationRead(BaseModel):
    id: uuid.UUID
    cycle_id: uuid.UUID
    student_name: str
    student_email: str
    class_year: int
    campus: str
    plate: str
    plate_state: str
    tier_preferences: list[uuid.UUID]
    tier_preference_labels: list[str] = []
    first_choice_label: str | None = None
    assigned_permit_type_id: uuid.UUID | None
    assigned_permit_type_label: str | None = None
    assigned_permit_type_price: Decimal | None = None
    assigned_permit_type_code: str | None = None
    assigned_permit_type_lots: list[str] = []
    assigned_lot: str | None
    status: str
    lottery_rank: int | None
    waitlist_position: int | None
    offer_expires_at: datetime | None
    admin_notes: str | None = None
    is_test_entry: bool
    fee_exempt: bool = False
    is_upgrade: bool = False
    existing_permit_type_id: uuid.UUID | None = None
    upgrade_credit: float | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class RunDrawRequest(BaseModel):
    include_test_entries: bool = True
    send_notifications: bool = True  # email selected + waitlisted applicants


# ── Helpers ──────────────────────────────────────────────────────────


async def _permit_type_map(db: AsyncSession) -> dict[uuid.UUID, PermitType]:
    pts = (await db.execute(select(PermitType))).scalars().all()
    return {pt.id: pt for pt in pts}


async def _cycle_to_read(db: AsyncSession, cycle: LotteryV2Cycle) -> CycleRead:
    count = (
        await db.execute(
            select(func.count())
            .select_from(LotteryV2Application)
            .where(LotteryV2Application.cycle_id == cycle.id)
        )
    ).scalar() or 0
    return CycleRead(
        id=cycle.id,
        name=cycle.name,
        status=cycle.status,
        opens_at=cycle.opens_at,
        closes_at=cycle.closes_at,
        offer_window_days=cycle.offer_window_days,
        drawn_at=cycle.drawn_at,
        drawn_by=cycle.drawn_by,
        auto_draw_threshold=cycle.auto_draw_threshold,
        auto_draw_at=cycle.auto_draw_at,
        application_count=count,
    )


async def _app_to_read(
    db: AsyncSession,
    app: LotteryV2Application,
    pt_by_id: dict[uuid.UUID, PermitType] | None = None,
) -> ApplicationRead:
    if pt_by_id is None:
        pt_by_id = await _permit_type_map(db)

    label = None
    price = None
    code = None
    lots: list[str] = []
    if app.assigned_permit_type_id:
        pt = pt_by_id.get(app.assigned_permit_type_id)
        if pt:
            label = pt.label
            price = pt.price
            code = pt.code
            lots = list(pt.lot_assignments or [])

    prefs = list(app.tier_preferences or [])
    preference_labels = [
        pt_by_id[tid].label if tid in pt_by_id else str(tid) for tid in prefs
    ]
    return ApplicationRead(
        id=app.id,
        cycle_id=app.cycle_id,
        student_name=app.student_name,
        student_email=app.student_email,
        class_year=app.class_year,
        campus=app.campus,
        plate=app.plate,
        plate_state=app.plate_state or "",
        tier_preferences=prefs,
        tier_preference_labels=preference_labels,
        first_choice_label=preference_labels[0] if preference_labels else None,
        assigned_permit_type_id=app.assigned_permit_type_id,
        assigned_permit_type_label=label,
        assigned_permit_type_price=price,
        assigned_permit_type_code=code,
        assigned_permit_type_lots=lots,
        assigned_lot=app.assigned_lot,
        status=app.status,
        lottery_rank=app.lottery_rank,
        waitlist_position=app.waitlist_position,
        offer_expires_at=app.offer_expires_at,
        admin_notes=app.admin_notes,
        is_test_entry=app.is_test_entry,
        fee_exempt=bool(app.fee_exempt),
        is_upgrade=bool(app.is_upgrade) if hasattr(app, "is_upgrade") else False,
        existing_permit_type_id=getattr(app, "existing_permit_type_id", None),
        upgrade_credit=getattr(app, "upgrade_credit", None),
        created_at=app.created_at,
    )


async def _maybe_auto_draw(db: AsyncSession, cycle: LotteryV2Cycle) -> None:
    """Fire the waterfall draw when any single tier is oversubscribed.

    For each lottery tier, count first-choice applications vs remaining capacity.
    If any tier's demand >= capacity * threshold, trigger the full draw.
    """
    if not cycle.auto_draw_threshold or cycle.status != "open":
        return

    from ..services.lottery_v2_runner import (
        LOTTERY_TIER_CODES as _LTC,
        build_tier_capacities,
    )

    pending_total = (
        await db.execute(
            select(func.count())
            .select_from(LotteryV2Application)
            .where(
                LotteryV2Application.cycle_id == cycle.id,
                LotteryV2Application.status == "pending",
            )
        )
    ).scalar() or 0
    # Avoid 1-person "draws" when leftover capacity is tiny
    if pending_total < 10:
        return

    pts = (
        await db.execute(
            select(PermitType).where(PermitType.code.in_(_LTC))
        )
    ).scalars().all()
    tiers = await build_tier_capacities(db, list(pts))

    # For each tier, count first-choice demand (tier_preferences[0])
    for pt_id, tier in tiers.items():
        if tier.remaining <= 0:
            continue
        # Count apps whose first-ranked tier is this one
        # Postgres arrays are 1-indexed; SQLAlchemy __getitem__ passes through as-is
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import UUID as PG_UUID

        first_choice_count = (
            await db.execute(
                select(func.count())
                .select_from(LotteryV2Application)
                .where(
                    LotteryV2Application.cycle_id == cycle.id,
                    LotteryV2Application.status == "pending",
                    cast(
                        LotteryV2Application.tier_preferences[1], PG_UUID(as_uuid=True)
                    ) == pt_id,
                )
            )
        ).scalar() or 0

        threshold_spots = tier.remaining * cycle.auto_draw_threshold
        if first_choice_count >= threshold_spots:
            logger.info(
                "Auto-draw triggered: tier %s (%s) has %d first-choice apps >= %d spots * %.0f%%",
                tier.code, tier.label, first_choice_count,
                tier.remaining, cycle.auto_draw_threshold * 100,
            )
            try:
                await run_waterfall_draw(db, cycle.id, run_by="auto_draw")
            except ValueError as e:
                logger.warning("Auto-draw skipped: %s", e)
            return


async def _eligible_tiers_for(
    db: AsyncSession,
    campus: str,
    class_year: int | None = None,
    prog_discount=None,
) -> list[TierRead]:
    from ..services.group_discount import apply_flat_discount

    codes = CAMPUS_TIER_CODES.get(campus, [])
    if not codes:
        return []
    pts = (
        await db.execute(
            select(PermitType)
            .where(PermitType.code.in_(codes), PermitType.is_active.is_(True))
            .order_by(PermitType.sort_order)
        )
    ).scalars().all()
    # Preserve campus code order
    by_code = {pt.code: pt for pt in pts}
    ordered = [by_code[c] for c in codes if c in by_code]

    out: list[TierRead] = []
    for pt in ordered:
        # Skip class-year filter when year unknown (intake map preview shows full path)
        if class_year is not None and not class_year_eligible(pt, class_year):
            continue
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
        your_price = apply_flat_discount(pt.price, prog_discount)
        out.append(
            TierRead(
                id=pt.id,
                code=pt.code,
                label=pt.label,
                price=your_price,
                list_price=pt.price if prog_discount else None,
                discount_amount=prog_discount.amount if prog_discount else None,
                discount_label=prog_discount.label if prog_discount else None,
                max_capacity=pt.max_capacity or 0,
                remaining=remaining,
                lot_assignments=list(pt.lot_assignments or []),
                min_class_year=pt.min_class_year,
                campus=campus,
                requires_lottery=bool(pt.requires_lottery),
                is_purchasable_online=bool(pt.is_purchasable_online),
            )
        )
    return out


# ── Student endpoints ────────────────────────────────────────────────


@router.get("/cycle", response_model=CycleRead)
async def get_open_cycle(
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Return the current open (or most recent drawn) cycle for students."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(LotteryV2Cycle)
        .where(LotteryV2Cycle.status == "open")
        .order_by(LotteryV2Cycle.created_at.desc())
        .limit(1)
    )
    cycle = result.scalar_one_or_none()
    if cycle:
        if cycle.closes_at and cycle.closes_at < now:
            cycle.status = "closed"
            await db.flush()
        else:
            return await _cycle_to_read(db, cycle)

    # After draw, still show cycle so students can see results
    result = await db.execute(
        select(LotteryV2Cycle)
        .where(LotteryV2Cycle.status.in_(["drawn", "closed"]))
        .order_by(LotteryV2Cycle.created_at.desc())
        .limit(1)
    )
    cycle = result.scalar_one_or_none()
    if not cycle:
        raise HTTPException(404, "No lottery cycle available")
    return await _cycle_to_read(db, cycle)


@router.get("/eligible-tiers", response_model=list[TierRead])
async def eligible_tiers(
    campus: str = Query(..., pattern="^(north|south|commuter)$"),
    class_year: int | None = Query(None, ge=2000, le=2100),
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    from ..services.group_discount import resolve_program_discount
    prog_discount = await resolve_program_discount(db, user)
    return await _eligible_tiers_for(db, campus, class_year, prog_discount)


@router.post("/applications", response_model=ApplicationRead, status_code=201)
async def submit_application(
    data: ApplicationSubmit,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    # Accept applications on open cycles, or as waitlist entries on drawn cycles
    cycle = (
        await db.execute(
            select(LotteryV2Cycle)
            .where(LotteryV2Cycle.status.in_(["open", "drawn"]))
            .order_by(LotteryV2Cycle.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not cycle:
        raise HTTPException(400, "No open lottery cycle — applications are closed")

    now = datetime.now(timezone.utc)
    if cycle.status == "open":
        if cycle.opens_at and cycle.opens_at > now:
            raise HTTPException(400, "Application window has not opened yet")
        if cycle.closes_at and cycle.closes_at < now:
            raise HTTPException(400, "Application window has closed")

    existing = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle.id,
                LotteryV2Application.student_sub == user.sub,
                LotteryV2Application.status.notin_(["superseded", "declined", "expired"]),
            )
        )
    ).scalars().all()

    # Upgrade / additional waitlist path
    accepted_app = next((a for a in existing if a.status == "accepted"), None)
    waitlisted_app = next((a for a in existing if a.status == "waitlisted"), None)
    if data.is_upgrade:
        if not accepted_app and not waitlisted_app:
            raise HTTPException(400, "You must have an existing application to join another waitlist")
        # For accepted students, only allow higher-priced tiers (no refunds)
        if accepted_app:
            pt_map = await _permit_type_map(db)
            current_pt = pt_map.get(accepted_app.assigned_permit_type_id)
            if not current_pt:
                raise HTTPException(400, "Cannot determine your current permit type")
            for tid in data.tier_preferences:
                target_pt = pt_map.get(tid)
                if not target_pt or target_pt.price <= current_pt.price:
                    raise HTTPException(400, "Upgrade waitlist is only for higher-priced tiers")
        # Block duplicate waitlist for the same tier
        existing_upgrade = next(
            (a for a in existing if a.is_upgrade and set(a.tier_preferences or []) & set(data.tier_preferences)),
            None,
        )
        if existing_upgrade:
            raise HTTPException(400, "You are already on the waitlist for this tier")
    else:
        # Standard path: only one non-upgrade application allowed
        non_upgrade = [a for a in existing if not a.is_upgrade]
        if non_upgrade:
            raise HTTPException(400, "You already have an application for this lottery")

    # Revive a dead row (superseded / declined / expired) instead of blocking re-apply
    revived = None
    if not data.is_upgrade:
        revived = (
            await db.execute(
                select(LotteryV2Application)
                .where(
                    LotteryV2Application.cycle_id == cycle.id,
                    LotteryV2Application.student_sub == user.sub,
                    LotteryV2Application.status.in_(["superseded", "declined", "expired"]),
                    LotteryV2Application.is_upgrade.is_(False),
                )
                .order_by(LotteryV2Application.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    eligible = await _eligible_tiers_for(db, data.campus, data.class_year)
    eligible_ids = {t.id for t in eligible}
    if not data.tier_preferences:
        raise HTTPException(400, "Rank at least one tier")
    if any(tid not in eligible_ids for tid in data.tier_preferences):
        raise HTTPException(400, "One or more ranked tiers are not eligible for you")
    if len(set(data.tier_preferences)) != len(data.tier_preferences):
        raise HTTPException(400, "Duplicate tier preferences are not allowed")

    name = (
        data.student_name
        or user.display_name
        or f"{user.given_name} {user.family_name}".strip()
        or user.email
    )
    phone = data.phone.strip()

    if revived:
        prior_status = revived.status
        app = revived
        app.student_email = user.email
        app.student_name = name
        app.class_year = data.class_year
        app.campus = data.campus
        app.plate = data.plate.strip().upper()
        app.plate_state = (data.plate_state or "").strip().upper()[:2]
        app.phone = phone
        app.sms_opt_in = bool(data.sms_opt_in)
        app.tier_preferences = list(data.tier_preferences)
        app.status = "pending"
        app.waitlist_position = None
        app.lottery_rank = None
        app.assigned_permit_type_id = None
        app.assigned_lot = None
        app.offer_expires_at = None
        note = (
            f"Revived from {prior_status} at {datetime.now(timezone.utc).isoformat()}"
        )
        app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
    else:
        app = LotteryV2Application(
            cycle_id=cycle.id,
            student_sub=user.sub,
            student_email=user.email,
            student_name=name,
            class_year=data.class_year,
            campus=data.campus,
            plate=data.plate.strip().upper(),
            plate_state=(data.plate_state or "").strip().upper()[:2],
            phone=phone,
            sms_opt_in=bool(data.sms_opt_in),
            tier_preferences=list(data.tier_preferences),
            status="pending",
            is_test_entry=False,
            is_upgrade=data.is_upgrade,
            existing_permit_type_id=accepted_app.assigned_permit_type_id if data.is_upgrade and accepted_app else None,
            upgrade_credit=float(current_pt.price) if data.is_upgrade and accepted_app else None,
        )

    from ..services.fee_exempt import lookup_fee_exempt

    exempt = await lookup_fee_exempt(
        db,
        user,
        extra_emails=[user.email],
        extra_names=[name],
    )
    if exempt:
        app.fee_exempt = True

    # If the draw already happened, try open seats first — only waitlist if full
    # Upgrade waitlist entries always go straight to waitlist (they already hold a permit)
    if cycle.status == "drawn":
        if not revived:
            db.add(app)
        await db.flush()
        if data.is_upgrade:
            placed = False
        else:
            placed = await try_place_application(db, app, send_notification=True)
        if not placed:
            max_pos = (
                await db.execute(
                    select(func.max(LotteryV2Application.waitlist_position)).where(
                        LotteryV2Application.cycle_id == cycle.id
                    )
                )
            ).scalar() or 0
            app.status = "waitlisted"
            app.waitlist_position = max_pos + 1
            await db.flush()
    else:
        if not revived:
            db.add(app)
        await db.flush()

    # Opt into parking + emergency SMS now; Phase 23 expands to all AlertUs channels
    if data.sms_opt_in and phone:
        from .student_permits import _opt_in_alerts

        await _opt_in_alerts(db, name, user.email, phone)

    # Check if auto-draw threshold is reached
    if cycle.status == "open":
        await _maybe_auto_draw(db, cycle)

    return await _app_to_read(db, app)


@router.get("/applications/me", response_model=ApplicationRead | None)
async def my_application(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Return this student's application for the current cycle only.

    Scoped to the open cycle when one exists, otherwise the latest drawn/closed
    cycle — never an older cycle's application that would block a new open window.
    """
    now = datetime.now(timezone.utc)
    cycle = (
        await db.execute(
            select(LotteryV2Cycle)
            .where(LotteryV2Cycle.status == "open")
            .order_by(LotteryV2Cycle.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if cycle and cycle.closes_at and cycle.closes_at < now:
        cycle.status = "closed"
        await db.flush()
        cycle = None

    if not cycle:
        cycle = (
            await db.execute(
                select(LotteryV2Cycle)
                .where(LotteryV2Cycle.status.in_(["drawn", "closed"]))
                .order_by(LotteryV2Cycle.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if not cycle:
        return None

    app = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle.id,
                LotteryV2Application.student_sub == user.sub,
            )
        )
    ).scalars().all()
    if not app:
        # Fallback: match by email when duplicate rows used different subs
        email = (user.email or "").strip().lower()
        if email:
            app = (
                await db.execute(
                    select(LotteryV2Application).where(
                        LotteryV2Application.cycle_id == cycle.id,
                        func.lower(LotteryV2Application.student_email) == email,
                    )
                )
            ).scalars().all()
    if not app:
        return None
    # Superseded / declined / expired are dead — let the student re-apply
    active = [a for a in app if a.status not in ("superseded", "declined", "expired")]
    # Filter out upgrade apps — they have their own endpoint
    active = [a for a in active if not a.is_upgrade]
    if not active:
        return None
    priority = {
        "accepted": 0,
        "selected": 1,
        "pending": 2,
        "waitlisted": 3,
        "expired": 4,
        "declined": 5,
        "ineligible": 6,
    }
    best = sorted(
        active,
        key=lambda a: (
            priority.get(a.status, 99),
            a.created_at or datetime(1970, 1, 1, tzinfo=timezone.utc),
        ),
    )[0]

    # Live roster check so RAs see discount info before paying
    if not best.fee_exempt:
        from ..services.fee_exempt import lookup_fee_exempt

        exempt = await lookup_fee_exempt(
            db,
            user,
            extra_emails=[best.student_email, user.email],
            extra_names=[best.student_name, user.display_name],
        )
        if exempt:
            best.fee_exempt = True
            await db.flush()

    return await _app_to_read(db, best)


@router.get("/applications/me/upgrades", response_model=list[ApplicationRead])
async def my_upgrade_applications(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Return this student's upgrade waitlist applications for the current cycle."""
    cycle = (
        await db.execute(
            select(LotteryV2Cycle)
            .where(LotteryV2Cycle.status.in_(["open", "drawn", "closed"]))
            .order_by(LotteryV2Cycle.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not cycle:
        return []

    apps = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle.id,
                LotteryV2Application.student_sub == user.sub,
                LotteryV2Application.is_upgrade.is_(True),
                LotteryV2Application.status.notin_(["superseded", "declined", "expired"]),
            )
        )
    ).scalars().all()

    if not apps:
        email = (user.email or "").strip().lower()
        if email:
            apps = (
                await db.execute(
                    select(LotteryV2Application).where(
                        LotteryV2Application.cycle_id == cycle.id,
                        func.lower(LotteryV2Application.student_email) == email,
                        LotteryV2Application.is_upgrade.is_(True),
                        LotteryV2Application.status.notin_(["superseded", "declined", "expired"]),
                    )
                )
            ).scalars().all()

    return [await _app_to_read(db, a) for a in apps]


@router.post("/applications/{application_id}/accept")
async def accept_offer(
    application_id: uuid.UUID,
    body: dict | None = Body(None),
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Accept a v2 lottery offer — Stripe checkout or fee-exempt issuance."""
    # Lock the row to prevent concurrent double-accept from rapid clicks
    app = (
        await db.execute(
            select(LotteryV2Application)
            .where(LotteryV2Application.id == application_id)
            .with_for_update(nowait=False)
        )
    ).scalar_one_or_none()
    if not app:
        raise HTTPException(404, "Application not found")
    if app.student_sub != user.sub:
        raise HTTPException(403, "Not your application")
    if app.status != "selected":
        raise HTTPException(400, f"Cannot accept an application with status '{app.status}'")

    now = datetime.now(timezone.utc)
    if app.offer_expires_at and now > app.offer_expires_at:
        app.status = "expired"
        await db.flush()
        raise HTTPException(400, "Offer has expired")

    if not app.assigned_permit_type_id:
        raise HTTPException(400, "No permit type assigned")

    # Allow student to confirm/update vehicle info before paying
    body = body or {}
    plate = (body.get("plate") or "").strip().upper()
    plate_state = (body.get("plate_state") or "").strip().upper()[:2]
    phone = (body.get("phone") or "").strip()
    if plate:
        app.plate = plate
    if plate_state:
        app.plate_state = plate_state
    if phone:
        app.phone = phone
    if not app.plate:
        raise HTTPException(400, "License plate is required to accept this offer")

    pt = await db.get(PermitType, app.assigned_permit_type_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    # Fee-exempt roster (Res Life Staff etc.) — skip Stripe for everyone on the list
    from ..services.fee_exempt import lookup_fee_exempt

    exempt = await lookup_fee_exempt(
        db,
        user,
        extra_emails=[app.student_email],
        extra_names=[app.student_name, user.display_name if hasattr(user, "display_name") else None],
    )
    if exempt:
        app.fee_exempt = True

    # ── Program discount (ABSN) + optional voucher ────────────────────────────
    from ..models.voucher import Voucher
    from ..routers.vouchers import _validate_voucher
    from ..services.group_discount import resolve_program_discount, apply_flat_discount

    prog_discount = await resolve_program_discount(db, user)
    discounted_price = apply_flat_discount(pt.price, prog_discount)
    applied_voucher: Voucher | None = None
    voucher_code = (body or {}).get("voucher_code", "")
    discount_note = f" | {prog_discount.label}: −${prog_discount.amount:.0f}" if prog_discount else ""

    if app.fee_exempt:
        ra_amount = Decimal(str(settings.ra_discount_amount))
        ra_price = max(Decimal("0.00"), pt.price - ra_amount)
        if ra_price < discounted_price:
            discounted_price = ra_price
            discount_note = f" | RA Discount: −${ra_amount:.0f}"

    if voucher_code:
        voucher_result = await db.execute(
            select(Voucher).where(func.upper(Voucher.code) == voucher_code.upper().strip())
        )
        applied_voucher = voucher_result.scalar()
        if not applied_voucher:
            raise HTTPException(400, "Invalid voucher code.")
        error = _validate_voucher(applied_voucher, pt.code)
        if error:
            raise HTTPException(400, error)

        voucher_price = pt.price
        if applied_voucher.discount_type == "full":
            voucher_price = Decimal("0.00")
        elif applied_voucher.discount_type == "percent":
            voucher_price = pt.price * (Decimal("100") - applied_voucher.discount_value) / Decimal("100")
        elif applied_voucher.discount_type == "flat":
            voucher_price = max(Decimal("0.00"), pt.price - applied_voucher.discount_value)
        if voucher_price < discounted_price:
            discounted_price = voucher_price
            discount_note = f" | Voucher: {applied_voucher.code}"
        else:
            applied_voucher = None

    if discounted_price <= 0:
        lot_assignment = ", ".join(pt.lot_assignments) if pt.lot_assignments else ""
        new_permit = Permit(
            permit_number=await next_permit_number(db),
            name=app.student_name,
            email=app.student_email or None,
            phone=app.phone or "",
            sms_opt_in=bool(app.sms_opt_in),
            plates=[app.plate],
            permit_type=pt.code,
            lot_assignment=lot_assignment,
            start_date=today_local(),
            end_date=today_local() + timedelta(days=pt.valid_days),
            status="active",
        )
        db.add(new_permit)
        method = "voucher" if applied_voucher else "program_discount"
        desc = (
            f"Voucher {applied_voucher.code} ({applied_voucher.program_name}) — {pt.code} — {app.plate}"
            if applied_voucher
            else f"{prog_discount.label if prog_discount else 'Program Discount'} — {pt.code} — {app.plate}"
        )
        db.add(Payment(
            amount=Decimal("0.00"),
            method=method,
            payment_type="lottery_v2_permit",
            payer_name=app.student_name or None,
            payer_email=app.student_email or None,
            plate=app.plate or None,
            description=desc,
        ))
        if applied_voucher:
            applied_voucher.current_uses += 1
            from .vouchers import record_voucher_usage
            await record_voucher_usage(db, applied_voucher, app.student_name, app.student_email, user.sub, pt.code, pt.price, Decimal("0.00"))
        app.status = "accepted"
        await db.flush()
        return {
            "status": "accepted",
            "fee_exempt": False,
            "voucher": bool(applied_voucher),
            "program_discount": bool(prog_discount) and not applied_voucher,
        }

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    # Upgrade pricing: charge only the difference
    charge_amount = discounted_price
    is_upgrade_checkout = bool(app.is_upgrade)
    if is_upgrade_checkout and app.upgrade_credit:
        charge_amount = max(Decimal("0.00"), discounted_price - Decimal(str(app.upgrade_credit)))

    if is_upgrade_checkout and charge_amount <= 0:
        # Free upgrade (edge case: discount covers the difference)
        from ..services.lottery_v2_runner import complete_upgrade
        await complete_upgrade(db, app, pt)
        return {"status": "accepted", "fee_exempt": False, "upgrade": True, "charge_amount": "0.00"}

    product_name = f"{pt.label} Parking Permit"
    product_desc = f"Plate: {app.plate} | Valid for {pt.valid_days} days" + discount_note
    if is_upgrade_checkout:
        product_name = f"Upgrade to {pt.label}"
        product_desc = f"Plate: {app.plate} | Difference from current permit" + discount_note

    session = stripe.checkout.Session.create(
        customer_email=app.student_email,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": product_name,
                        "description": product_desc,
                    },
                    "unit_amount": int(charge_amount * 100),
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "lottery_v2_permit",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "permit_type_code": pt.code,
                "permit_type_label": pt.label,
                "permit_price": str(pt.price),
                "permit_valid_days": str(pt.valid_days),
                "plate": app.plate,
                "student_name": app.student_name,
                "student_email": app.student_email,
                "class_year": str(app.class_year) if app.class_year else "",
                "application_id": str(app.id),
                "lottery_rank": str(app.lottery_rank) if app.lottery_rank else "",
                "assigned_lot": app.assigned_lot or "",
                "lot_assignments": ",".join(pt.lot_assignments) if pt.lot_assignments else "",
                "phone": app.phone or "",
                "sms_opt_in": "true" if app.sms_opt_in else "false",
                "institution": settings.school_name or "moravian",
                "program_discount": prog_discount.label if prog_discount else "",
                "program_discount_amount": str(prog_discount.amount) if prog_discount else "",
            },
        },
        success_url=f"{base_url}/parking?accepted={application_id}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/parking",
        metadata={
            "type": "lottery_v2_permit",
            "application_id": str(app.id),
            "permit_type_id": str(pt.id),
            "permit_type_code": pt.code,
            "student_name": app.student_name,
            "plate": app.plate,
            "email": app.student_email,
            "valid_days": str(pt.valid_days),
            "assigned_lot": app.assigned_lot or "",
            "phone": app.phone or "",
            "sms_opt_in": "true" if app.sms_opt_in else "false",
            "voucher_code": applied_voucher.code if applied_voucher else "",
            "program_discount": prog_discount.label if prog_discount else "",
            "program_discount_amount": str(prog_discount.amount) if prog_discount else "",
            "is_upgrade": "true" if is_upgrade_checkout else "false",
        },
    )

    if applied_voucher:
        applied_voucher.current_uses += 1
        from .vouchers import record_voucher_usage
        await record_voucher_usage(db, applied_voucher, app.student_name, app.student_email, user.sub, pt.code, pt.price, discounted_price)
        await db.flush()

    # Mark payment-stage entry on the application for admin case view
    note = (
        f"Payment started (Stripe checkout {session.id}) by {user.email or user.sub} at "
        f"{datetime.now(timezone.utc).isoformat()} — {pt.label} ${discounted_price}"
    )
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
    await db.flush()

    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/applications/{application_id}/decline")
async def decline_offer(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.student_sub != user.sub and not (user.email or "").lower() == (app.student_email or "").lower():
        # Admin impersonation uses synthetic sub; also allow email match
        if not (user.sub or "").startswith("impersonated:"):
            raise HTTPException(403, "Not your application")
        if (user.email or "").lower() != (app.student_email or "").lower():
            raise HTTPException(403, "Not your application")
    if app.status != "selected":
        raise HTTPException(400, f"Cannot decline an application with status '{app.status}'")

    app.status = "declined"
    app.assigned_permit_type_id = None
    app.assigned_lot = None
    await db.flush()

    promoted = await promote_from_waitlist(db, app.cycle_id)
    return {
        "status": "declined",
        "promoted_application_id": str(promoted.id) if promoted else None,
    }


class ManualSelectRequest(BaseModel):
    permit_type_id: uuid.UUID | None = None
    send_notification: bool = True
    # When True, assign even if the type is not in the student's ranked prefs
    allow_any_type: bool = True
    # When True, assign even if live remaining capacity is 0 (admin override)
    force_capacity: bool = False


@router.post("/applications/{application_id}/bump-waitlist", response_model=ApplicationRead)
async def admin_bump_waitlist(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Move a waitlisted applicant to position #1."""
    try:
        app = await bump_waitlist_to_top(db, application_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return await _app_to_read(db, app)


@router.post("/applications/{application_id}/restore-waitlist", response_model=ApplicationRead)
async def admin_restore_waitlist(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Restore a superseded (or expired/declined) application onto the waitlist."""
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.status in ("accepted", "waitlisted", "pending"):
        raise HTTPException(400, f"Cannot restore an application with status '{app.status}'")
    # Also allow clearing a selected offer back to waitlist (admin reassignment prep)
    if app.status not in ("superseded", "expired", "declined", "selected"):
        raise HTTPException(400, f"Cannot restore an application with status '{app.status}'")

    max_pos = (
        await db.execute(
            select(func.max(LotteryV2Application.waitlist_position)).where(
                LotteryV2Application.cycle_id == app.cycle_id
            )
        )
    ).scalar() or 0
    app.status = "waitlisted"
    app.waitlist_position = max_pos + 1
    app.assigned_permit_type_id = None
    app.assigned_lot = None
    app.offer_expires_at = None
    app.lottery_rank = None
    note = (
        f"Admin restored to waitlist #{app.waitlist_position} by "
        f"{admin.email or admin.sub} at {datetime.now(timezone.utc).isoformat()}"
    )
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
    await db.flush()
    return await _app_to_read(db, app)


@router.post("/applications/{application_id}/remove")
async def admin_delete_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Permanently delete a duplicate application."""
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")

    email = app.student_email
    name = app.student_name
    status = app.status
    tier = app.assigned_permit_type_id

    await db.delete(app)
    await db.flush()

    logger.info(
        "Admin %s deleted application %s (%s / %s / was %s)",
        admin.email or admin.sub, application_id, name, email, status,
    )
    return {"deleted": True, "id": str(application_id), "name": name, "email": email}


@router.get("/applications/search", response_model=list[ApplicationRead])
async def admin_search_applications(
    email: str,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Search applications by student email across all cycles and statuses."""
    apps = (
        await db.execute(
            select(LotteryV2Application)
            .where(LotteryV2Application.student_email.ilike(f"%{email}%"))
            .order_by(LotteryV2Application.created_at.desc())
        )
    ).scalars().all()
    pt_by_id = await _permit_type_map(db)
    return [await _app_to_read(db, a, pt_by_id) for a in apps]


class AdminAddApplication(BaseModel):
    email: str
    permit_type_id: uuid.UUID
    campus: str = "north"


@router.post("/applications/admin-add", response_model=ApplicationRead, status_code=201)
async def admin_add_to_waitlist(
    data: AdminAddApplication,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Admin: create a new waitlist entry for a student by email + permit type."""
    import httpx
    from sqlalchemy import text

    email = data.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")

    # Resolve student identity (Okta first, then DB fallback)
    sub = ""
    name = email
    class_year: int | None = None

    if settings.okta_domain and settings.okta_api_token:
        try:
            async with httpx.AsyncClient() as client:
                user_res = await client.get(
                    f"https://{settings.okta_domain}/api/v1/users/{email}",
                    headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                    timeout=10,
                )
                if user_res.status_code == 200:
                    okta_user = user_res.json()
                    sub = okta_user.get("id", "")
                    profile = okta_user.get("profile", {})
                    name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or email
                    cy = profile.get(settings.okta_class_year_claim)
                    if cy:
                        try:
                            class_year = int(cy)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass

    # DB fallback: check existing lottery apps or permits
    if not sub:
        app_row = (await db.execute(text("""
            SELECT student_sub, student_name, class_year
            FROM lottery_v2_applications
            WHERE LOWER(student_email) = :email
            ORDER BY created_at DESC LIMIT 1
        """), {"email": email})).mappings().first()
        if app_row:
            sub = app_row["student_sub"] or ""
            name = app_row["student_name"] or email
            class_year = app_row["class_year"]
        else:
            perm_row = (await db.execute(text("""
                SELECT student_id as sub, name FROM permits
                WHERE LOWER(email) = :email AND deleted_at IS NULL
                ORDER BY created_at DESC LIMIT 1
            """), {"email": email})).mappings().first()
            if perm_row:
                sub = perm_row["sub"] or ""
                name = perm_row["name"] or email

    if not sub:
        sub = f"admin-added:{email}"

    # Get the active/drawn cycle
    cycle = (
        await db.execute(
            select(LotteryV2Cycle)
            .where(LotteryV2Cycle.status.in_(["open", "drawn"]))
            .order_by(LotteryV2Cycle.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not cycle:
        raise HTTPException(400, "No active lottery cycle")

    # Validate permit type
    pt = await db.get(PermitType, data.permit_type_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    # Check for duplicate non-upgrade app
    existing = (await db.execute(
        select(LotteryV2Application).where(
            LotteryV2Application.cycle_id == cycle.id,
            LotteryV2Application.student_sub == sub,
            LotteryV2Application.is_upgrade.is_(False),
            LotteryV2Application.status.notin_(["superseded", "declined", "expired"]),
        )
    )).scalars().all()
    if existing:
        raise HTTPException(400, f"{name} already has an active application in this cycle")

    # Pull plate/phone from most recent app if available
    prev_app = (await db.execute(
        select(LotteryV2Application).where(
            LotteryV2Application.student_sub == sub,
        ).order_by(LotteryV2Application.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    plate = prev_app.plate if prev_app else "ADMIN-ADDED"
    plate_state = prev_app.plate_state if prev_app else ""
    phone = prev_app.phone if prev_app else ""
    if not class_year and prev_app:
        class_year = prev_app.class_year

    # Calculate waitlist position
    max_pos = (
        await db.execute(
            select(func.max(LotteryV2Application.waitlist_position)).where(
                LotteryV2Application.cycle_id == cycle.id
            )
        )
    ).scalar() or 0

    app = LotteryV2Application(
        cycle_id=cycle.id,
        student_sub=sub,
        student_email=email,
        student_name=name,
        class_year=class_year or 2027,
        campus=data.campus,
        plate=plate,
        plate_state=plate_state,
        phone=phone or "",
        tier_preferences=[data.permit_type_id],
        assigned_permit_type_id=data.permit_type_id,
        status="waitlisted",
        waitlist_position=max_pos + 1,
        admin_notes=f"Added by {admin.email}",
    )
    db.add(app)

    # Check fee-exempt roster
    from ..services.fee_exempt import lookup_fee_exempt
    temp_user = OktaUser(sub=sub, email=email, groups=[], given_name=name.split(" ", 1)[0], family_name=name.split(" ", 1)[1] if " " in name else "")
    exempt = await lookup_fee_exempt(db, temp_user, extra_emails=[email], extra_names=[name])
    if exempt:
        app.fee_exempt = True

    await db.flush()
    logger.info("Admin %s added %s (%s) to waitlist pos %d for %s", admin.email, name, email, app.waitlist_position, pt.label)
    return await _app_to_read(db, app)


@router.post("/applications/{application_id}/manual-select", response_model=ApplicationRead)
async def admin_manual_select(
    application_id: uuid.UUID,
    data: ManualSelectRequest | None = None,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Manually select a pending/waitlisted applicant into available capacity."""
    opts = data or ManualSelectRequest()
    try:
        app = await manual_select_application(
            db,
            application_id,
            permit_type_id=opts.permit_type_id,
            send_notification=opts.send_notification,
            admin_label=admin.email or admin.sub,
            allow_any_type=opts.allow_any_type,
            force_capacity=opts.force_capacity,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return await _app_to_read(db, app)


class AdminUpgradeRequest(BaseModel):
    permit_type_id: uuid.UUID
    send_notification: bool = True


@router.post("/applications/{application_id}/admin-upgrade")
async def admin_upgrade_permit(
    application_id: uuid.UUID,
    data: AdminUpgradeRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Admin-initiated upgrade for a student who already purchased a permit.

    Creates a Stripe checkout for the price difference and transitions the
    application so the existing accept -> webhook -> complete_upgrade pipeline
    handles the rest.
    """
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.status != "accepted":
        raise HTTPException(400, f"Can only upgrade an accepted application (status is '{app.status}')")

    # Look up the student's current permit type from the accepted application
    if not app.assigned_permit_type_id:
        raise HTTPException(400, "Application has no assigned permit type")
    old_pt = await db.get(PermitType, app.assigned_permit_type_id)
    if not old_pt:
        raise HTTPException(400, "Current permit type not found")

    new_pt = await db.get(PermitType, data.permit_type_id)
    if not new_pt or not new_pt.is_active:
        raise HTTPException(400, "Target permit type not found or inactive")

    if new_pt.price <= old_pt.price:
        raise HTTPException(400, f"Target tier ({new_pt.label}: ${new_pt.price}) must cost more than current ({old_pt.label}: ${old_pt.price})")

    # Apply any applicable discounts to the new price
    from ..services.group_discount import resolve_program_discount, apply_flat_discount

    admin_as_user = OktaUser(sub=app.student_sub, email=app.student_email, groups=[])
    prog_discount = await resolve_program_discount(db, admin_as_user)
    new_discounted = apply_flat_discount(new_pt.price, prog_discount)
    old_discounted = apply_flat_discount(old_pt.price, prog_discount)

    from ..services.fee_exempt import lookup_fee_exempt

    exempt = await lookup_fee_exempt(
        db, admin_as_user,
        extra_emails=[app.student_email],
        extra_names=[app.student_name],
    )
    if exempt:
        ra_amount = Decimal(str(settings.ra_discount_amount))
        new_ra_price = max(Decimal("0.00"), new_pt.price - ra_amount)
        old_ra_price = max(Decimal("0.00"), old_pt.price - ra_amount)
        if new_ra_price < new_discounted:
            new_discounted = new_ra_price
        if old_ra_price < old_discounted:
            old_discounted = old_ra_price

    charge_amount = max(Decimal("0.00"), new_discounted - old_discounted)

    # Revoke the old permit immediately so it stops counting as "active"
    old_permit = (
        await db.execute(
            select(Permit).where(
                Permit.email == app.student_email,
                Permit.permit_type == old_pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            ).order_by(Permit.created_at.desc())
        )
    ).scalars().first()
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
    if old_permit:
        old_permit.status = "upgraded"

    # Transition the application for the upgrade pipeline
    app.is_upgrade = True
    app.existing_permit_type_id = old_pt.id
    app.upgrade_credit = float(old_discounted)
    app.assigned_permit_type_id = new_pt.id
    app.assigned_lot = ", ".join(new_pt.lot_assignments) if new_pt.lot_assignments else None
    app.status = "selected"
    app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=7)

    note = (
        f"Admin upgrade initiated by {admin.email or admin.sub} at "
        f"{datetime.now(timezone.utc).isoformat()} — "
        f"{old_pt.label} (${old_discounted}) → {new_pt.label} (${new_discounted}), "
        f"charge: ${charge_amount}"
    )
    app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note

    if charge_amount <= 0:
        from ..services.lottery_v2_runner import complete_upgrade
        await complete_upgrade(db, app, new_pt)
        await db.flush()
        return {
            "status": "upgraded",
            "charge_amount": "0.00",
            "old_type": old_pt.label,
            "new_type": new_pt.label,
        }

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    product_name = f"Upgrade to {new_pt.label}"
    product_desc = f"Plate: {app.plate} | Difference: {old_pt.label} → {new_pt.label}"

    session = stripe.checkout.Session.create(
        customer_email=app.student_email,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": product_name,
                        "description": product_desc,
                    },
                    "unit_amount": int(charge_amount * 100),
                },
                "quantity": 1,
            }
        ],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK UPGRADE",
            "metadata": {
                "type": "lottery_v2_permit",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "permit_type_code": new_pt.code,
                "permit_type_label": new_pt.label,
                "permit_price": str(new_pt.price),
                "permit_valid_days": str(new_pt.valid_days),
                "plate": app.plate,
                "student_name": app.student_name,
                "student_email": app.student_email,
                "class_year": str(app.class_year) if app.class_year else "",
                "application_id": str(app.id),
                "is_upgrade": "true",
                "institution": settings.school_name or "moravian",
            },
        },
        success_url=f"{base_url}/parking?upgraded={application_id}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/parking",
        metadata={
            "type": "lottery_v2_permit",
            "application_id": str(app.id),
            "permit_type_id": str(new_pt.id),
            "permit_type_code": new_pt.code,
            "student_name": app.student_name,
            "plate": app.plate,
            "email": app.student_email,
            "valid_days": str(new_pt.valid_days),
            "is_upgrade": "true",
        },
    )

    stripe_note = (
        f"Upgrade payment link created (Stripe {session.id}) — ${charge_amount}"
    )
    app.admin_notes = f"{app.admin_notes}\n{stripe_note}".strip() if app.admin_notes else stripe_note
    await db.flush()

    # Send the student an email with the payment link
    if data.send_notification and app.student_email:
        from ..services.email import send_email, branded_email_shell
        from ..services.lottery_v2_runner import extract_first_name

        first_name = extract_first_name(app.student_name)
        school = settings.school_name or "Campus"
        inner = (
            f'<h2 style="color:{settings.brand_primary_color};margin:0 0 8px;font-size:20px;">'
            f"Parking Permit Upgrade Available</h2>"
            f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name}, '
            f"you have been offered an upgrade from <strong>{old_pt.label}</strong> to "
            f"<strong>{new_pt.label}</strong>.</p>"
            '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;'
            'border-radius:8px;margin:20px 0;">'
            '<tr><td colspan="2" style="padding:12px 16px 4px;font-size:11px;color:#999;'
            'text-transform:uppercase;letter-spacing:1px;">Upgrade Details</td></tr>'
            '<tr style="border-bottom:1px solid #eee;">'
            '<td style="padding:10px 16px;color:#666;font-size:14px;">New Permit</td>'
            f'<td style="padding:10px 16px;font-weight:600;font-size:16px;'
            f'color:{settings.brand_primary_color};">{new_pt.label}</td></tr>'
            '<tr style="border-bottom:1px solid #eee;">'
            '<td style="padding:10px 16px;color:#666;font-size:14px;">Amount Due</td>'
            f'<td style="padding:10px 16px;font-weight:600;font-size:16px;">'
            f'${charge_amount:.2f}</td></tr>'
            "</table>"
            f'<p style="color:#333;font-size:14px;line-height:1.6;">Click below to pay the '
            f"difference and complete your upgrade. This offer expires on "
            f"{app.offer_expires_at.strftime('%B %d, %Y') if app.offer_expires_at else 'soon'}.</p>"
            '<div style="text-align:center;margin:24px 0;">'
            f'<a href="{session.url}" style="background:{settings.brand_primary_color};'
            'color:#fff;padding:14px 32px;border-radius:8px;text-decoration:none;'
            f'font-weight:600;font-size:16px;">Pay ${charge_amount:.2f} &amp; Upgrade</a>'
            "</div>"
        )
        body_html = await branded_email_shell(school, inner)
        body_text = (
            f"PARKING PERMIT UPGRADE\n\n"
            f"Dear {first_name},\n\n"
            f"You have been offered an upgrade from {old_pt.label} to {new_pt.label}.\n"
            f"Amount due: ${charge_amount:.2f}\n\n"
            f"Pay here: {session.url}\n\n"
            f"This offer expires on {app.offer_expires_at.strftime('%B %d, %Y') if app.offer_expires_at else 'soon'}."
        )
        await send_email(
            to=[app.student_email],
            subject=f"Parking Permit Upgrade — {new_pt.label}",
            body_html=body_html,
            body_text=body_text,
        )

    return {
        "status": "upgrade_pending",
        "checkout_url": session.url,
        "charge_amount": str(charge_amount),
        "old_type": old_pt.label,
        "new_type": new_pt.label,
    }


# ── Admin endpoints ──────────────────────────────────────────────────


@router.get("/cycles", response_model=list[CycleRead])
async def list_cycles(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    cycles = (
        await db.execute(select(LotteryV2Cycle).order_by(LotteryV2Cycle.created_at.desc()))
    ).scalars().all()
    return [await _cycle_to_read(db, c) for c in cycles]


@router.post("/cycles", response_model=CycleRead, status_code=201)
async def create_cycle(
    data: CycleCreate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    cycle = LotteryV2Cycle(
        name=data.name,
        status="draft",
        offer_window_days=data.offer_window_days,
    )
    db.add(cycle)
    await db.flush()
    return await _cycle_to_read(db, cycle)


class OpenCycleRequest(BaseModel):
    auto_draw_threshold: float | None = None  # e.g. 1.10 = draw at 110% capacity
    auto_draw_days: int | None = None  # e.g. 5 = draw 5 days after open if not triggered sooner


@router.post("/cycles/{cycle_id}/open", response_model=CycleRead)
async def open_cycle(
    cycle_id: uuid.UUID,
    data: OpenCycleRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    opts = data or OpenCycleRequest()
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status == "drawn":
        raise HTTPException(400, "Cannot open a drawn cycle — reset first")

    # Close any other open cycles
    others = (
        await db.execute(
            select(LotteryV2Cycle).where(
                LotteryV2Cycle.status == "open",
                LotteryV2Cycle.id != cycle_id,
            )
        )
    ).scalars().all()
    for o in others:
        o.status = "closed"

    now = datetime.now(timezone.utc)
    cycle.status = "open"
    cycle.opens_at = now
    cycle.closes_at = None
    cycle.drawn_at = None
    cycle.drawn_by = None
    cycle.auto_draw_threshold = opts.auto_draw_threshold
    cycle.auto_draw_at = (
        now + timedelta(days=opts.auto_draw_days) if opts.auto_draw_days else None
    )
    await db.flush()
    return await _cycle_to_read(db, cycle)


@router.post("/cycles/{cycle_id}/close", response_model=CycleRead)
async def close_cycle(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status != "open":
        raise HTTPException(400, f"Cycle is '{cycle.status}', not open")
    cycle.status = "closed"
    cycle.closes_at = datetime.now(timezone.utc)
    await db.flush()
    return await _cycle_to_read(db, cycle)


@router.post("/cycles/{cycle_id}/reset", response_model=CycleRead)
async def reset_cycle(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Reset draw results — apps return to pending; cycle becomes closed."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    apps = (
        await db.execute(
            select(LotteryV2Application).where(LotteryV2Application.cycle_id == cycle_id)
        )
    ).scalars().all()
    for app in apps:
        if app.status in ("selected", "waitlisted", "ineligible", "expired", "declined"):
            # Don't reset accepted (permit already issued)
            if app.status == "accepted":
                continue
            app.status = "pending"
            app.lottery_rank = None
            app.waitlist_position = None
            app.assigned_permit_type_id = None
            app.assigned_lot = None
            app.offer_expires_at = None
            app.admin_notes = None

    cycle.status = "closed"
    cycle.drawn_at = None
    cycle.drawn_by = None
    await db.flush()
    return await _cycle_to_read(db, cycle)


@router.post("/cycles/{cycle_id}/run")
async def run_draw(
    cycle_id: uuid.UUID,
    data: RunDrawRequest | None = None,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    opts = data or RunDrawRequest()
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status == "open":
        # Auto-close for convenience in staging
        cycle.status = "closed"
        cycle.closes_at = datetime.now(timezone.utc)
        await db.flush()

    try:
        result = await run_waterfall_draw(
            db,
            cycle_id,
            run_by=admin.email,
            include_test_entries=opts.include_test_entries,
            send_notifications=opts.send_notifications,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return result


class RepairRequest(BaseModel):
    send_notifications: bool = True


@router.post("/cycles/{cycle_id}/repair")
async def repair_draw(
    cycle_id: uuid.UUID,
    data: RepairRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Demote duplicate offers and place waitlisted applicants into open seats."""
    opts = data or RepairRequest()
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status != "drawn":
        raise HTTPException(400, "Repair is only for drawn cycles")
    try:
        return await repair_cycle_placements(
            db, cycle_id, send_notifications=opts.send_notifications
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/cycles/{cycle_id}/advance-waitlist")
async def advance_cycle_waitlist(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Manually advance the waitlist: expire overdue offers and promote next applicant(s).
    
    Ignores auto_advance_waitlist toggle — this is an explicit admin action.
    """
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status != "drawn":
        raise HTTPException(400, "Can only advance waitlist on drawn cycles")

    now = datetime.now(timezone.utc)

    # Expire overdue offers
    expired_result = await db.execute(
        select(LotteryV2Application).where(
            LotteryV2Application.cycle_id == cycle_id,
            LotteryV2Application.status == "selected",
            LotteryV2Application.offer_expires_at.isnot(None),
            LotteryV2Application.offer_expires_at < now,
        )
    )
    expired = expired_result.scalars().all()
    for app in expired:
        app.status = "expired"
        app.assigned_permit_type_id = None
        app.assigned_lot = None
    await db.flush()

    # Promote from waitlist (force=True bypasses auto_advance_waitlist)
    promoted_count = 0
    for _ in range(len(expired) or 1):
        promoted = await promote_from_waitlist(db, cycle_id, force=True)
        if promoted:
            promoted_count += 1
        else:
            break

    await db.commit()
    return {
        "expired": len(expired),
        "advanced": promoted_count,
    }


@router.post("/cycles/{cycle_id}/notify-waitlist")
async def notify_waitlist(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Email current waitlisted applicants their waitlist position (resend-safe)."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    try:
        return await notify_waitlisted_applicants(db, cycle_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/cycles/{cycle_id}/seed")
async def seed_test_data(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Insert ~18 test applicants across campuses/years with varied rankings."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")
    if cycle.status == "drawn":
        raise HTTPException(400, "Reset the cycle before seeding")

    pts = (
        await db.execute(
            select(PermitType).where(PermitType.code.in_(ALL_V2_TIER_CODES))
        )
    ).scalars().all()
    by_code = {pt.code: pt for pt in pts}
    for code in ALL_V2_TIER_CODES:
        if code not in by_code:
            raise HTTPException(
                400,
                f"Missing permit type '{code}' — seed permit types first",
            )

    north_ids = [by_code[c].id for c in CAMPUS_TIER_CODES["north"]]
    south_ids = [by_code[c].id for c in CAMPUS_TIER_CODES["south"]]

    # Delete existing test entries for this cycle so seed is idempotent
    existing_tests = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle_id,
                LotteryV2Application.is_test_entry.is_(True),
            )
        )
    ).scalars().all()
    for a in existing_tests:
        await db.delete(a)
    await db.flush()

    now = datetime.now(timezone.utc)
    seed_specs = [
        # name, year, campus, plate, prefs (index into north/south lists), offset minutes
        ("Alex Senior", 2026, "north", "TST001", [0, 1, 2], 1),
        ("Blake Senior", 2026, "north", "TST002", [1, 0, 2], 2),
        ("Casey Senior", 2026, "south", "TST003", [0, 1], 3),
        ("Dana Senior", 2026, "south", "TST004", [1, 0], 4),
        ("Ellis Junior", 2027, "north", "TST005", [0, 1, 2], 5),
        ("Finley Junior", 2027, "north", "TST006", [2, 1, 0], 6),
        ("Gray Junior", 2027, "south", "TST007", [0, 1], 7),
        ("Harper Junior", 2027, "south", "TST008", [1, 0], 8),
        ("Indigo Soph", 2028, "north", "TST009", [1, 2, 0], 9),
        ("Jordan Soph", 2028, "north", "TST010", [2, 1], 10),
        ("Kai Soph", 2028, "south", "TST011", [0, 1], 11),
        ("Logan Soph", 2028, "south", "TST012", [1], 12),
        ("Morgan Fresh", 2029, "north", "TST013", [2, 1], 13),
        ("Noah Fresh", 2029, "north", "TST014", [1, 2], 14),
        ("Quinn Fresh", 2029, "south", "TST015", [1, 0], 15),
        ("Riley Fresh", 2029, "south", "TST016", [0, 1], 16),
        ("Sam Oversub", 2026, "north", "TST017", [0, 0], 17),  # will dedupe prefs
        ("Taylor Late", 2028, "north", "TST018", [0, 1, 2], 30),
    ]

    created = 0
    for name, year, campus, plate, pref_idx, minutes in seed_specs:
        pool = north_ids if campus == "north" else south_ids
        # Unique ordered prefs
        prefs: list[uuid.UUID] = []
        for i in pref_idx:
            if i < len(pool) and pool[i] not in prefs:
                prefs.append(pool[i])
        if not prefs:
            continue

        # Filter by eligibility
        eligible = await _eligible_tiers_for(db, campus, year)
        eligible_ids = {t.id for t in eligible}
        prefs = [p for p in prefs if p in eligible_ids]
        if not prefs:
            # Freshmen may only get steel field if min_class_year blocks others —
            # fall back to whatever is eligible
            prefs = [t.id for t in eligible]
        if not prefs:
            continue

        app = LotteryV2Application(
            cycle_id=cycle_id,
            student_sub=f"test-v2-{plate.lower()}",
            student_email=f"{plate.lower()}@test.moravian.edu",
            student_name=name,
            class_year=year,
            campus=campus,
            plate=plate,
            plate_state="PA",
            tier_preferences=prefs,
            status="pending",
            is_test_entry=True,
            created_at=now - timedelta(minutes=(60 - minutes)),
        )
        db.add(app)
        created += 1

    await db.flush()
    return {"seeded": created, "cycle_id": str(cycle_id)}


@router.post("/cycles/{cycle_id}/purge-test")
async def purge_test_data(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Remove all test entries from a cycle."""
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    result = await db.execute(
        select(func.count()).select_from(LotteryV2Application).where(
            LotteryV2Application.cycle_id == cycle_id,
            LotteryV2Application.is_test_entry.is_(True),
        )
    )
    count = result.scalar() or 0

    await db.execute(
        delete(LotteryV2Application).where(
            LotteryV2Application.cycle_id == cycle_id,
            LotteryV2Application.is_test_entry.is_(True),
        )
    )
    await db.flush()
    return {"purged": count, "cycle_id": str(cycle_id)}


@router.get("/cycles/{cycle_id}/applications", response_model=list[ApplicationRead])
async def list_applications(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    apps = (
        await db.execute(
            select(LotteryV2Application)
            .where(LotteryV2Application.cycle_id == cycle_id)
            .order_by(
                LotteryV2Application.lottery_rank.asc().nullslast(),
                LotteryV2Application.created_at.asc(),
            )
        )
    ).scalars().all()
    pt_by_id = await _permit_type_map(db)
    return [await _app_to_read(db, a, pt_by_id) for a in apps]


@router.get("/cycles/{cycle_id}/capacity-audit")
async def capacity_audit(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Live capacity vs demand diagnostic for a lottery cycle.

    Answers: why did Q/U (or any tier) only get N placements?
    """
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    pts = (
        await db.execute(
            select(PermitType).where(PermitType.code.in_(LOTTERY_TIER_CODES))
        )
    ).scalars().all()
    pt_by_id = {pt.id: pt for pt in pts}
    pt_by_code = {pt.code: pt for pt in pts}
    tiers = await build_tier_capacities(db, list(pts))

    apps = (
        await db.execute(
            select(LotteryV2Application).where(LotteryV2Application.cycle_id == cycle_id)
        )
    ).scalars().all()

    # Active permit counts by type code (same filter the draw uses)
    active_by_code: dict[str, int] = {}
    for pt in pts:
        active_by_code[pt.code] = (
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

    # Also count active permits assigned to lots Q / U regardless of type
    lot_active = {}
    for lot in ("Q", "U"):
        lot_active[lot] = (
            await db.execute(
                select(func.count())
                .select_from(Permit)
                .where(
                    permit_lot_matches(lot),
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                )
            )
        ).scalar() or 0

    def prefs(app: LotteryV2Application) -> list:
        return list(app.tier_preferences or [])

    south_apps = [a for a in apps if a.campus == "south"]
    north_apps = [a for a in apps if a.campus == "north"]

    south_guaranteed = pt_by_code.get("south_guaranteed_resident")
    steel_field = pt_by_code.get("steel_field_resident")

    def has_pref(app: LotteryV2Application, pt: PermitType | None) -> bool:
        return bool(pt and pt.id in prefs(app))

    def first_choice(app: LotteryV2Application, pt: PermitType | None) -> bool:
        p = prefs(app)
        return bool(pt and p and p[0] == pt.id)

    def _class_year_label(cy: int | None) -> str:
        if cy is None:
            return "Unknown"
        now_year = datetime.now(timezone.utc).year
        academic_start = now_year if datetime.now(timezone.utc).month >= 7 else now_year - 1
        diff = cy - academic_start
        if diff <= 1:
            return "Senior"
        elif diff == 2:
            return "Junior"
        elif diff == 3:
            return "Sophomore"
        elif diff >= 4:
            return "Freshman"
        return "Other"

    def _class_year_breakdown(app_list: list) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in app_list:
            label = _class_year_label(a.class_year)
            counts[label] = counts.get(label, 0) + 1
        return counts

    # SIS enrichment: resolve class years and classifications from Jenzabar
    from ..services.sis_student_data import lookup_batch_by_emails
    import sentry_sdk

    all_tier_permits: dict[str, list[Permit]] = {}
    all_emails: list[str] = []
    for pt in pts:
        tier_permits = (
            await db.execute(
                select(Permit).where(
                    Permit.permit_type == pt.code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        all_tier_permits[pt.code] = list(tier_permits)
        for p in tier_permits:
            if p.email:
                all_emails.append(p.email)

    try:
        sis_by_email = await lookup_batch_by_emails(all_emails)
    except Exception as e:
        logger.error("SIS batch enrichment failed, continuing without SIS data: %s", e)
        sentry_sdk.capture_exception(e)
        sis_by_email = {}

    def _sis_class_year_breakdown(permit_list: list[Permit]) -> dict[str, int]:
        """Build class year breakdown from SIS ClassCode for active permits."""
        counts: dict[str, int] = {}
        for p in permit_list:
            em = (p.email or "").strip().lower()
            data = sis_by_email.get(em)
            label = data.class_label if data and data.class_label else "Unknown"
            counts[label] = counts.get(label, 0) + 1
        return counts

    def _sis_breakdown(permit_list: list[Permit]) -> dict:
        housing: dict[str, int] = {}
        res_life = 0
        employee = 0
        absn = 0
        for p in permit_list:
            em = (p.email or "").strip().lower()
            data = sis_by_email.get(em)
            if not data:
                continue
            if data.housing_label:
                housing[data.housing_label] = housing.get(data.housing_label, 0) + 1
            if data.res_life_staff:
                res_life += 1
            if data.employee:
                employee += 1
            if data.accel_nursing:
                absn += 1
        return {
            "housing_breakdown": housing,
            "res_life_staff_count": res_life,
            "employee_count": employee,
            "accel_nursing_count": absn,
        }

    tier_rows = []
    for code in LOTTERY_TIER_CODES:
        pt = pt_by_code.get(code)
        if not pt:
            tier_rows.append({"code": code, "missing": True})
            continue
        tier = tiers.get(pt.id)
        selected_to_tier = [
            a for a in apps
            if a.assigned_permit_type_id == pt.id
            and a.status in ("selected", "accepted")
        ]
        selected_only = [a for a in selected_to_tier if a.status == "selected"]
        accepted_only = [a for a in selected_to_tier if a.status == "accepted"]
        waitlisted_with_pref = [
            a for a in apps if a.status == "waitlisted" and has_pref(a, pt)
        ]
        pending_with_pref = [
            a for a in apps if a.status == "pending" and has_pref(a, pt)
        ]
        first_choice_apps = [a for a in apps if first_choice(a, pt)]
        any_pref_apps = [a for a in apps if has_pref(a, pt)]
        active = active_by_code.get(pt.code, 0)
        selected_count = len(selected_only)
        accepted_count = len(accepted_only)
        max_cap = pt.max_capacity or 0
        over_by = max(0, active - max_cap)
        truly_open = max(0, max_cap - active)
        projected = active + selected_count
        projected_over = max(0, projected - max_cap)

        committed = active + selected_count
        tier_permit_list = all_tier_permits.get(pt.code, [])
        tier_rows.append({
            "code": pt.code,
            "label": pt.label,
            "lot_assignments": list(pt.lot_assignments or []),
            "max_capacity": max_cap,
            "active_permits": active,
            "selected_pending_payment": selected_count,
            "committed": committed,
            "over_capacity_by": over_by,
            "truly_open": truly_open,
            "projected": projected,
            "projected_over": projected_over,
            "auto_advance_waitlist": pt.auto_advance_waitlist,
            "waitlisted_with_pref": len(waitlisted_with_pref),
            "apps_first_choice": len(first_choice_apps),
            "class_year_breakdown": _sis_class_year_breakdown(tier_permit_list) if tier_permit_list else _class_year_breakdown(selected_to_tier),
            **_sis_breakdown(tier_permit_list),
        })

    # South / U deep dive
    sg_id = south_guaranteed.id if south_guaranteed else None
    south_unique_emails = {(a.student_email or "").lower() for a in south_apps}
    south_with_u = [a for a in south_apps if has_pref(a, south_guaranteed)]
    south_selected_u = [
        a for a in south_apps
        if a.assigned_permit_type_id == sg_id and a.status in ("selected", "accepted")
    ]
    south_selected_other = [
        a for a in south_apps
        if a.status in ("selected", "accepted") and a.assigned_permit_type_id != sg_id
    ]
    south_waitlisted = [a for a in south_apps if a.status == "waitlisted"]
    south_waitlisted_with_u = [a for a in south_waitlisted if has_pref(a, south_guaranteed)]

    # North / Q deep dive
    sf_id = steel_field.id if steel_field else None
    north_with_q = [a for a in north_apps if has_pref(a, steel_field)]
    north_selected_q = [
        a for a in north_apps
        if a.assigned_permit_type_id == sf_id and a.status in ("selected", "accepted")
    ]
    north_waitlisted_with_q = [
        a for a in north_apps if a.status == "waitlisted" and has_pref(a, steel_field)
    ]
    # People who ranked Q first (would take Q even if guaranteed open)
    q_first = [a for a in apps if first_choice(a, steel_field)]

    # Duplicate application detection
    email_counts: dict[str, int] = {}
    for a in apps:
        e = (a.student_email or "").lower()
        email_counts[e] = email_counts.get(e, 0) + 1
    duplicate_emails = {e: n for e, n in email_counts.items() if n > 1 and e}

    # Detect students with multiple active permits across tiers (stale permits
    # from upgrades where the old permit wasn't revoked).
    lottery_codes = [pt.code for pt in pts]
    multi_permit_rows = (
        await db.execute(
            select(Permit.email, func.count().label("cnt"), func.array_agg(Permit.permit_type).label("types"))
            .where(
                Permit.permit_type.in_(lottery_codes),
                Permit.status == "active",
                Permit.deleted_at.is_(None),
                Permit.email.isnot(None),
            )
            .group_by(Permit.email)
            .having(func.count() > 1)
        )
    ).all()
    stale_permits = [
        {"email": row.email, "active_count": row.cnt, "types": row.types}
        for row in multi_permit_rows
    ]

    # Detect stale selections: apps still "selected" but student already has
    # an active permit for that tier (upgrade completed, selection not cleared)
    selected_apps = [a for a in apps if a.status == "selected" and a.assigned_permit_type_id]
    stale_selections = []
    for a in selected_apps:
        pt = pt_by_id.get(a.assigned_permit_type_id)
        if not pt:
            continue
        has_permit = (
            await db.execute(
                select(Permit.id).where(
                    func.lower(Permit.email) == (a.student_email or "").lower(),
                    Permit.permit_type == pt.code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if has_permit:
            stale_selections.append({
                "email": a.student_email,
                "name": a.student_name,
                "tier": pt.label,
            })

    stale_count = len(stale_permits) + len(stale_selections)

    generated_at = datetime.now(timezone.utc).isoformat()

    return {
        "generated_at": generated_at,
        "cycle": {
            "id": str(cycle.id),
            "name": cycle.name,
            "status": cycle.status,
            "drawn_at": cycle.drawn_at.isoformat() if cycle.drawn_at else None,
            "application_count": len(apps),
        },
        "lot_active_permits": lot_active,
        "tiers": tier_rows,
        "stale_permits": stale_permits,
        "stale_selections": stale_selections,
        "stale_count": stale_count,
        "south": {
            "total_apps": len(south_apps),
            "unique_emails": len(south_unique_emails),
            "with_u_in_prefs": len(south_with_u),
            "selected_to_u": len(south_selected_u),
            "selected_to_other": len(south_selected_other),
            "waitlisted": len(south_waitlisted),
            "waitlisted_with_u_in_prefs": len(south_waitlisted_with_u),
            "waitlisted_with_u_emails": sorted(
                {(a.student_email or "").lower() for a in south_waitlisted_with_u}
            )[:50],
            "status_breakdown": {
                s: len([a for a in south_apps if a.status == s])
                for s in sorted({a.status for a in south_apps})
            },
        },
        "north_q": {
            "with_q_in_prefs": len(north_with_q),
            "ranked_q_first": len(q_first),
            "selected_to_q": len(north_selected_q),
            "waitlisted_with_q_in_prefs": len(north_waitlisted_with_q),
            "ranked_q_first_emails": sorted(
                {(a.student_email or "").lower() for a in q_first}
            )[:50],
        },
        "duplicates": {
            "emails_with_multiple_apps": len(duplicate_emails),
            "extra_app_rows": sum(n - 1 for n in duplicate_emails.values()),
            "sample": dict(list(sorted(duplicate_emails.items(), key=lambda x: -x[1])[:20])),
        },
    }


@router.get("/tier-detail/{permit_type_code}")
async def tier_detail(
    permit_type_code: str,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Return all lottery applications and active permits for a specific tier."""
    pt = (
        await db.execute(
            select(PermitType).where(PermitType.code == permit_type_code)
        )
    ).scalar_one_or_none()
    if not pt:
        raise HTTPException(404, f"Permit type '{permit_type_code}' not found")

    # All applications assigned to this tier
    apps = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.assigned_permit_type_id == pt.id,
                LotteryV2Application.status.in_(["selected", "accepted"]),
            ).order_by(LotteryV2Application.status, LotteryV2Application.student_name)
        )
    ).scalars().all()

    # All active permits for this tier
    permits = (
        await db.execute(
            select(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            ).order_by(Permit.name)
        )
    ).scalars().all()

    # Build lookup: email → application created_at (submission timestamp)
    app_by_email: dict[str, LotteryV2Application] = {}
    for a in apps:
        key = (a.student_email or "").lower()
        if key and key not in app_by_email:
            app_by_email[key] = a

    permit_emails = {(p.email or "").lower() for p in permits}
    selected_apps = [a for a in apps if a.status == "selected"]
    accepted_apps = [a for a in apps if a.status == "accepted"]

    # Pending offers: selected apps that DON'T yet have an active permit
    pending = [a for a in selected_apps if (a.student_email or "").lower() not in permit_emails]
    # Accepted apps whose email doesn't match any active permit (data issue)
    accepted_no_permit = [
        a for a in accepted_apps
        if (a.student_email or "").lower() not in permit_emails
    ]
    # Permits without a matching application (direct purchase or data issue)
    app_emails = {(a.student_email or "").lower() for a in apps}
    permits_no_app = [p for p in permits if (p.email or "").lower() not in app_emails]

    unique_people = len(permit_emails | {(a.student_email or "").lower() for a in selected_apps})
    committed = len(permits) + len(pending)

    # SIS enrichment: resolve Moravian IDs via Okta, then batch-query Jenzabar
    from ..services.sis_student_data import lookup_batch_by_emails

    all_emails = [p.email for p in permits if p.email]
    sis_by_email = await lookup_batch_by_emails(all_emails)

    _empty_sis = {"housing_status": None, "housing_label": None, "division_code": None,
                  "class_code": None, "class_label": None,
                  "accel_nursing": None, "res_life_staff": None, "employee": None}

    def _sis_fields(email: str | None) -> dict:
        em = (email or "").strip().lower()
        data = sis_by_email.get(em) if em else None
        if not data:
            return _empty_sis
        return {"housing_status": data.housing_status, "housing_label": data.housing_label,
                "division_code": data.division_code, "class_code": data.class_code,
                "class_label": data.class_label, "accel_nursing": data.accel_nursing,
                "res_life_staff": data.res_life_staff, "employee": data.employee}

    # SIS summary counts
    sis_housing: dict[str, int] = {}
    sis_res_life = 0
    sis_employee = 0
    sis_absn = 0
    for p in permits:
        sf = _sis_fields(p.email)
        if sf["housing_label"]:
            sis_housing[sf["housing_label"]] = sis_housing.get(sf["housing_label"], 0) + 1
        if sf["res_life_staff"]:
            sis_res_life += 1
        if sf["employee"]:
            sis_employee += 1
        if sf["accel_nursing"]:
            sis_absn += 1

    return {
        "permit_type": {
            "code": pt.code,
            "label": pt.label,
            "price": str(pt.price),
            "max_capacity": pt.max_capacity,
        },
        "summary": {
            "active_permit_count": len(permits),
            "pending_count": len(pending),
            "committed": committed,
            "unique_people": unique_people,
            "over_by": max(0, committed - (pt.max_capacity or 0)),
            "housing_breakdown": sis_housing,
            "res_life_staff_count": sis_res_life,
            "employee_count": sis_employee,
            "accel_nursing_count": sis_absn,
        },
        "active_permits": [
            {
                "name": p.name,
                "email": p.email,
                "student_id": p.student_id,
                "plate": ", ".join(p.plates) if p.plates else "",
                "permit_number": p.permit_number,
                "permit_issued_at": p.created_at.isoformat() if p.created_at else None,
                "applied_at": (
                    app_by_email[ek].created_at.isoformat()
                    if (ek := (p.email or "").lower()) in app_by_email
                    and app_by_email[ek].created_at
                    else None
                ),
                "class_year": (
                    app_by_email[ek].class_year
                    if (ek := (p.email or "").lower()) in app_by_email
                    else None
                ),
                **_sis_fields(p.email),
            }
            for p in permits
        ],
        "pending_offers": [
            {
                "name": a.student_name,
                "email": a.student_email,
                "is_upgrade": bool(a.is_upgrade),
                "plate": a.plate,
                "applied_at": a.created_at.isoformat() if a.created_at else None,
                "class_year": a.class_year,
            }
            for a in pending
        ],
        "issues": {
            "accepted_no_permit": [
                {"name": a.student_name, "email": a.student_email}
                for a in accepted_no_permit
            ],
            "permits_no_app": [
                {"name": p.name, "email": p.email, "permit_number": p.permit_number}
                for p in permits_no_app
            ],
        },
    }


@router.post("/cleanup-stale-permits")
async def cleanup_stale_permits(
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Clean up stale data from upgrades:
    1. Revoke old permits for students with multiple active lottery permits
    2. Clear stale 'selected' applications where the student already has
       an active permit for the assigned tier (upgrade completed via
       another path, or admin already fixed them)
    """
    lottery_codes = list(set(ALL_V2_TIER_CODES))

    # ── 1. Stale permits: students with multiple active lottery permits ──
    multi = (
        await db.execute(
            select(Permit.email)
            .where(
                Permit.permit_type.in_(lottery_codes),
                Permit.status == "active",
                Permit.deleted_at.is_(None),
                Permit.email.isnot(None),
            )
            .group_by(Permit.email)
            .having(func.count() > 1)
        )
    ).scalars().all()

    revoked_permits = []
    for email in multi:
        permits = (
            await db.execute(
                select(Permit)
                .where(
                    Permit.email == email,
                    Permit.permit_type.in_(lottery_codes),
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                )
                .order_by(Permit.created_at.desc())
            )
        ).scalars().all()

        for old in permits[1:]:
            old.status = "upgraded"
            revoked_permits.append({
                "email": email,
                "revoked_type": old.permit_type,
                "kept_type": permits[0].permit_type,
            })

    # ── 2. Stale selections: 'selected' apps where student already has permit ──
    stale_selected = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.status == "selected",
                LotteryV2Application.assigned_permit_type_id.isnot(None),
            )
        )
    ).scalars().all()

    pt_map = await _permit_type_map(db)
    cleared_selections = []
    for app in stale_selected:
        pt = pt_map.get(app.assigned_permit_type_id)
        if not pt:
            continue
        has_permit = (
            await db.execute(
                select(Permit.id).where(
                    func.lower(Permit.email) == (app.student_email or "").lower(),
                    Permit.permit_type == pt.code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if has_permit:
            app.status = "accepted"
            note = (
                f"Cleanup: marked accepted — active {pt.label} permit already exists. "
                f"By {admin.email or admin.sub} at {datetime.now(timezone.utc).isoformat()}"
            )
            app.admin_notes = f"{app.admin_notes}\n{note}".strip() if app.admin_notes else note
            cleared_selections.append({
                "email": app.student_email,
                "name": app.student_name,
                "tier": pt.label,
            })

    if revoked_permits or cleared_selections:
        await db.flush()

    return {
        "revoked_permits": len(revoked_permits),
        "cleared_selections": len(cleared_selections),
        "permit_detail": revoked_permits,
        "selection_detail": cleared_selections,
        "admin": admin.email or admin.sub,
    }


@router.get("/cycles/{cycle_id}/duplicates-report")
async def duplicates_report(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Read-only report: who holds duplicate offers or permits in this cycle, per tier."""
    from ..models.permit import Permit

    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    pts = (
        await db.execute(
            select(PermitType).where(
                PermitType.code.in_(LOTTERY_TIER_CODES),
                PermitType.is_active.is_(True),
            )
        )
    ).scalars().all()
    pt_by_id = {pt.id: pt for pt in pts}

    apps = (
        await db.execute(
            select(LotteryV2Application).where(LotteryV2Application.cycle_id == cycle_id)
        )
    ).scalars().all()

    # Group all selected/accepted apps by email
    winners = [a for a in apps if a.status in ("selected", "accepted")]
    by_email: dict[str, list] = {}
    for a in winners:
        key = (a.student_email or "").strip().lower()
        if key:
            by_email.setdefault(key, []).append(a)

    # Find emails with multiple offers
    duplicate_entries = []
    for email, group in sorted(by_email.items()):
        if len(group) < 2:
            continue
        rows = []
        for a in sorted(group, key=lambda x: x.created_at or datetime.min):
            pt = pt_by_id.get(a.assigned_permit_type_id) if a.assigned_permit_type_id else None
            rows.append({
                "id": str(a.id),
                "status": a.status,
                "tier": pt.label if pt else None,
                "tier_code": pt.code if pt else None,
                "lot": a.assigned_lot,
                "class_year": a.class_year,
                "name": a.student_name,
                "created_at": a.created_at.isoformat() if a.created_at else None,
                "offer_expires_at": a.offer_expires_at.isoformat() if a.offer_expires_at else None,
            })
        duplicate_entries.append({
            "email": email,
            "count": len(group),
            "applications": rows,
        })

    # Per-tier breakdown: how many selected offers exceed remaining capacity
    tier_report = []
    for pt in sorted(pts, key=lambda p: p.sort_order):
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

        tier_apps = [a for a in apps if a.assigned_permit_type_id == pt.id]
        selected = [a for a in tier_apps if a.status == "selected"]
        accepted = [a for a in tier_apps if a.status == "accepted"]

        # Emails with multiple offers assigned to THIS tier
        tier_by_email: dict[str, list] = {}
        for a in tier_apps:
            if a.status in ("selected", "accepted"):
                key = (a.student_email or "").strip().lower()
                if key:
                    tier_by_email.setdefault(key, []).append(a)
        tier_dupes = {e: g for e, g in tier_by_email.items() if len(g) > 1}

        # People who also have an active permit already (double-issued)
        selected_emails = [(a.student_email or "").strip().lower() for a in selected]
        already_have_permit = []
        for email in set(selected_emails):
            existing = (
                await db.execute(
                    select(Permit).where(
                        func.lower(Permit.email) == email,
                        Permit.permit_type == pt.code,
                        Permit.status == "active",
                        Permit.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if existing:
                already_have_permit.append(email)

        max_cap = pt.max_capacity or 0
        committed = active_count + len(selected)
        over_by = max(0, committed - max_cap)

        tier_report.append({
            "code": pt.code,
            "label": pt.label,
            "max_capacity": max_cap,
            "active_permits": active_count,
            "selected_offers": len(selected),
            "accepted_apps": len(accepted),
            "committed": committed,
            "over_capacity_by": over_by,
            "duplicate_emails_in_tier": len(tier_dupes),
            "duplicate_detail": [
                {"email": e, "count": len(g)} for e, g in sorted(tier_dupes.items())
            ],
            "selected_but_already_have_permit": already_have_permit,
        })

    return {
        "cycle_id": str(cycle_id),
        "cycle_name": cycle.name,
        "total_duplicate_students": len(duplicate_entries),
        "duplicates": duplicate_entries,
        "tiers": tier_report,
    }


@router.get("/cycles/{cycle_id}/results")
async def get_results(
    cycle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    cycle = await db.get(LotteryV2Cycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "Cycle not found")

    audit = (
        await db.execute(
            select(LotteryV2AuditLog)
            .where(LotteryV2AuditLog.cycle_id == cycle_id)
            .order_by(LotteryV2AuditLog.run_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    pt_by_id = await _permit_type_map(db)
    apps_raw = list(
        (
            await db.execute(
                select(LotteryV2Application)
                .where(LotteryV2Application.cycle_id == cycle_id)
                .order_by(
                    LotteryV2Application.lottery_rank.asc().nullslast(),
                    LotteryV2Application.waitlist_position.asc().nullslast(),
                )
            )
        ).scalars().all()
    )
    apps = [await _app_to_read(db, a, pt_by_id) for a in apps_raw]

    # Live unique winners — one row per email for placements view
    winner_reads = [
        a for a in apps if a.status in ("selected", "accepted") and a.assigned_permit_type_label
    ]
    seen_winner_emails: set[str] = set()
    unique_winners: list = []
    for a in winner_reads:
        key = (a.student_email or "").strip().lower() or a.id
        if key in seen_winner_emails:
            continue
        seen_winner_emails.add(key)
        unique_winners.append(a)

    by_tier: dict[str, list] = {}
    for a in unique_winners:
        by_tier.setdefault(a.assigned_permit_type_label or "(none)", []).append(a)

    # True waitlist — exclude superseded and anyone who already won
    waitlisted = [
        a
        for a in apps
        if a.status == "waitlisted"
        and (a.student_email or "").strip().lower() not in seen_winner_emails
    ]

    # Capacity context per tier label
    tier_capacity: dict[str, dict] = {}
    for pt in pt_by_id.values():
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
        filled = len(by_tier.get(pt.label, []))
        selected_only = sum(
            1 for a in by_tier.get(pt.label, []) if a.status == "selected"
        )
        max_cap = pt.max_capacity or 0
        remaining = max(0, max_cap - active_count)
        tier_capacity[pt.label] = {
            "max_capacity": max_cap,
            "active_permits": active_count,
            "remaining_vs_active": remaining,
            "unique_placed": filled,
            "over_capacity": selected_only > remaining or (max_cap > 0 and filled > max_cap),
        }

    live_selected = len(unique_winners)
    live_waitlisted = len(waitlisted)

    return {
        "cycle": await _cycle_to_read(db, cycle),
        "audit": {
            "strategy": audit.strategy if audit else None,
            "total_applicants": audit.total_applicants if audit else 0,
            "eligible_applicants": audit.eligible_applicants if audit else 0,
            "selected_count": audit.selected_count if audit else 0,
            "waitlisted_count": audit.waitlisted_count if audit else 0,
            "run_at": audit.run_at.isoformat() if audit and audit.run_at else None,
            "run_by": audit.run_by if audit else None,
            "warnings": audit.warnings if audit else None,
        }
        if audit
        else None,
        "live": {
            "selected_count": live_selected,
            "waitlisted_count": live_waitlisted,
            "accepted_count": sum(1 for a in unique_winners if a.status == "accepted"),
            "tier_capacity": tier_capacity,
        },
        "by_tier": {k: [x.model_dump(mode="json") for x in v] for k, v in by_tier.items()},
        "waitlisted": [x.model_dump(mode="json") for x in waitlisted],
        "applications": [a.model_dump(mode="json") for a in apps],
    }


@router.get("/sis-lookup/{id_num}")
async def sis_student_lookup(
    id_num: str,
    _admin: OktaUser = Depends(require_admin()),
):
    """Look up a student's housing status and division from SIS (Jenzabar)."""
    from ..services.sis_student_data import lookup_student_parking_data

    data = await lookup_student_parking_data(id_num)
    if not data:
        raise HTTPException(404, "Student not found in SIS or SIS not configured")
    return {
        "id_num": data.id_num,
        "division_code": data.division_code,
        "housing_status": data.housing_status,
        "housing_label": data.housing_label,
        "class_code": data.class_code,
        "class_label": data.class_label,
        "accel_nursing": data.accel_nursing,
        "res_life_staff": data.res_life_staff,
        "employee": data.employee,
    }
