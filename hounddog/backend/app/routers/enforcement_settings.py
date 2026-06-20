from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..schemas.enforcement_settings import EnforcementSettingsRead, EnforcementSettingsUpdate

router = APIRouter(dependencies=[Depends(get_current_user)])


async def _get_or_create_settings(db: AsyncSession) -> EnforcementSettings:
    result = await db.execute(select(EnforcementSettings).where(EnforcementSettings.id == 1))
    settings = result.scalar()
    if not settings:
        settings = EnforcementSettings(id=1)
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


@router.get("", response_model=EnforcementSettingsRead)
async def get_enforcement_settings(db: AsyncSession = Depends(get_db)):
    return await _get_or_create_settings(db)


@router.put("", response_model=EnforcementSettingsRead)
async def update_enforcement_settings(
    data: EnforcementSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    settings = await _get_or_create_settings(db)

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)

    settings.updated_by = user.email
    await db.flush()
    await db.refresh(settings)
    return settings
