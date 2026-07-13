import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.resident_plate import ResidentPlate
from ..schemas.resident_plate import ResidentPlateCreate, ResidentPlateRead

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ResidentPlateRead])
async def list_resident_plates(
    street_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = select(ResidentPlate).order_by(ResidentPlate.created_at.desc())
    if street_id:
        query = query.where(ResidentPlate.street_id == street_id)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=ResidentPlateRead, status_code=201)
async def tag_resident_plate(
    data: ResidentPlateCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Tag a plate as a local resident. Idempotent — returns existing if already tagged."""
    normalized = data.plate.upper().strip()
    existing = await db.execute(
        select(ResidentPlate).where(
            func.upper(ResidentPlate.plate) == normalized
        )
    )
    found = existing.scalar()
    if found:
        return found

    rp = ResidentPlate(
        plate=normalized,
        plate_state=data.plate_state.upper().strip() if data.plate_state else "",
        street_id=data.street_id,
        notes=data.notes,
        added_by=user.email,
    )
    db.add(rp)
    await db.flush()
    await db.refresh(rp)
    return rp


@router.delete("/{plate_id}", status_code=204)
async def remove_resident_plate(
    plate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    rp = await db.get(ResidentPlate, plate_id)
    if not rp:
        raise HTTPException(404, "Resident plate not found")
    await db.delete(rp)
    await db.flush()


@router.get("/check/{plate}")
async def check_resident_plate(
    plate: str,
    db: AsyncSession = Depends(get_db),
):
    """Quick lookup — returns whether a plate is tagged as a local resident."""
    normalized = plate.upper().strip()
    result = await db.execute(
        select(ResidentPlate).where(
            func.upper(ResidentPlate.plate) == normalized
        )
    )
    found = result.scalar()
    if found:
        return {"is_resident": True, "plate": found.plate, "notes": found.notes}
    return {"is_resident": False}
