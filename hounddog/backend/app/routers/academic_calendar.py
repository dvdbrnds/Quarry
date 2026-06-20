import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, require_admin
from ..database import get_db
from ..models.academic_season import AcademicSeason
from ..schemas.academic_season import (
    AcademicSeasonCreate,
    AcademicSeasonRead,
    AcademicSeasonUpdate,
    ActiveSeasonResponse,
)

router = APIRouter(dependencies=[Depends(require_admin())])


@router.get("", response_model=list[AcademicSeasonRead])
async def list_seasons(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AcademicSeason).order_by(AcademicSeason.start_date)
    )
    return result.scalars().all()


@router.get("/active", response_model=ActiveSeasonResponse)
async def get_active_season(db: AsyncSession = Depends(get_db)):
    today = date.today()
    result = await db.execute(
        select(AcademicSeason).where(
            AcademicSeason.start_date <= today,
            AcademicSeason.end_date >= today,
        )
    )
    season = result.scalar()

    if not season:
        result = await db.execute(
            select(AcademicSeason).where(AcademicSeason.is_default.is_(True))
        )
        season = result.scalar()

    if season:
        return ActiveSeasonResponse(season=season)
    return ActiveSeasonResponse(season=None)


@router.post("", response_model=AcademicSeasonRead, status_code=201)
async def create_season(
    data: AcademicSeasonCreate, db: AsyncSession = Depends(get_db)
):
    if data.is_default:
        await db.execute(
            select(AcademicSeason).where(AcademicSeason.is_default.is_(True))
        )
        existing_defaults = (
            await db.execute(
                select(AcademicSeason).where(AcademicSeason.is_default.is_(True))
            )
        ).scalars().all()
        for s in existing_defaults:
            s.is_default = False

    season = AcademicSeason(**data.model_dump())
    db.add(season)
    await db.flush()
    await db.refresh(season)
    return season


@router.put("/{season_id}", response_model=AcademicSeasonRead)
async def update_season(
    season_id: uuid.UUID,
    data: AcademicSeasonUpdate,
    db: AsyncSession = Depends(get_db),
):
    season = await db.get(AcademicSeason, season_id)
    if not season:
        raise HTTPException(404, "Season not found")

    updates = data.model_dump(exclude_unset=True)

    if updates.get("is_default"):
        existing_defaults = (
            await db.execute(
                select(AcademicSeason).where(
                    AcademicSeason.is_default.is_(True),
                    AcademicSeason.id != season_id,
                )
            )
        ).scalars().all()
        for s in existing_defaults:
            s.is_default = False

    for field, value in updates.items():
        setattr(season, field, value)

    await db.flush()
    await db.refresh(season)
    return season


@router.delete("/{season_id}", status_code=204)
async def delete_season(season_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    season = await db.get(AcademicSeason, season_id)
    if not season:
        raise HTTPException(404, "Season not found")
    await db.delete(season)
    await db.flush()
