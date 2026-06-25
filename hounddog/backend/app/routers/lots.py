import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser
from ..database import get_db
from ..models.lot import ParkingLot
from ..models.lot_closure import LotClosure
from ..models.lot_zone import LotZone
from ..models.parking_spot import ParkingSpot
from ..models.permit import Permit
from ..schemas.lot import (
    LotCreate,
    LotRead,
    LotReadWithZones,
    LotUpdate,
    LotZoneCreate,
    LotZoneRead,
    LotZoneUpdate,
)
from ..schemas.parking_spot import SpotCreate, SpotRead, SpotUpdate
from ..schemas.lot_closure import (
    CloseLotNow,
    LotClosureCreate,
    LotClosureRead,
    LotClosureUpdate,
    LotClosureWithLotName,
)
from ..services.email import send_lot_closure_notification, send_lot_reopen_notification

logger = logging.getLogger("quarry.lots")

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

    stale = await db.execute(
        select(ParkingLot).where(ParkingLot.name == data.name, ParkingLot.deleted_at.isnot(None))
    )
    for old in stale.scalars().all():
        await db.delete(old)
    await db.flush()

    lot = ParkingLot(
        name=data.name,
        boundary=[c.model_dump() for c in data.boundary],
        total_spaces=data.total_spaces,
        handicap_spaces=data.handicap_spaces,
        designation_code=data.designation_code,
        designation_label=data.designation_label,
        access_schedule=[s.model_dump() for s in data.access_schedule],
        is_snow_lot=data.is_snow_lot,
        has_sheepdog=data.has_sheepdog,
        notes=data.notes,
    )
    db.add(lot)
    await db.flush()
    await db.refresh(lot)
    return lot


# --- Closure routes (static paths before /{lot_id} to avoid conflicts) ---


