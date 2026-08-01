"""Student-facing permit application endpoints."""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user
from ..config import settings
from ..database import get_db
from ..models.alert_subscriber import AlertSubscriber
from ..models.lot import ParkingLot
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.permit_application import PermitApplication
from ..models.permit_type import PermitType
from ..services.permit_numbering import next_permit_number

_logger = logging.getLogger("quarry.student_permits")
from ..schemas.permit_application import (
    ApplicationSubmit,
    ApplicationWithType,
    AvailablePermitType,
    DirectPurchaseRequest,
    LotAccessInfo,
    VehicleSwapRequest,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

COMMUTER_CODES = {"commuter_undergrad", "commuter_grad", "premium_commuter"}

ALL_ALERT_CATEGORIES = ["emergency", "weather", "campus_closing", "parking", "general"]
# Permit-registration opt-in today; Phase 23 (AlertUs) expands to ALL_ALERT_CATEGORIES + all channels
PERMIT_OPT_IN_CATEGORIES = ["emergency", "parking"]


async def _opt_in_alerts(
    db: AsyncSession,
    name: str,
    email: str,
    phone: str,
) -> None:
    """Create or update an alert subscriber when a student opts in during
    permit registration. Subscribes to emergency + parking SMS for now;
    Phase 23 grows this to all AlertUs emergency channels."""
    try:
        existing = await db.execute(
            select(AlertSubscriber).where(AlertSubscriber.email == email)
        )
        subscriber = existing.scalar_one_or_none()
        if subscriber:
            if phone and not subscriber.phone:
                subscriber.phone = phone
            subscriber.sms_enabled = True
            # Merge so we don't wipe categories already granted elsewhere
            existing_cats = set(subscriber.categories or [])
            subscriber.categories = list(existing_cats | set(PERMIT_OPT_IN_CATEGORIES))
        else:
            subscriber = AlertSubscriber(
                name=name,
                email=email,
                phone=phone,
                sms_enabled=True,
                email_enabled=True,
                categories=list(PERMIT_OPT_IN_CATEGORIES),
                source="permit_registration",
            )
            db.add(subscriber)
        await db.flush()
    except Exception as e:
        _logger.warning("Alert opt-in failed (non-fatal): %s", e)


async def _load_lot_lookup(db: AsyncSession) -> dict[str, ParkingLot]:
    result = await db.execute(
        select(ParkingLot).where(ParkingLot.deleted_at.is_(None))
    )
    return {lot.name: lot for lot in result.scalars().all()}


def _build_lot_details(
    lot_names: list[str],
    permit_type_code: str,
    lot_lookup: dict[str, ParkingLot],
) -> list[LotAccessInfo]:
    details: list[LotAccessInfo] = []
    is_commuter = permit_type_code in COMMUTER_CODES
    for name in lot_names:
        lot = lot_lookup.get(name)
        designation = lot.designation_code if lot else ""
        restricted = is_commuter and designation in ("FS", "FSC")
        details.append(LotAccessInfo(
            name=name,
            designation_code=designation,
            is_time_restricted=restricted,
            restriction_label="After 4 PM & weekends" if restricted else "",
        ))
    return details


@router.get("/available", response_model=list[AvailablePermitType])
async def available_permit_types(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """List permit types currently open for application or direct purchase."""
    now = datetime.now(timezone.utc)
    from sqlalchemy import or_, and_
    result = await db.execute(
        select(PermitType).where(
            PermitType.is_active.is_(True),
            or_(
                # Lottery types with an open application window
                and_(
                    PermitType.requires_lottery.is_(True),
                    PermitType.application_opens_at.isnot(None),
                    PermitType.application_opens_at <= now,
                    or_(
                        PermitType.application_closes_at.is_(None),
                        PermitType.application_closes_at > now,
                    ),
                ),
                # Always-available types (direct purchase) — respects schedule if set
                and_(
                    PermitType.requires_lottery.is_(False),
                    PermitType.is_purchasable_online.is_(True),
                    or_(
                        PermitType.application_opens_at.is_(None),
                        PermitType.application_opens_at <= now,
                    ),
                    or_(
                        PermitType.application_closes_at.is_(None),
                        PermitType.application_closes_at > now,
                    ),
                ),
            ),
        ).order_by(PermitType.sort_order)
    )
    all_types = result.scalars().all()

    # Filter by eligible_groups: if a permit type has eligible_groups set,
    # the user must belong to at least one of those groups to see it.
    user_groups = set(user.groups)
    types = [
        pt for pt in all_types
        if not pt.eligible_groups or user_groups & set(pt.eligible_groups)
    ]

    lot_lookup = await _load_lot_lookup(db)

    out: list[AvailablePermitType] = []
    for pt in types:
        active_count = (await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )).scalar() or 0
        remaining = max(0, pt.max_capacity - active_count)

        current_applicants = None
        approximate_odds = None
        if pt.requires_lottery:
            app_count = (await db.execute(
                select(func.count()).select_from(PermitApplication).where(
                    PermitApplication.permit_type_id == pt.id,
                    PermitApplication.status == "pending",
                )
            )).scalar() or 0
            current_applicants = app_count
            approximate_odds = (
                f"{min(100, round(pt.max_capacity / app_count * 100))}%"
                if app_count > 0 else "100%"
            )

        out.append(AvailablePermitType(
            id=pt.id,
            code=pt.code,
            label=pt.label,
            eligible=pt.eligible,
            price=pt.price,
            max_capacity=pt.max_capacity,
            remaining=remaining,
            lot_assignments=pt.lot_assignments,
            lot_details=_build_lot_details(pt.lot_assignments, pt.code, lot_lookup),
            valid_days=pt.valid_days,
            min_class_year=pt.min_class_year,
            allow_multiple=pt.allow_multiple,
            application_closes_at=pt.application_closes_at,
            requires_lottery=pt.requires_lottery,
            current_applicants=current_applicants,
            approximate_odds=approximate_odds,
        ))
    return out


@router.post("/apply", response_model=ApplicationWithType, status_code=201)
async def submit_application(
    data: ApplicationSubmit,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Submit a permit application."""
    now = datetime.now(timezone.utc)

    pt = await db.get(PermitType, data.permit_type_id)
    if not pt or not pt.is_active:
        raise HTTPException(404, "Permit type not found")

    if not pt.application_opens_at:
        raise HTTPException(400, "This permit type is not accepting applications")
    if now < pt.application_opens_at:
        raise HTTPException(400, "Application window has not opened yet")
    if pt.application_closes_at and now > pt.application_closes_at:
        raise HTTPException(400, "Application window has closed")

    if pt.min_class_year and data.class_year > pt.min_class_year:
        raise HTTPException(
            403,
            f"This permit type requires class year {pt.min_class_year} or earlier. "
            f"First-year students are not eligible for resident parking.",
        )

    if not pt.allow_multiple:
        existing = await db.execute(
            select(PermitApplication).where(
                PermitApplication.student_sub == user.sub,
                PermitApplication.permit_type_id == pt.id,
                PermitApplication.status.notin_(["expired", "declined"]),
            )
        )
        if existing.scalar():
            raise HTTPException(409, "You already have an active application for this permit type")

    citation_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM tickets
            WHERE UPPER(plate) = UPPER(:plate)
              AND status NOT IN ('paid', 'voided', 'resolved_permit')
        """),
        {"plate": data.plate.upper().strip()},
    )
    unpaid_count = citation_result.scalar() or 0
    if unpaid_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"You have {unpaid_count} unpaid parking citation(s). "
            f"Pay all outstanding fines before applying for a permit. "
            f"Visit {settings.student_facing_url}/pay to pay online.",
        )

    okta_profile = {
        "sub": user.sub,
        "email": user.email,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "display_name": user.display_name,
        "class_year": user.class_year,
        "groups": user.groups,
    }

    app = PermitApplication(
        student_sub=user.sub,
        student_email=user.email,
        student_name=data.student_name,
        class_year=data.class_year,
        permit_type_id=pt.id,
        plate=data.plate.upper().strip(),
        plate_state=data.plate_state.upper().strip(),
        phone=data.phone,
        lot_preferences=data.lot_preferences,
        is_test_entry=user.is_staff,
        okta_metadata=okta_profile,
    )
    db.add(app)
    await db.flush()
    await db.refresh(app)

    if data.sms_opt_in and data.phone:
        await _opt_in_alerts(db, data.student_name, user.email, data.phone)

    lot_lookup = await _load_lot_lookup(db)
    return ApplicationWithType(
        **{k: v for k, v in app.__dict__.items() if not k.startswith("_")},
        permit_type_label=pt.label,
        permit_type_code=pt.code,
        permit_type_price=pt.price,
        lot_assignments=pt.lot_assignments,
        lot_details=_build_lot_details(pt.lot_assignments, pt.code, lot_lookup),
    )


