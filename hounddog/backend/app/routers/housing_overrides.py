"""Admin endpoints for managing housing status overrides."""

import logging
import sentry_sdk
import uuid

from fastapi import APIRouter, Depends, HTTPException
from ..utils.safe_router import SafeRouter
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_office, OktaUser, get_current_user
from ..database import get_db
from ..models.housing_override import HousingOverride
from ..models.permit_application import PermitApplication
from ..models.permit_type import PermitType

_logger = logging.getLogger("quarry.housing_overrides")

# Must stay in sync with student_permits.py
_COMMUTER_CODES = {"commuter_undergrad", "commuter_grad", "premium_commuter"}
_RESIDENT_CODES = {
    "north_premium_resident", "south_premium_resident",
    "north_guaranteed_resident", "south_guaranteed_resident",
    "south_standalone", "steel_field_resident",
}

router = SafeRouter(dependencies=[Depends(require_office())])

VALID_STATUSES = {"R", "C", "O"}


class OverrideCreate(BaseModel):
    student_email: str
    student_name: str = ""
    moravian_id: str = ""
    override_status: str
    reason: str = ""


class OverrideUpdate(BaseModel):
    override_status: str | None = None
    reason: str | None = None
    student_name: str | None = None
    moravian_id: str | None = None


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
    email = data.student_email.strip().lower()
    if not email:
        raise HTTPException(400, "student_email is required")

    existing = (
        await db.execute(select(HousingOverride).where(func.lower(HousingOverride.student_email) == email))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, f"Override already exists for {email}. Edit or delete the existing one.")

    try:
        override = HousingOverride(
            moravian_id=data.moravian_id.strip(),
            student_name=data.student_name.strip(),
            student_email=email,
            override_status=data.override_status,
            reason=data.reason.strip(),
            created_by=getattr(user, "email", ""),
        )
        db.add(override)
        await db.flush()
        await db.refresh(override)
    except HTTPException:
        raise
    except Exception as e:
        sentry_sdk.capture_exception(e)
        _logger.error("Failed to create housing override for %s: %s", email, e)
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            raise HTTPException(409, f"Override already exists for {email}. Edit or delete the existing one.")
        raise HTTPException(500, f"Failed to save override: {e}")

    cancelled = await _cancel_conflicting_applications(db, email, data.override_status)
    return {
        "id": str(override.id),
        "student_email": override.student_email,
        "cancelled_applications": cancelled,
    }


@router.put("/{override_id}")
async def update_override(
    override_id: uuid.UUID,
    data: OverrideUpdate,
    db: AsyncSession = Depends(get_db),
):
    override = await db.get(HousingOverride, override_id)
    if not override:
        raise HTTPException(404, "Override not found")
    status_changed = False
    if data.override_status is not None:
        if data.override_status not in VALID_STATUSES:
            raise HTTPException(400, f"override_status must be one of: {', '.join(sorted(VALID_STATUSES))}")
        if data.override_status != override.override_status:
            status_changed = True
        override.override_status = data.override_status
    if data.reason is not None:
        override.reason = data.reason.strip()
    if data.student_name is not None:
        override.student_name = data.student_name.strip()
    if data.moravian_id is not None:
        override.moravian_id = data.moravian_id.strip()

    cancelled = 0
    if status_changed:
        cancelled = await _cancel_conflicting_applications(db, override.student_email, override.override_status)

    return {
        "id": str(override.id),
        "student_email": override.student_email,
        "cancelled_applications": cancelled,
    }


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


async def _cancel_conflicting_applications(
    db: AsyncSession, student_email: str, new_status: str
) -> int:
    """Cancel pending/waitlisted lottery applications that conflict with the new housing status.

    If overriding to Commuter, cancel resident applications.
    If overriding to Resident, cancel commuter applications.
    Returns the count of cancelled applications.
    """
    if new_status == "C":
        conflicting_codes = _RESIDENT_CODES
    elif new_status == "R":
        conflicting_codes = _COMMUTER_CODES
    else:
        return 0

    try:
        # Find permit_type IDs for conflicting codes
        pt_result = await db.execute(
            select(PermitType.id).where(PermitType.code.in_(conflicting_codes))
        )
        conflicting_type_ids = [row[0] for row in pt_result]
        if not conflicting_type_ids:
            return 0

        # Find active applications for this student that match conflicting types
        apps_result = await db.execute(
            select(PermitApplication).where(
                func.lower(PermitApplication.student_email) == student_email.lower(),
                PermitApplication.permit_type_id.in_(conflicting_type_ids),
                PermitApplication.status.in_(["pending", "waitlisted", "selected", "accepted"]),
            )
        )
        apps = apps_result.scalars().all()

        for app in apps:
            old_status = app.status
            app.status = "expired"
            _logger.info(
                "Auto-cancelled %s application %s for %s (was %s, housing override → %s)",
                app.permit_type_id, app.id, student_email, old_status, new_status,
            )

        if apps:
            await db.flush()

        return len(apps)
    except Exception as e:
        sentry_sdk.capture_exception(e)
        _logger.error("Failed to cancel conflicting applications for %s: %s", student_email, e)
        return 0


async def get_housing_override_by_email(email: str, db: AsyncSession) -> str | None:
    """Check if a manual housing override exists by email. Returns status code or None."""
    if not email:
        return None
    row = (
        await db.execute(
            select(HousingOverride.override_status)
            .where(HousingOverride.student_email == email.lower())
        )
    ).scalar_one_or_none()
    return row


async def get_housing_override(moravian_id: str, db: AsyncSession) -> str | None:
    """Check if a manual housing override exists by moravian_id. Returns status code or None."""
    if not moravian_id:
        return None
    row = (
        await db.execute(
            select(HousingOverride.override_status)
            .where(HousingOverride.moravian_id == moravian_id, HousingOverride.moravian_id != "")
        )
    ).scalar_one_or_none()
    return row
