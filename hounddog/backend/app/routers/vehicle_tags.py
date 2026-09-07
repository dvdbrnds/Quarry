"""Vehicle Tags — known vehicles without permits.

Officers can run plates through JNET/CLEAN state systems and register
them here so the parking system recognises the vehicle and its owner
even when no permit has been purchased.
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_office
from ..database import get_db
from ..models.permit import Permit

router = APIRouter(dependencies=[Depends(get_current_user)])


class VehicleTagCreate(BaseModel):
    name: str
    plates: list[str]
    plate_state: str = ""
    email: str | None = None
    phone: str = ""
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    vehicle_year: str | None = None
    tag_notes: str | None = None
    tag_source: str | None = None  # "JNET", "CLEAN", "manual", etc.


class VehicleTagUpdate(BaseModel):
    name: str | None = None
    plates: list[str] | None = None
    plate_state: str | None = None
    email: str | None = None
    phone: str | None = None
    vehicle_make: str | None = None
    vehicle_model: str | None = None
    vehicle_color: str | None = None
    vehicle_year: str | None = None
    tag_notes: str | None = None
    tag_source: str | None = None
    status: str | None = None


class VehicleTagRead(BaseModel):
    id: uuid.UUID
    name: str
    plates: list[str]
    email: str | None
    phone: str
    vehicle_make: str | None
    vehicle_model: str | None
    vehicle_color: str | None
    vehicle_year: str | None
    tag_notes: str | None
    tag_source: str | None
    status: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VehicleTagList(BaseModel):
    items: list[VehicleTagRead]
    total: int


@router.get("", response_model=VehicleTagList)
async def list_vehicle_tags(
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_office()),
):
    query = select(Permit).where(
        Permit.is_tag_only.is_(True),
        Permit.deleted_at.is_(None),
    )

    if search:
        term = f"%{search}%"
        query = query.where(
            or_(
                Permit.name.ilike(term),
                func.array_to_string(Permit.plates, ",").ilike(term),
                Permit.vehicle_make.ilike(term),
                Permit.vehicle_model.ilike(term),
                Permit.vehicle_color.ilike(term),
                Permit.tag_notes.ilike(term),
            )
        )

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    tags = (
        await db.execute(
            query.order_by(desc(Permit.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return VehicleTagList(
        items=[VehicleTagRead(
            id=t.id,
            name=t.name,
            plates=t.plates,
            email=t.email,
            phone=t.phone or "",
            vehicle_make=t.vehicle_make,
            vehicle_model=t.vehicle_model,
            vehicle_color=t.vehicle_color,
            vehicle_year=t.vehicle_year,
            tag_notes=t.tag_notes,
            tag_source=t.tag_source,
            status=t.status,
            created_at=t.created_at,
            updated_at=t.updated_at,
        ) for t in tags],
        total=total,
    )


@router.post("", response_model=VehicleTagRead, status_code=201)
async def create_vehicle_tag(
    data: VehicleTagCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    if not data.plates:
        raise HTTPException(400, "At least one plate is required")

    vehicle_desc_parts = [p for p in [data.vehicle_year, data.vehicle_make, data.vehicle_model, data.vehicle_color] if p]
    vehicle_desc = " ".join(vehicle_desc_parts) if vehicle_desc_parts else ""

    tag = Permit(
        name=data.name,
        plates=[p.strip().upper().replace(" ", "").replace("-", "") for p in data.plates],
        email=data.email,
        phone=data.phone,
        permit_type="vehicle_tag",
        status="active",
        lot_assignment="",
        is_tag_only=True,
        vehicle_make=data.vehicle_make,
        vehicle_model=data.vehicle_model,
        vehicle_color=data.vehicle_color,
        vehicle_year=data.vehicle_year,
        tag_notes=data.tag_notes,
        tag_source=data.tag_source,
    )
    db.add(tag)
    await db.flush()
    await db.refresh(tag)

    return VehicleTagRead(
        id=tag.id,
        name=tag.name,
        plates=tag.plates,
        email=tag.email,
        phone=tag.phone or "",
        vehicle_make=tag.vehicle_make,
        vehicle_model=tag.vehicle_model,
        vehicle_color=tag.vehicle_color,
        vehicle_year=tag.vehicle_year,
        tag_notes=tag.tag_notes,
        tag_source=tag.tag_source,
        status=tag.status,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


@router.put("/{tag_id}", response_model=VehicleTagRead)
async def update_vehicle_tag(
    tag_id: uuid.UUID,
    data: VehicleTagUpdate,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_office()),
):
    tag = await db.get(Permit, tag_id)
    if not tag or tag.deleted_at or not tag.is_tag_only:
        raise HTTPException(404, "Vehicle tag not found")

    if data.name is not None:
        tag.name = data.name
    if data.plates is not None:
        tag.plates = [p.strip().upper().replace(" ", "").replace("-", "") for p in data.plates]
    if data.email is not None:
        tag.email = data.email
    if data.phone is not None:
        tag.phone = data.phone
    if data.vehicle_make is not None:
        tag.vehicle_make = data.vehicle_make
    if data.vehicle_model is not None:
        tag.vehicle_model = data.vehicle_model
    if data.vehicle_color is not None:
        tag.vehicle_color = data.vehicle_color
    if data.vehicle_year is not None:
        tag.vehicle_year = data.vehicle_year
    if data.tag_notes is not None:
        tag.tag_notes = data.tag_notes
    if data.tag_source is not None:
        tag.tag_source = data.tag_source
    if data.status is not None:
        tag.status = data.status

    await db.flush()
    await db.refresh(tag)

    return VehicleTagRead(
        id=tag.id,
        name=tag.name,
        plates=tag.plates,
        email=tag.email,
        phone=tag.phone or "",
        vehicle_make=tag.vehicle_make,
        vehicle_model=tag.vehicle_model,
        vehicle_color=tag.vehicle_color,
        vehicle_year=tag.vehicle_year,
        tag_notes=tag.tag_notes,
        tag_source=tag.tag_source,
        status=tag.status,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


class ConvertTagRequest(BaseModel):
    permit_type: str
    lot_assignment: str | None = None
    waive_fee: bool = True


@router.post("/{tag_id}/convert")
async def convert_tag_to_permit(
    tag_id: uuid.UUID,
    data: ConvertTagRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    """Convert a vehicle tag into a real permit.

    Keeps the same record (same plate, owner info) and just changes
    permit_type, assigns lots, clears the tag flag, and generates a
    permit number.
    """
    from ..models.permit_type import PermitType
    from ..services.lot_assignment import effective_lot_assignment

    tag = await db.get(Permit, tag_id)
    if not tag or tag.deleted_at or not tag.is_tag_only:
        raise HTTPException(404, "Vehicle tag not found")

    pt = (await db.execute(
        select(PermitType).where(PermitType.code == data.permit_type)
    )).scalar_one_or_none()
    if not pt:
        raise HTTPException(400, f"Unknown permit type: {data.permit_type}")

    # Generate a permit number
    seq = await db.execute(select(func.nextval("qps_permit_number_seq")))
    seq_val = seq.scalar()
    permit_number = f"QPS-{seq_val:05d}"

    # Resolve lot assignment
    type_lots = list(pt.lot_assignments or [])
    lot_assignment = effective_lot_assignment(data.lot_assignment, type_lots)

    from datetime import timedelta
    from ..services.timeutils import today_local

    tag.permit_type = pt.code
    tag.lot_assignment = lot_assignment
    tag.permit_number = permit_number
    tag.is_tag_only = False
    tag.start_date = today_local()
    tag.end_date = today_local() + timedelta(days=pt.valid_days)
    tag.status = "active"

    await db.flush()
    await db.refresh(tag)

    return {
        "id": str(tag.id),
        "permit_number": tag.permit_number,
        "permit_type": tag.permit_type,
        "lot_assignment": tag.lot_assignment,
        "name": tag.name,
        "status": tag.status,
    }


@router.delete("/{tag_id}", status_code=204)
async def delete_vehicle_tag(
    tag_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_office()),
):
    tag = await db.get(Permit, tag_id)
    if not tag or tag.deleted_at or not tag.is_tag_only:
        raise HTTPException(404, "Vehicle tag not found")
    tag.deleted_at = datetime.now(timezone.utc)
    await db.flush()
