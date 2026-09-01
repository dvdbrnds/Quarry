"""Admin endpoints for managing housing status overrides."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_office, OktaUser, get_current_user
from ..database import get_db
from ..models.housing_override import HousingOverride

router = APIRouter(dependencies=[Depends(require_office())])

VALID_STATUSES = {"R", "C", "O"}


class OverrideCreate(BaseModel):
    moravian_id: str
    student_name: str = ""
    student_email: str = ""
    override_status: str
    reason: str = ""


class OverrideUpdate(BaseModel):
    override_status: str | None = None
    reason: str | None = None
    student_name: str | None = None
    student_email: str | None = None


@router.get("")
async def list_overrides(db: AsyncSession = Depends(get_db)):
    rows = (
        await db.execute(
            select(HousingOverride).order_by(HousingOverride.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(o.id),
            "moravian_id": o.moravian_id,
            "student_name": o.student_name,
            "student_email": o.student_email,
            "override_status": o.override_status,
            "override_label": {"R": "Resident", "C": "Commuter", "O": "Off Campus"}.get(o.override_status, o.override_status),
            "reason": o.reason,
            "created_by": o.created_by,
            "created_at": o.created_at.isoformat() if o.created_at else "",
        }
        for o in rows
    ]


@router.post("", status_code=201)
async def create_override(
    data: OverrideCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    if data.override_status not in VALID_STATUSES:
        raise HTTPException(400, f"override_status must be one of: {', '.join(sorted(VALID_STATUSES))}")
    mid = data.moravian_id.strip()
    if not mid:
        raise HTTPException(400, "moravian_id is required")

    existing = (
        await db.execute(select(HousingOverride).where(HousingOverride.moravian_id == mid))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Override already exists for {mid}. Edit or delete the existing one.")

    override = HousingOverride(
        moravian_id=mid,
        student_name=data.student_name.strip(),
        student_email=data.student_email.strip(),
        override_status=data.override_status,
        reason=data.reason.strip(),
        created_by=getattr(user, "email", ""),
    )
    db.add(override)
    await db.flush()
    await db.refresh(override)
    return {"id": str(override.id), "moravian_id": override.moravian_id}


@router.put("/{override_id}")
async def update_override(
    override_id: uuid.UUID,
    data: OverrideUpdate,
    db: AsyncSession = Depends(get_db),
):
    override = await db.get(HousingOverride, override_id)
    if not override:
        raise HTTPException(404, "Override not found")
    if data.override_status is not None:
        if data.override_status not in VALID_STATUSES:
            raise HTTPException(400, f"override_status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        override.override_status = data.override_status
    if data.reason is not None:
        override.reason = data.reason.strip()
    if data.student_name is not None:
        override.student_name = data.student_name.strip()
    if data.student_email is not None:
        override.student_email = data.student_email.strip()
    return {"id": str(override.id), "moravian_id": override.moravian_id}


@router.delete("/{override_id}")
async def delete_override(
    override_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    override = await db.get(HousingOverride, override_id)
    if not override:
        raise HTTPException(404, "Override not found")
    await db.delete(override)
    return {"deleted": True}


async def get_housing_override(moravian_id: str, db: AsyncSession) -> str | None:
    """Check if a manual housing override exists. Returns status code or None."""
    if not moravian_id:
        return None
    row = (
        await db.execute(
            select(HousingOverride.override_status)
            .where(HousingOverride.moravian_id == moravian_id)
        )
    ).scalar_one_or_none()
    return row
