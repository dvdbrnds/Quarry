"""Student-facing permit application endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_application import PermitApplication
from ..models.permit_type import PermitType
from ..schemas.permit_application import (
    ApplicationSubmit,
    ApplicationWithType,
    AvailablePermitType,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/available", response_model=list[AvailablePermitType])
async def available_permit_types(db: AsyncSession = Depends(get_db)):
    """List permit types currently open for application."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(PermitType).where(
            PermitType.is_active.is_(True),
            PermitType.application_opens_at.isnot(None),
            PermitType.application_opens_at <= now,
            PermitType.application_closes_at.isnot(None),
            PermitType.application_closes_at > now,
        ).order_by(PermitType.sort_order)
    )
    types = result.scalars().all()

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

        out.append(AvailablePermitType(
            id=pt.id,
            code=pt.code,
            label=pt.label,
            eligible=pt.eligible,
            price=pt.price,
            max_capacity=pt.max_capacity,
            remaining=remaining,
            lot_assignments=pt.lot_assignments,
            valid_days=pt.valid_days,
            application_closes_at=pt.application_closes_at,
            requires_lottery=pt.requires_lottery,
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

    if not pt.application_opens_at or not pt.application_closes_at:
        raise HTTPException(400, "This permit type is not accepting applications")
    if now < pt.application_opens_at:
        raise HTTPException(400, "Application window has not opened yet")
    if now > pt.application_closes_at:
        raise HTTPException(400, "Application window has closed")

    existing = await db.execute(
        select(PermitApplication).where(
            PermitApplication.student_sub == user.sub,
            PermitApplication.permit_type_id == pt.id,
            PermitApplication.status.notin_(["expired", "declined"]),
        )
    )
    if existing.scalar():
        raise HTTPException(409, "You already have an active application for this permit type")

    app = PermitApplication(
        student_sub=user.sub,
        student_email=user.email,
        student_name=data.student_name,
        class_year=data.class_year,
        permit_type_id=pt.id,
        plate=data.plate.upper().strip(),
        phone=data.phone,
    )
    db.add(app)
    await db.flush()
    await db.refresh(app)

    return ApplicationWithType(
        **{k: v for k, v in app.__dict__.items() if not k.startswith("_")},
        permit_type_label=pt.label,
        permit_type_code=pt.code,
        permit_type_price=pt.price,
        lot_assignments=pt.lot_assignments,
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

    out: list[ApplicationWithType] = []
    for app in apps:
        pt = await db.get(PermitType, app.permit_type_id)
        out.append(ApplicationWithType(
            **{k: v for k, v in app.__dict__.items() if not k.startswith("_")},
            permit_type_label=pt.label if pt else "",
            permit_type_code=pt.code if pt else "",
            permit_type_price=pt.price if pt else 0,
            lot_assignments=pt.lot_assignments if pt else [],
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

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
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
    """Promote the next waitlisted applicant to selected."""
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
    next_app.status = "selected"
    next_app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=pt.offer_window_days)
    await db.flush()

    from ..services.email import send_email
    await send_email(
        to=[next_app.student_email],
        subject=f"Parking Permit Offer — {pt.label}",
        body_html=(
            f"<p>Good news! A spot has opened up for <strong>{pt.label}</strong>.</p>"
            f"<p>Log in to the student portal to accept your offer before "
            f"<strong>{next_app.offer_expires_at.strftime('%b %d, %Y')}</strong>.</p>"
        ),
    )
