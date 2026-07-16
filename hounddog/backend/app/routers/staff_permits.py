"""Staff/faculty self-service vehicle enrollment — no lottery, no cost."""

import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_role
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..services.permit_numbering import next_permit_number


_require_staff = require_role("admin", "staff")

router = APIRouter(dependencies=[Depends(_require_staff)])


STAFF_PERMIT_CODE = "faculty_staff"


class VehicleEnroll(BaseModel):
    name: str
    plate: str
    plate_state: str = ""


class VehicleRead(BaseModel):
    id: str
    permit_number: str | None
    name: str
    email: str | None
    plate: str
    lot_assignment: str
    status: str
    start_date: str
    end_date: str | None
    permit_type: str = ""
    permit_type_label: str = ""


class AvailableStaffPermit(BaseModel):
    id: str
    code: str
    label: str
    eligible: str
    lot_assignments: list[str]
    valid_days: int


@router.get("/available", response_model=list[AvailableStaffPermit])
async def available_staff_permits(db: AsyncSession = Depends(get_db)):
    """Return the faculty/staff permit type(s) available for enrollment."""
    result = await db.execute(
        select(PermitType).where(
            PermitType.is_active.is_(True),
            PermitType.code == STAFF_PERMIT_CODE,
        )
    )
    types = result.scalars().all()
    return [
        AvailableStaffPermit(
            id=str(pt.id),
            code=pt.code,
            label=pt.label,
            eligible=pt.eligible,
            lot_assignments=pt.lot_assignments,
            valid_days=pt.valid_days,
        )
        for pt in types
    ]


@router.post("/enroll", response_model=VehicleRead, status_code=201)
async def enroll_vehicle(
    data: VehicleEnroll,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Register a vehicle — creates a permit immediately (no lottery, no cost)."""
    pt_result = await db.execute(
        select(PermitType).where(
            PermitType.code == STAFF_PERMIT_CODE,
            PermitType.is_active.is_(True),
        )
    )
    pt = pt_result.scalar()
    if not pt:
        raise HTTPException(404, "Staff/faculty permit type not configured")

    plate = data.plate.upper().strip()
    if not plate:
        raise HTTPException(400, "License plate is required")

    existing = await db.execute(
        select(Permit).where(
            Permit.plates.any(plate),
            Permit.permit_type == STAFF_PERMIT_CODE,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    if existing.scalar():
        raise HTTPException(409, f"Plate {plate} is already registered for a faculty/staff permit")

    new_start = date.today()
    target = date(new_start.year, 6, 30)
    if target <= new_start:
        target = date(new_start.year + 1, 6, 30)

    permit = Permit(
        permit_number=await next_permit_number(db),
        name=data.name.strip(),
        email=user.email,
        student_id=user.sub,
        plates=[plate],
        lot_assignment=", ".join(pt.lot_assignments) if pt.lot_assignments else "",
        permit_type=STAFF_PERMIT_CODE,
        start_date=new_start,
        end_date=target,
        status="active",
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)

    return VehicleRead(
        id=str(permit.id),
        permit_number=permit.permit_number,
        name=permit.name,
        email=permit.email,
        plate=plate,
        lot_assignment=permit.lot_assignment,
        status=permit.status,
        start_date=permit.start_date.isoformat(),
        end_date=permit.end_date.isoformat() if permit.end_date else None,
        permit_type=permit.permit_type or "",
        permit_type_label=pt.label,
    )


@router.get("/my-vehicles", response_model=list[VehicleRead])
async def my_vehicles(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """List all of the current user's permits (including legacy/imported)."""
    from sqlalchemy import or_

    result = await db.execute(
        select(Permit).where(
            or_(Permit.student_id == user.sub, Permit.email == user.email),
            Permit.deleted_at.is_(None),
        ).order_by(Permit.created_at.desc())
    )
    permits = result.scalars().all()

    pt_codes = {p.permit_type for p in permits if p.permit_type}
    label_map: dict[str, str] = {}
    if pt_codes:
        pt_result = await db.execute(
            select(PermitType.code, PermitType.label).where(PermitType.code.in_(pt_codes))
        )
        label_map = {row.code: row.label for row in pt_result}

    return [
        VehicleRead(
            id=str(p.id),
            permit_number=p.permit_number,
            name=p.name,
            email=p.email,
            plate=p.plates[0] if p.plates else "",
            lot_assignment=p.lot_assignment,
            status=p.status,
            start_date=p.start_date.isoformat(),
            end_date=p.end_date.isoformat() if p.end_date else None,
            permit_type=p.permit_type or "",
            permit_type_label=label_map.get(p.permit_type or "", p.permit_type or ""),
        )
        for p in permits
    ]


@router.delete("/{permit_id}", status_code=204)
async def remove_vehicle(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Remove a vehicle registration."""
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Vehicle registration not found")
    if permit.student_id != user.sub:
        raise HTTPException(403, "Not your vehicle registration")
    if permit.permit_type != STAFF_PERMIT_CODE:
        raise HTTPException(400, "This is not a staff/faculty vehicle registration")

    permit.deleted_at = datetime.now(timezone.utc)
    await db.flush()
