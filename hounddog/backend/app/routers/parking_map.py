from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.lot import ParkingLot

router = APIRouter()


def _lot_to_public(lot: ParkingLot) -> dict:
    return {
        "id": str(lot.id),
        "name": lot.name,
        "boundary": lot.boundary,
        "total_spaces": lot.total_spaces,
        "handicap_spaces": lot.handicap_spaces,
        "designation_code": lot.designation_code,
        "designation_label": lot.designation_label,
        "lot_type": lot.lot_type,
        "external_url": lot.external_url,
        "external_provider": lot.external_provider,
        "is_closed": lot.is_closed,
        "campus": lot.campus,
    }


@router.get("")
async def get_parking_map(db: AsyncSession = Depends(get_db)):
    """
    Public parking map data. Returns all non-deleted lots with boundaries.
    Auth gating is handled client-side based on the public_map_requires_auth config flag.
    """
    result = await db.execute(
        select(ParkingLot)
        .where(ParkingLot.deleted_at.is_(None))
        .order_by(ParkingLot.name)
    )
    lots = result.scalars().all()
    return [_lot_to_public(lot) for lot in lots]
