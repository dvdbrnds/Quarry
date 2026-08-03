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
    class_year_eligible,
    promote_from_waitlist,
    run_waterfall_draw,
)
from ..services.permit_numbering import next_permit_number

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
    assigned_permit_type_id: uuid.UUID | None
    assigned_permit_type_label: str | None = None
    assigned_permit_type_price: Decimal | None = None
    assigned_permit_type_code: str | None = None
    assigned_lot: str | None
    status: str
    lottery_rank: int | None
    waitlist_position: int | None
    offer_expires_at: datetime | None
    is_test_entry: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RunDrawRequest(BaseModel):
    include_test_entries: bool = True
    send_notifications: bool = False  # default off for staging demos


# ── Helpers ──────────────────────────────────────────────────────────


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


async def _app_to_read(db: AsyncSession, app: LotteryV2Application) -> ApplicationRead:
    label = None
    price = None
    code = None
    if app.assigned_permit_type_id:
        pt = await db.get(PermitType, app.assigned_permit_type_id)
        if pt:
            label = pt.label
            price = pt.price
            code = pt.code
    return ApplicationRead(
        id=app.id,
        cycle_id=app.cycle_id,
        student_name=app.student_name,
        student_email=app.student_email,
        class_year=app.class_year,
        campus=app.campus,
        plate=app.plate,
        plate_state=app.plate_state or "",
        tier_preferences=list(app.tier_preferences or []),
        assigned_permit_type_id=app.assigned_permit_type_id,
        assigned_permit_type_label=label,
        assigned_permit_type_price=price,
        assigned_permit_type_code=code,
        assigned_lot=app.assigned_lot,
        status=app.status,
        lottery_rank=app.lottery_rank,
        waitlist_position=app.waitlist_position,
        offer_expires_at=app.offer_expires_at,
        is_test_entry=app.is_test_entry,
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
) -> list[TierRead]:
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
        out.append(
            TierRead(
                id=pt.id,
                code=pt.code,
                label=pt.label,
                price=pt.price,
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
    _user: OktaUser = Depends(get_current_user_or_impersonated),
):
    return await _eligible_tiers_for(db, campus, class_year)


@router.post("/applications", response_model=ApplicationRead, status_code=201)
async def submit_application(
    data: ApplicationSubmit,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    cycle = (
        await db.execute(
            select(LotteryV2Cycle)
            .where(LotteryV2Cycle.status == "open")
            .order_by(LotteryV2Cycle.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not cycle:
        raise HTTPException(400, "No open lottery cycle — applications are closed")

    now = datetime.now(timezone.utc)
    if cycle.opens_at and cycle.opens_at > now:
        raise HTTPException(400, "Application window has not opened yet")
    if cycle.closes_at and cycle.closes_at < now:
        raise HTTPException(400, "Application window has closed")

    existing = (
        await db.execute(
            select(LotteryV2Application).where(
                LotteryV2Application.cycle_id == cycle.id,
                LotteryV2Application.student_sub == user.sub,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(400, "You already have an application for this lottery")

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
    )
    db.add(app)
    await db.flush()

    # Opt into parking + emergency SMS now; Phase 23 expands to all AlertUs channels
    if data.sms_opt_in and phone:
        from .student_permits import _opt_in_alerts

        await _opt_in_alerts(db, name, user.email, phone)

    # Check if auto-draw threshold is reached
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
    ).scalar_one_or_none()
    if not app:
        return None
    return await _app_to_read(db, app)


@router.post("/applications/{application_id}/accept")
async def accept_offer(
    application_id: uuid.UUID,
    body: dict | None = Body(None),
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Accept a v2 lottery offer — Stripe checkout or fee-exempt issuance."""
    app = await db.get(LotteryV2Application, application_id)
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

    pt = await db.get(PermitType, app.assigned_permit_type_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    if app.fee_exempt:
        lot_assignment = app.assigned_lot or (
            ",".join(pt.lot_assignments) if pt.lot_assignments else ""
        )
        new_permit = Permit(
            permit_number=await next_permit_number(db),
            name=app.student_name,
            email=app.student_email or None,
            phone=app.phone or "",
            sms_opt_in=bool(app.sms_opt_in),
            plates=[app.plate],
            permit_type=pt.code,
            lot_assignment=lot_assignment,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=pt.valid_days),
            status="active",
        )
        db.add(new_permit)
        db.add(
            Payment(
                amount=Decimal("0.00"),
                method="fee_exempt",
                payment_type="lottery_v2_permit",
                payer_name=app.student_name or None,
                payer_email=app.student_email or None,
                plate=app.plate or None,
                description=f"Fee-Exempt Permit ({pt.code}) — {app.plate}",
            )
        )
        app.status = "accepted"
        await db.flush()
        return {"status": "accepted", "fee_exempt": True}

    # ── Coupon discount ──────────────────────────────────────────────────────
    from ..models.coupon import Coupon
    from ..routers.coupons import _validate_coupon

    discounted_price = pt.price
    applied_coupon: Coupon | None = None
    coupon_code = (body or {}).get("coupon_code", "")

    if coupon_code:
        coupon_result = await db.execute(
            select(Coupon).where(func.upper(Coupon.code) == coupon_code.upper().strip())
        )
        applied_coupon = coupon_result.scalar()
        if not applied_coupon:
            raise HTTPException(400, "Invalid coupon code.")
        error = _validate_coupon(applied_coupon, pt.code)
        if error:
            raise HTTPException(400, error)

        if applied_coupon.discount_type == "full":
            discounted_price = Decimal("0.00")
        elif applied_coupon.discount_type == "percent":
            discounted_price = pt.price * (Decimal("100") - applied_coupon.discount_value) / Decimal("100")
        elif applied_coupon.discount_type == "flat":
            discounted_price = max(Decimal("0.00"), pt.price - applied_coupon.discount_value)

    # Full coupon waiver: issue permit at $0 without Stripe
    if applied_coupon and discounted_price <= 0:
        lot_assignment = app.assigned_lot or (
            ",".join(pt.lot_assignments) if pt.lot_assignments else ""
        )
        new_permit = Permit(
            permit_number=await next_permit_number(db),
            name=app.student_name,
            email=app.student_email or None,
            phone=app.phone or "",
            sms_opt_in=bool(app.sms_opt_in),
            plates=[app.plate],
            permit_type=pt.code,
            lot_assignment=lot_assignment,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=pt.valid_days),
            status="active",
        )
        db.add(new_permit)
        db.add(Payment(
            amount=Decimal("0.00"),
            method="coupon",
            payment_type="lottery_v2_permit",
            payer_name=app.student_name or None,
            payer_email=app.student_email or None,
            plate=app.plate or None,
            description=f"Coupon {applied_coupon.code} ({applied_coupon.program_name}) — {pt.code} — {app.plate}",
        ))
        applied_coupon.current_uses += 1
        from .coupons import record_coupon_usage
        await record_coupon_usage(db, applied_coupon, app.student_name, app.student_email, user.sub, pt.code, pt.price, Decimal("0.00"))
        app.status = "accepted"
        await db.flush()
        return {"status": "accepted", "fee_exempt": False, "coupon": True}

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    session = stripe.checkout.Session.create(
        customer_email=app.student_email,
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"{pt.label} Parking Permit",
                        "description": f"Plate: {app.plate} | Valid for {pt.valid_days} days"
                        + (f" | Coupon: {applied_coupon.code}" if applied_coupon else ""),
                    },
                    "unit_amount": int(discounted_price * 100),
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
            "coupon_code": applied_coupon.code if applied_coupon else "",
        },
    )

    if applied_coupon:
        applied_coupon.current_uses += 1
        from .coupons import record_coupon_usage
        await record_coupon_usage(db, applied_coupon, app.student_name, app.student_email, user.sub, pt.code, pt.price, discounted_price)
        await db.flush()

    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/applications/{application_id}/decline")
async def decline_offer(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    app = await db.get(LotteryV2Application, application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.student_sub != user.sub:
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
    return [await _app_to_read(db, a) for a in apps]


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

    apps = [
        await _app_to_read(db, a)
        for a in (
            await db.execute(
                select(LotteryV2Application)
                .where(LotteryV2Application.cycle_id == cycle_id)
                .order_by(
                    LotteryV2Application.lottery_rank.asc().nullslast(),
                    LotteryV2Application.waitlist_position.asc().nullslast(),
                )
            )
        ).scalars().all()
    ]

    by_tier: dict[str, list] = {}
    waitlisted = []
    for a in apps:
        if a.status in ("selected", "accepted") and a.assigned_permit_type_label:
            by_tier.setdefault(a.assigned_permit_type_label, []).append(a)
        elif a.status == "waitlisted":
            waitlisted.append(a)

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
        "by_tier": {k: [x.model_dump(mode="json") for x in v] for k, v in by_tier.items()},
        "waitlisted": [x.model_dump(mode="json") for x in waitlisted],
        "applications": [a.model_dump(mode="json") for a in apps],
    }
