"""Overnight guest registration endpoints for students and admins."""

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, get_current_user_or_impersonated, require_office
from ..database import get_db
from ..models.guest_registration import GuestRegistration
from ..models.permit import Permit

# ── Student-facing router ────────────────────────────────────────────

student_router = APIRouter(dependencies=[Depends(get_current_user)])


class GuestCreate(BaseModel):
    guest_name: str = Field(..., min_length=1, max_length=256)
    guest_plate: str = Field(..., min_length=1, max_length=20)
    guest_plate_state: str = "PA"
    check_in: date
    check_out: date
    roommate_consent: bool
    notes: str | None = None


class GuestRead(BaseModel):
    id: uuid.UUID
    host_email: str
    host_name: str
    guest_name: str
    guest_plate: str | None
    guest_plate_state: str
    check_in: date
    check_out: date
    roommate_consent: bool
    notes: str | None
    status: str
    created_at: str

    class Config:
        from_attributes = True


@student_router.get("", response_model=list[GuestRead])
async def list_my_guests(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    cutoff = date.today() - timedelta(days=30)
    result = await db.execute(
        select(GuestRegistration)
        .where(
            func.lower(GuestRegistration.host_email) == (user.email or "").lower(),
            or_(
                GuestRegistration.status == "active",
                GuestRegistration.check_out >= cutoff,
            ),
        )
        .order_by(GuestRegistration.check_in.desc())
    )
    rows = result.scalars().all()
    return [
        GuestRead(
            id=r.id,
            host_email=r.host_email,
            host_name=r.host_name,
            guest_name=r.guest_name,
            guest_plate=r.guest_plate,
            guest_plate_state=r.guest_plate_state or "PA",
            check_in=r.check_in,
            check_out=r.check_out,
            roommate_consent=r.roommate_consent,
            notes=r.notes,
            status=r.status,
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@student_router.post("", response_model=GuestRead, status_code=201)
async def register_guest(
    data: GuestCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    if not data.roommate_consent:
        raise HTTPException(400, "Roommate consent is required for overnight guests.")

    if data.check_in < date.today():
        raise HTTPException(400, "Check-in date cannot be in the past.")

    stay_days = (data.check_out - data.check_in).days
    if stay_days < 1:
        raise HTTPException(400, "Check-out must be after check-in.")
    if stay_days > 2:
        raise HTTPException(400, "Guests may stay a maximum of 2 consecutive nights (48 hours).")

    # 7-day overlap check: no more than 2 total guest-nights within any 7-day window
    window_start = data.check_in - timedelta(days=7)
    window_end = data.check_out + timedelta(days=7)
    overlap_result = await db.execute(
        select(GuestRegistration).where(
            func.lower(GuestRegistration.host_email) == (user.email or "").lower(),
            GuestRegistration.status == "active",
            GuestRegistration.check_out > window_start,
            GuestRegistration.check_in < window_end,
        )
    )
    existing = overlap_result.scalars().all()

    # Count total guest-nights in the 7-day window around the new stay
    for day_offset in range(stay_days):
        check_day = data.check_in + timedelta(days=day_offset)
        window_start_day = check_day - timedelta(days=6)
        window_end_day = check_day + timedelta(days=1)

        nights_in_window = 0
        for reg in existing:
            overlap_start = max(reg.check_in, window_start_day)
            overlap_end = min(reg.check_out, window_end_day)
            if overlap_end > overlap_start:
                nights_in_window += (overlap_end - overlap_start).days

        if nights_in_window + stay_days > 2:
            raise HTTPException(
                400,
                "This would exceed the 2-night maximum within a 7-day period. "
                "Guests can stay a maximum of 2 consecutive days within any 7-day window."
            )

    host_name = user.email or ""
    if hasattr(user, "profile") and user.profile:
        display = user.profile.get("displayName") or user.profile.get("name")
        if display:
            host_name = display

    reg = GuestRegistration(
        host_email=(user.email or "").lower(),
        host_name=host_name,
        guest_name=data.guest_name.strip(),
        guest_plate=(data.guest_plate or "").strip().upper() or None,
        guest_plate_state=(data.guest_plate_state or "PA").strip().upper()[:2],
        check_in=data.check_in,
        check_out=data.check_out,
        roommate_consent=True,
        notes=(data.notes or "").strip() or None,
    )
    db.add(reg)
    await db.flush()
    await db.refresh(reg)

    # Auto-create a temporary guest permit with commuter lot access
    plate = (data.guest_plate or "").strip().upper()
    if plate:
        from ..models.permit_type import PermitType
        pt_result = await db.execute(
            select(PermitType).where(PermitType.code == "student_guest")
        )
        guest_pt = pt_result.scalars().first()
        lot_assignment = ", ".join(guest_pt.lot_assignments) if guest_pt and guest_pt.lot_assignments else "X, A, F, H, M, N, O, R, S, U"

        from ..services.permit_numbering import next_permit_number
        guest_permit = Permit(
            permit_number=await next_permit_number(db),
            name=f"Guest of {host_name} — {data.guest_name.strip()}",
            email=(user.email or "").lower(),
            plates=[plate],
            lot_assignment=lot_assignment,
            permit_type="student_guest",
            start_date=data.check_in,
            end_date=data.check_out,
            status="active",
        )
        db.add(guest_permit)
        await db.flush()

    return GuestRead(
        id=reg.id,
        host_email=reg.host_email,
        host_name=reg.host_name,
        guest_name=reg.guest_name,
        guest_plate=reg.guest_plate,
        guest_plate_state=reg.guest_plate_state or "PA",
        check_in=reg.check_in,
        check_out=reg.check_out,
        roommate_consent=reg.roommate_consent,
        notes=reg.notes,
        status=reg.status,
        created_at=reg.created_at.isoformat() if reg.created_at else "",
    )


@student_router.delete("/{guest_id}", status_code=204)
async def cancel_guest(
    guest_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    reg = await db.get(GuestRegistration, guest_id)
    if not reg:
        raise HTTPException(404, "Guest registration not found")
    if reg.host_email.lower() != (user.email or "").lower():
        raise HTTPException(403, "You can only cancel your own guest registrations")
    reg.status = "cancelled"
    await db.flush()


# ── Admin router ─────────────────────────────────────────────────────

admin_router = APIRouter(dependencies=[Depends(require_office())])


@admin_router.get("")
async def list_all_guests(
    db: AsyncSession = Depends(get_db),
    search: str | None = Query(None),
    status: str | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
):
    query = select(GuestRegistration).order_by(GuestRegistration.check_in.desc())

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                GuestRegistration.host_name.ilike(like),
                GuestRegistration.host_email.ilike(like),
                GuestRegistration.guest_name.ilike(like),
                GuestRegistration.guest_plate.ilike(like),
            )
        )
    if status:
        query = query.where(GuestRegistration.status == status)
    if from_date:
        query = query.where(GuestRegistration.check_in >= from_date)
    if to_date:
        query = query.where(GuestRegistration.check_out <= to_date)

    result = await db.execute(query.limit(500))
    rows = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "host_email": r.host_email,
            "host_name": r.host_name,
            "guest_name": r.guest_name,
            "guest_plate": r.guest_plate,
            "guest_plate_state": r.guest_plate_state,
            "check_in": r.check_in.isoformat(),
            "check_out": r.check_out.isoformat(),
            "roommate_consent": r.roommate_consent,
            "notes": r.notes,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
