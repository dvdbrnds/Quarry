import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, require_role
from ..config import settings
from ..database import get_db
from ..models.device import Device
from ..schemas.device import DeviceCreate, DeviceRead

router = APIRouter(dependencies=[Depends(require_role("admin", "supervisor"))])


class DeviceReadWithPairing(DeviceRead):
    pairing_url: str = ""
    pairing_payload: dict = {}


@router.get("", response_model=list[DeviceRead])
async def list_devices(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Device).order_by(Device.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=DeviceReadWithPairing, status_code=201)
async def create_device(data: DeviceCreate, db: AsyncSession = Depends(get_db)):
    device = Device(name=data.name, device_type=data.device_type)
    db.add(device)
    await db.flush()
    await db.refresh(device)

    pairing_payload = {
        "url": settings.public_url,
        "key": device.api_key,
        "name": settings.school_name,
    }

    return DeviceReadWithPairing(
        id=device.id,
        name=device.name,
        api_key=device.api_key,
        device_type=device.device_type,
        last_seen=device.last_seen,
        created_at=device.created_at,
        pairing_url=settings.public_url,
        pairing_payload=pairing_payload,
    )


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    device = await db.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    await db.delete(device)
    await db.flush()
