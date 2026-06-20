import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user
from ..database import get_db
from ..models.lot import ParkingLot
from ..models.lot_zone import LotZone
from ..schemas.lot import (
    LotCreate,
    LotRead,
    LotReadWithZones,
    LotUpdate,
    LotZoneCreate,
    LotZoneRead,
    LotZoneUpdate,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[LotRead])
async def list_lots(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ParkingLot)
        .where(ParkingLot.deleted_at.is_(None))
        .order_by(ParkingLot.name)
    )
    return result.scalars().all()


@router.post("", response_model=LotRead, status_code=201)
async def create_lot(data: LotCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(ParkingLot).where(ParkingLot.name == data.name, ParkingLot.deleted_at.is_(None))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Lot '{data.name}' already exists")

    lot = ParkingLot(
        name=data.name,
        boundary=[c.model_dump() for c in data.boundary],
        total_spaces=data.total_spaces,
        handicap_spaces=data.handicap_spaces,
        designation_code=data.designation_code,
        designation_label=data.designation_label,
        access_schedule=[s.model_dump() for s in data.access_schedule],
        is_snow_lot=data.is_snow_lot,
        notes=data.notes,
    )
    db.add(lot)
    await db.flush()
    await db.refresh(lot)
    return lot


@router.get("/{lot_id}", response_model=LotReadWithZones)
async def get_lot(lot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    zones_result = await db.execute(
        select(LotZone).where(LotZone.lot_id == lot_id).order_by(LotZone.zone_type)
    )
    zones = zones_result.scalars().all()

    lot_data = LotReadWithZones.model_validate(lot)
    lot_data.zones = [LotZoneRead.model_validate(z) for z in zones]
    return lot_data


@router.put("/{lot_id}", response_model=LotRead)
async def update_lot(
    lot_id: uuid.UUID, data: LotUpdate, db: AsyncSession = Depends(get_db)
):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    if data.name is not None:
        lot.name = data.name
    if data.boundary is not None:
        lot.boundary = [c.model_dump() for c in data.boundary]
    if data.total_spaces is not None:
        lot.total_spaces = data.total_spaces
    if data.handicap_spaces is not None:
        lot.handicap_spaces = data.handicap_spaces
    if data.designation_code is not None:
        lot.designation_code = data.designation_code
    if data.designation_label is not None:
        lot.designation_label = data.designation_label
    if data.access_schedule is not None:
        lot.access_schedule = [s.model_dump() for s in data.access_schedule]
    if data.is_snow_lot is not None:
        lot.is_snow_lot = data.is_snow_lot
    if data.notes is not None:
        lot.notes = data.notes

    await db.flush()
    await db.refresh(lot)
    return lot


@router.delete("/{lot_id}", status_code=204)
async def delete_lot(lot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")
    lot.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# --- Zone CRUD (nested under lots) ---


@router.get("/{lot_id}/zones", response_model=list[LotZoneRead])
async def list_zones(lot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    result = await db.execute(
        select(LotZone).where(LotZone.lot_id == lot_id).order_by(LotZone.zone_type)
    )
    return result.scalars().all()


@router.post("/{lot_id}/zones", response_model=LotZoneRead, status_code=201)
async def create_zone(
    lot_id: uuid.UUID, data: LotZoneCreate, db: AsyncSession = Depends(get_db)
):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    zone = LotZone(
        lot_id=lot_id,
        zone_type=data.zone_type,
        label=data.label,
        space_count=data.space_count,
        boundary=[c.model_dump() for c in data.boundary],
        fine_override=data.fine_override,
        is_premium=data.is_premium,
        notes=data.notes,
    )
    db.add(zone)
    await db.flush()
    await db.refresh(zone)
    return zone


@router.put("/{lot_id}/zones/{zone_id}", response_model=LotZoneRead)
async def update_zone(
    lot_id: uuid.UUID,
    zone_id: uuid.UUID,
    data: LotZoneUpdate,
    db: AsyncSession = Depends(get_db),
):
    zone = await db.get(LotZone, zone_id)
    if not zone or zone.lot_id != lot_id:
        raise HTTPException(404, "Zone not found")

    updates = data.model_dump(exclude_unset=True)
    if "boundary" in updates and updates["boundary"] is not None:
        updates["boundary"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in updates["boundary"]]

    for field, value in updates.items():
        setattr(zone, field, value)

    await db.flush()
    await db.refresh(zone)
    return zone


@router.delete("/{lot_id}/zones/{zone_id}", status_code=204)
async def delete_zone(
    lot_id: uuid.UUID, zone_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    zone = await db.get(LotZone, zone_id)
    if not zone or zone.lot_id != lot_id:
        raise HTTPException(404, "Zone not found")
    await db.delete(zone)
    await db.flush()