@router.get("/my-applications", response_model=list[ApplicationWithType])
async def my_applications(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """List the current student's own applications."""
    result = await db.execute(
        select(PermitApplication)
        .where(PermitApplication.student_sub == user.sub)
        .order_by(PermitApplication.created_at.desc())
    )
    apps = result.scalars().all()

    lot_lookup = await _load_lot_lookup(db)

    from sqlalchemy import or_

    out: list[ApplicationWithType] = []
    for app in apps:
        pt = await db.get(PermitType, app.permit_type_id)
        pt_code = pt.code if pt else ""
        pt_lots = pt.lot_assignments if pt else []
        waitlist_msg = None
        if app.status == "waitlisted" and app.waitlist_position:
            waitlist_msg = (
                f"You are #{app.waitlist_position} on the waitlist. "
                "You will be notified by email if a spot becomes available."
            )

        swap_info: dict = {}
        if app.status == "accepted":
            permit_result = await db.execute(
                select(Permit).where(
                    Permit.permit_type == pt_code,
                    Permit.status == "active",
                    Permit.deleted_at.is_(None),
                    or_(Permit.student_id == user.sub, Permit.email == user.email),
                ).order_by(Permit.created_at.desc()).limit(1)
            )
            permit = permit_result.scalar()
            if permit:
                now = datetime.now(timezone.utc)
                lpc = permit.last_plate_change
                next_swap = (lpc + timedelta(days=7)) if lpc else None
                swap_info = {
                    "permit_id": str(permit.id),
                    "current_plate": permit.plates[0] if permit.plates else app.plate,
                    "last_plate_change": lpc,
                    "next_swap_available": next_swap,
                    "can_swap": next_swap is None or now >= next_swap,
                }

        out.append(ApplicationWithType(
            **{k: v for k, v in app.__dict__.items() if not k.startswith("_")},
            permit_type_label=pt.label if pt else "",
            permit_type_code=pt_code,
            permit_type_price=pt.price if pt else 0,
            lot_assignments=pt_lots,
            lot_details=_build_lot_details(pt_lots, pt_code, lot_lookup),
            waitlist_message=waitlist_msg,
            **swap_info,
        ))
    return out


@router.post("/{application_id}/accept")
async def accept_offer(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Accept a lottery offer — creates Stripe checkout for permit payment."""
    app = await db.get(PermitApplication, application_id)
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

    pt = await db.get(PermitType, app.permit_type_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    # Fee-exempt path: issue permit directly at $0, skip Stripe
    if app.fee_exempt:
        lot_assignment = ""
        if app.assigned_lot:
            lot_assignment = app.assigned_lot
        elif pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

        new_permit = Permit(
            permit_number=await next_permit_number(db),
            name=app.student_name,
            email=app.student_email or None,
            plates=[app.plate],
            permit_type=pt.code,
            lot_assignment=lot_assignment,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=pt.valid_days),
            status="active",
        )
        db.add(new_permit)

        payment = Payment(
            amount=Decimal("0.00"),
            method="fee_exempt",
            payment_type="lottery_permit",
            payer_name=app.student_name or None,
            payer_email=app.student_email or None,
            plate=app.plate or None,
            description=f"Fee-Exempt Permit ({pt.code}) — {app.plate}",
        )
        db.add(payment)

        app.status = "accepted"
        await db.flush()

        return {"status": "accepted", "fee_exempt": True}

    # Standard payment path via Stripe
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    session = stripe.checkout.Session.create(
        customer_email=app.student_email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{pt.label} Parking Permit",
                    "description": f"Plate: {app.plate} | Valid for {pt.valid_days} days",
                },
                "unit_amount": int(pt.price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "lottery_permit",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_activity_permits,
                    settings.gl_segment5, settings.gl_segment6,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_activity": settings.gl_activity_permits,
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
                "institution": settings.school_name or "moravian",
            },
        },
        success_url=f"{base_url}/student/permits?accepted={application_id}",
        cancel_url=f"{base_url}/student/permits",
        metadata={
            "type": "lottery_permit",
            "application_id": str(app.id),
            "permit_type_id": str(pt.id),
            "permit_type_code": pt.code,
            "student_name": app.student_name,
            "plate": app.plate,
            "email": app.student_email,
            "valid_days": str(pt.valid_days),
        },
    )

    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/purchase")
async def direct_purchase(
    data: DirectPurchaseRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Buy an always-available permit directly via Stripe (no lottery)."""
    pt = await db.get(PermitType, data.permit_type_id)
    if not pt or not pt.is_active:
        raise HTTPException(404, "Permit type not found")
    if not pt.is_purchasable_online or pt.requires_lottery:
        raise HTTPException(400, "This permit type cannot be purchased directly")

    active_count = (await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.permit_type == pt.code,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )).scalar() or 0
    remaining = max(0, pt.max_capacity - active_count)
    if remaining <= 0:
        raise HTTPException(400, "No permits remaining for this type")

    if pt.min_class_year and data.class_year > pt.min_class_year:
        raise HTTPException(
            403,
            f"This permit type requires class year {pt.min_class_year} or earlier.",
        )

    if not pt.allow_multiple:
        existing = await db.execute(
            select(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
                Permit.email == user.email,
            )
        )
        if existing.scalar():
            raise HTTPException(409, "You already have an active permit of this type")

    citation_result = await db.execute(
        text("""
            SELECT COUNT(*) FROM tickets
            WHERE UPPER(plate) = UPPER(:plate)
              AND status NOT IN ('paid', 'voided', 'resolved_permit')
        """),
        {"plate": data.plate.upper().strip()},
    )
    unpaid_count = citation_result.scalar() or 0
    if unpaid_count > 0:
        raise HTTPException(
            status_code=400,
            detail=f"You have {unpaid_count} unpaid parking citation(s). "
            f"Pay all outstanding fines before purchasing a permit. "
            f"Visit {settings.student_facing_url}/pay to pay online.",
        )

    if data.sms_opt_in and data.phone:
        await _opt_in_alerts(db, data.student_name, user.email, data.phone)

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    lot_assignment = data.lot_preference or (
        ",".join(pt.lot_assignments) if pt.lot_assignments else ""
    )

    session = stripe.checkout.Session.create(
        customer_email=user.email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{pt.label} Parking Permit",
                    "description": f"Plate: {data.plate.upper()} | Valid for {pt.valid_days} days",
                },
                "unit_amount": int(pt.price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "direct_permit_purchase",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_activity_permits,
                    settings.gl_segment5, settings.gl_segment6,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_activity": settings.gl_activity_permits,
                "permit_type_code": pt.code,
                "permit_type_label": pt.label,
                "permit_price": str(pt.price),
                "permit_valid_days": str(pt.valid_days),
                "plate": data.plate.upper().strip(),
                "student_name": data.student_name,
                "student_email": user.email,
                "class_year": str(data.class_year),
                "lot_assignment": lot_assignment,
                "phone": data.phone or "",
                "sms_opt_in": "true" if data.sms_opt_in else "false",
                "institution": settings.school_name or "moravian",
            },
        },
        success_url=f"{base_url}/parking?purchased=true&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/parking",
        metadata={
            "type": "direct_permit_purchase",
            "permit_type_id": str(pt.id),
            "permit_type_code": pt.code,
            "student_name": data.student_name,
            "plate": data.plate.upper().strip(),
            "email": user.email,
            "valid_days": str(pt.valid_days),
            "lot_assignment": lot_assignment,
            "phone": data.phone or "",
            "sms_opt_in": "true" if data.sms_opt_in else "false",
        },
    )

    return {"checkout_url": session.url, "session_id": session.id}


