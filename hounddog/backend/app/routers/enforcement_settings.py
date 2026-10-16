from fastapi import APIRouter, Depends, HTTPException
from ..utils.safe_router import SafeRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings as app_settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..schemas.enforcement_settings import EnforcementSettingsRead, EnforcementSettingsUpdate

router = SafeRouter(dependencies=[Depends(get_current_user)])


async def _get_or_create_settings(db: AsyncSession) -> EnforcementSettings:
    result = await db.execute(select(EnforcementSettings).where(EnforcementSettings.id == 1))
    settings = result.scalar()
    if not settings:
        settings = EnforcementSettings(id=1)
        db.add(settings)
        await db.flush()
        await db.refresh(settings)
    return settings


def _read(settings: EnforcementSettings) -> EnforcementSettingsRead:
    out = EnforcementSettingsRead.model_validate(settings)
    out.barnacle_env_enabled = app_settings.barnacle_enabled
    return out


@router.get("", response_model=EnforcementSettingsRead)
async def get_enforcement_settings(db: AsyncSession = Depends(get_db)):
    return _read(await _get_or_create_settings(db))


@router.put("", response_model=EnforcementSettingsRead)
async def update_enforcement_settings(
    data: EnforcementSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    settings = await _get_or_create_settings(db)

    changes = data.model_dump(exclude_unset=True)
    before = {k: getattr(settings, k) for k in changes}
    for field, value in changes.items():
        setattr(settings, field, value)

    if settings.policy_reminder_day >= settings.policy_late_fee_1_day:
        raise HTTPException(400, "The reminder day must come before the first late fee day")
    if settings.policy_late_fee_1_day >= settings.policy_late_fee_2_day:
        raise HTTPException(400, "The first late fee day must come before the second")
    if settings.policy_due_day >= settings.policy_late_fee_1_day:
        raise HTTPException(400, "The due day must come before the first late fee day")
    if (settings.policy_effective_date and settings.legacy_resolution_deadline
            and settings.legacy_resolution_deadline < settings.policy_effective_date):
        raise HTTPException(400, "The legacy resolution deadline can't be before the effective date")

    policy_keys = {k for k in changes if k.startswith(("policy_", "late_fee", "legacy_", "barnacle_", "denied_", "owner_notification", "removal_phone"))}
    if policy_keys:
        from ..services.citation_policy.service import record_policy_event
        await record_policy_event(
            db, user.email, "enforcement_settings", "1",
            f"Citation policy settings changed: {', '.join(sorted(policy_keys))}",
            {k: {"from": str(before[k]), "to": str(changes[k])} for k in policy_keys},
        )

    settings.updated_by = user.email
    await db.flush()
    await db.refresh(settings)
    return _read(settings)