@router.get("/closures/all", response_model=list[LotClosureWithLotName])
async def list_all_closures(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(LotClosure, ParkingLot.name).join(
        ParkingLot, LotClosure.lot_id == ParkingLot.id
    ).where(ParkingLot.deleted_at.is_(None))
    if status:
        q = q.where(LotClosure.status == status)
    q = q.order_by(LotClosure.closes_at.desc())

    rows = (await db.execute(q)).all()
    result = []
    for closure, lot_name in rows:
        data = LotClosureWithLotName.model_validate(closure)
        data.lot_name = lot_name
        result.append(data)
    return result


@router.post("/closures", response_model=LotClosureRead, status_code=201)
async def schedule_closure(
    data: LotClosureCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    lot = await db.get(ParkingLot, data.lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    closure = LotClosure(
        lot_id=data.lot_id,
        reason=data.reason,
        closes_at=data.closes_at,
        reopens_at=data.reopens_at,
        is_immediate=data.is_immediate,
        status="scheduled",
        created_by=user.email,
    )
    db.add(closure)
    await db.flush()
    await db.refresh(closure)
    return closure


@router.put("/closures/{closure_id}", response_model=LotClosureRead)
async def update_closure(
    closure_id: uuid.UUID,
    data: LotClosureUpdate,
    db: AsyncSession = Depends(get_db),
):
    closure = await db.get(LotClosure, closure_id)
    if not closure:
        raise HTTPException(404, "Closure not found")

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(closure, field, value)

    await db.flush()
    await db.refresh(closure)
    return closure


@router.delete("/closures/{closure_id}", status_code=204)
async def cancel_closure(closure_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    closure = await db.get(LotClosure, closure_id)
    if not closure:
        raise HTTPException(404, "Closure not found")
    closure.status = "cancelled"
    await db.flush()


# --- Lot CRUD (parameterized paths) ---


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
    if data.has_sheepdog is not None:
        lot.has_sheepdog = data.has_sheepdog
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

    open_closures = (
        await db.execute(
            select(LotClosure).where(
                LotClosure.lot_id == lot_id,
                LotClosure.status.in_(["scheduled", "active"]),
            )
        )
    ).scalars().all()
    for closure in open_closures:
        closure.status = "cancelled"

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


# --- Spot CRUD (SheepDog puck assignments) ---


@router.get("/{lot_id}/spots", response_model=list[SpotRead])
async def list_spots(lot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    result = await db.execute(
        select(ParkingSpot).where(ParkingSpot.lot_id == lot_id).order_by(ParkingSpot.number)
    )
    return result.scalars().all()


@router.post("/{lot_id}/spots", response_model=SpotRead, status_code=201)
async def create_spot(
    lot_id: uuid.UUID, data: SpotCreate, db: AsyncSession = Depends(get_db)
):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    spot = ParkingSpot(
        lot_id=lot_id,
        number=data.number,
        label=data.label,
        sensor_id=data.sensor_id,
        latitude=data.latitude,
        longitude=data.longitude,
    )
    db.add(spot)
    await db.flush()
    await db.refresh(spot)
    return spot


@router.put("/{lot_id}/spots/{spot_id}", response_model=SpotRead)
async def update_spot(
    lot_id: uuid.UUID,
    spot_id: uuid.UUID,
    data: SpotUpdate,
    db: AsyncSession = Depends(get_db),
):
    spot = await db.get(ParkingSpot, spot_id)
    if not spot or spot.lot_id != lot_id:
        raise HTTPException(404, "Spot not found")

    updates = data.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(spot, field, value)

    await db.flush()
    await db.refresh(spot)
    return spot


@router.delete("/{lot_id}/spots/{spot_id}", status_code=204)
async def delete_spot(
    lot_id: uuid.UUID, spot_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    spot = await db.get(ParkingSpot, spot_id)
    if not spot or spot.lot_id != lot_id:
        raise HTTPException(404, "Spot not found")
    await db.delete(spot)
    await db.flush()


# --- Lot Closures ---


async def _get_closure_recipients(
    lot_id: uuid.UUID, extra: list[str], db: AsyncSession
) -> list[str]:
    """Build the email list: permits assigned to the lot + any extras."""
    from ..config import settings

    recipients = set(extra)
    if settings.lot_closure_mailing_list:
        recipients.update(
            e.strip()
            for e in settings.lot_closure_mailing_list.split(",")
            if e.strip()
        )

    lot = await db.get(ParkingLot, lot_id)
    if lot:
        result = await db.execute(
            select(Permit.email).where(
                Permit.lot_assignment == lot.name,
                Permit.email.isnot(None),
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )
        for (email,) in result.all():
            if email:
                recipients.add(email)

    return list(recipients)


@router.post("/{lot_id}/close", response_model=LotClosureRead)
async def close_lot_now(
    lot_id: uuid.UUID,
    body: CloseLotNow,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    now = datetime.now(timezone.utc)
    closure = LotClosure(
        lot_id=lot_id,
        reason=body.reason,
        closes_at=now,
        reopens_at=body.reopens_at,
        is_immediate=True,
        status="active",
        notification_sent=True,
        created_by=user.email,
    )
    lot.is_closed = True
    db.add(closure)
    await db.flush()
    await db.refresh(closure)

    recipients = await _get_closure_recipients(lot_id, body.recipients, db)
    reopens_str = body.reopens_at.strftime("%b %d, %Y %I:%M %p") if body.reopens_at else None
    await send_lot_closure_notification(
        lot_name=lot.name,
        reason=body.reason,
        recipients=recipients,
        closes_at=now.strftime("%b %d, %Y %I:%M %p %Z"),
        reopens_at=reopens_str,
    )

    return closure


@router.post("/{lot_id}/reopen", response_model=LotRead)
async def reopen_lot(
    lot_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")

    lot.is_closed = False

    active_closures = (
        await db.execute(
            select(LotClosure).where(
                LotClosure.lot_id == lot_id,
                LotClosure.status == "active",
            )
        )
    ).scalars().all()
    for c in active_closures:
        c.status = "completed"
        c.reopens_at = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(lot)

    recipients = await _get_closure_recipients(lot_id, [], db)
    await send_lot_reopen_notification(lot.name, recipients)

    return lot
