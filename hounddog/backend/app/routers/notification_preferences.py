"""Public (no auth) endpoints for students to manage notification preferences."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.notification_preference import NotificationPreference
from ..models.permit import Permit
from ..schemas.messaging import NotificationPreferenceRead, NotificationPreferenceUpdate

router = APIRouter()


@router.get("/{token}", response_model=NotificationPreferenceRead)
async def get_preferences(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(NotificationPreference, Permit).join(
            Permit, NotificationPreference.permit_id == Permit.id
        ).where(NotificationPreference.opt_out_token == token)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Preference link not found or expired")

    pref, permit = row
    first_name = permit.name.split()[0] if permit.name else ""

    return NotificationPreferenceRead(
        first_name=first_name,
        phone=permit.phone,
        sms_opt_in=pref.sms_opt_in,
    )


@router.put("/{token}", response_model=NotificationPreferenceRead)
async def update_preferences(
    token: str,
    data: NotificationPreferenceUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(NotificationPreference, Permit).join(
            Permit, NotificationPreference.permit_id == Permit.id
        ).where(NotificationPreference.opt_out_token == token)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(404, "Preference link not found or expired")

    pref, permit = row
    pref.sms_opt_in = data.sms_opt_in
    permit.sms_opt_in = data.sms_opt_in

    if data.phone is not None:
        permit.phone = data.phone

    await db.flush()

    first_name = permit.name.split()[0] if permit.name else ""
    return NotificationPreferenceRead(
        first_name=first_name,
        phone=permit.phone,
        sms_opt_in=pref.sms_opt_in,
    )