@router.post("/swap-vehicle")
async def swap_vehicle(
    data: VehicleSwapRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Change the vehicle (plate) on an existing active permit. Limited to once per week."""
    from sqlalchemy import or_

    permit = await db.get(Permit, data.permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    if permit.status != "active":
        raise HTTPException(400, "Only active permits can have their vehicle changed")

    is_owner = (permit.student_id == user.sub) or (permit.email and permit.email == user.email)
    if not is_owner:
        raise HTTPException(403, "Not your permit")

    new_plate = data.new_plate.upper().strip()
    if not new_plate:
        raise HTTPException(400, "License plate is required")

    now = datetime.now(timezone.utc)
    if permit.last_plate_change:
        cooldown_end = permit.last_plate_change + timedelta(days=7)
        if now < cooldown_end:
            next_available = cooldown_end.strftime("%B %d, %Y")
            raise HTTPException(
                429,
                f"You can only change your vehicle once per week. "
                f"Next change available {next_available}.",
            )

    dupe = await db.execute(
        select(Permit).where(
            Permit.plates.any(new_plate),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
            Permit.id != permit.id,
        )
    )
    if dupe.scalar():
        raise HTTPException(409, f"Plate {new_plate} is already registered on another active permit")

    old_plate = permit.plates[0] if permit.plates else ""
    permit.plates = [new_plate]
    permit.last_plate_change = now
    await db.flush()
    await db.refresh(permit)

    return {
        "status": "ok",
        "old_plate": old_plate,
        "new_plate": new_plate,
        "next_swap_available": (now + timedelta(days=7)).isoformat(),
    }


@router.post("/{application_id}/decline")
async def decline_offer(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Decline a lottery offer — advances the waitlist."""
    app = await db.get(PermitApplication, application_id)
    if not app:
        raise HTTPException(404, "Application not found")
    if app.student_sub != user.sub:
        raise HTTPException(403, "Not your application")
    if app.status != "selected":
        raise HTTPException(400, f"Cannot decline an application with status '{app.status}'")

    app.status = "declined"
    await db.flush()

    await _advance_waitlist(app.permit_type_id, db)

    return {"status": "declined"}


async def _advance_waitlist(permit_type_id: uuid.UUID, db: AsyncSession):
    """Promote the next waitlisted applicant to selected and notify remaining."""
    pt = await db.get(PermitType, permit_type_id)
    if not pt:
        return

    next_app = (await db.execute(
        select(PermitApplication)
        .where(
            PermitApplication.permit_type_id == permit_type_id,
            PermitApplication.status == "waitlisted",
        )
        .order_by(PermitApplication.waitlist_position.asc())
        .limit(1)
    )).scalar()

    if not next_app:
        return

    from datetime import timedelta
    now = datetime.now(timezone.utc)
    next_app.status = "selected"
    offer_days = pt.offer_window_days if pt.offer_window_days is not None else 5
    next_app.offer_expires_at = now + timedelta(days=offer_days)
    await db.flush()

    from ..services.email import send_lottery_selection_email
    from ..config import settings
    await send_lottery_selection_email(
        recipient_email=next_app.student_email,
        student_name=next_app.student_name,
        permit_type_label=pt.label,
        price=str(pt.price),
        deadline=next_app.offer_expires_at.strftime("%B %d, %Y"),
        portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
        assigned_lot=next_app.assigned_lot,
    )

    # Recompute positions for remaining waitlisted applicants
    remaining_waitlisted = (await db.execute(
        select(PermitApplication)
        .where(
            PermitApplication.permit_type_id == permit_type_id,
            PermitApplication.status == "waitlisted",
        )
        .order_by(PermitApplication.waitlist_position.asc())
    )).scalars().all()

    for new_pos, app in enumerate(remaining_waitlisted, 1):
        app.waitlist_position = new_pos
    await db.flush()

    # Send position update emails only if 24+ hours since lottery ran
    lottery_ran = pt.lottery_run_at
    cooldown_passed = (
        lottery_ran is None
        or (now - lottery_ran).total_seconds() > 86400
    )
    if cooldown_passed and remaining_waitlisted:
        import logging
        _logger = logging.getLogger(__name__)
        from ..services.email import send_waitlist_position_update_email
        total_wl = len(remaining_waitlisted)
        for app in remaining_waitlisted:
            if not app.student_email:
                continue
            try:
                await send_waitlist_position_update_email(
                    recipient_email=app.student_email,
                    student_name=app.student_name,
                    permit_type_label=pt.label,
                    new_position=app.waitlist_position,
                    total_waitlisted=total_wl,
                )
            except Exception:
                _logger.error("Failed to send waitlist update to %s", app.id, exc_info=True)
