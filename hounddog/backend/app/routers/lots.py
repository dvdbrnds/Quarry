import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.lot import ParkingLot
from ..schemas.lot import LotCreate, LotRead, LotUpdate

router = APIRouter()


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
    )
    db.add(lot)
    await db.flush()
    await db.refresh(lot)
    return lot


@router.get("/{lot_id}", response_model=LotRead)
async def get_lot(lot_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    lot = await db.get(ParkingLot, lot_id)
    if not lot or lot.deleted_at:
        raise HTTPException(404, "Lot not found")
    return lot


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
