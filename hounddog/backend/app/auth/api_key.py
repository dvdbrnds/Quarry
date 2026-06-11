from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.device import Device

api_key_header = APIKeyHeader(name="Authorization", auto_error=False)


async def get_device(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Device:
    if not api_key:
        raise HTTPException(status_code=401, detail="Missing API key")

    token = api_key.removeprefix("Bearer ").strip()
    result = await db.execute(select(Device).where(Device.api_key == token))
    device = result.scalar_one_or_none()

    if device is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    device.last_seen = datetime.now(timezone.utc)
    return device


async def optional_device(
    api_key: str | None = Security(api_key_header),
    db: AsyncSession = Depends(get_db),
) -> Device | None:
    if not api_key:
        return None
    try:
        return await get_device(api_key, db)
    except HTTPException:
        return None
