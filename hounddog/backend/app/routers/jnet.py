"""
JNET lookup endpoints.

POST /api/jnet/plate-lookup — plate + registered owner lookup
GET  /api/jnet/status        — JNET connectivity and user auth status
"""

import re
import uuid

from fastapi import Depends, HTTPException, Request, Response
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.safe_router import SafeRouter
from ..auth.okta import OktaUser, get_current_user
from ..database import get_db
from ..models.jnet_authorized_user import JNETAuthorizedUser
from ..models.cjis_audit_log import CJISAuditLog
from ..services.jnet.client import JNETClient
from ..services.jnet.config import jnet_settings
from ..services.jnet.middleware import require_jnet_officer
from ..services.jnet.audit import log_jnet_query
from ..services.jnet.anomaly import check_query_anomalies
from ..services.jnet.models import JNETError

router = SafeRouter(prefix="/api/jnet", tags=["JNET"])

PLATE_REGEX = re.compile(r"^[A-Z0-9]{1,8}$")


class PlateLookupRequest(BaseModel):
    plate_number: str
    state: str = "PA"

    @field_validator("plate_number", mode="before")
    @classmethod
    def normalize_plate(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-]", "", v).upper()
        if not PLATE_REGEX.match(cleaned):
            raise ValueError(
                "Invalid plate number. Must be 1-8 alphanumeric characters."
            )
        return cleaned

    @field_validator("state", mode="before")
    @classmethod
    def normalize_state(cls, v: str) -> str:
        return v.upper().strip()[:2]


@router.post("/plate-lookup")
async def plate_lookup(
    body: PlateLookupRequest,
    request: Request,
    response: Response,
    jnet_user: JNETAuthorizedUser = Depends(require_jnet_officer),
    db: AsyncSession = Depends(get_db),
):
    """
    Look up a license plate via JNET.

    Requires jnet_officer role + all CJIS prerequisites.
    CJI data is returned in the response body and NEVER persisted.
    """
    # CJI must never be cached
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

    client_ip = request.client.host if request.client else "unknown"
    device_id = request.headers.get("X-BirdDog-Device-Id")

    client = JNETClient()
    success = False
    error_msg = None
    response_time_ms = 0

    try:
        result, response_time_ms = await client.plate_lookup(
            plate_number=body.plate_number,
            state=body.state,
        )
        success = True
    except JNETError as exc:
        error_msg = exc.message
        raise HTTPException(status_code=502, detail="JNET lookup failed. Please try again.")
    finally:
        audit_entry = await log_jnet_query(
            user_id=jnet_user.id,
            user_email=jnet_user.email,
            user_full_name=jnet_user.full_name,
            action="plate_lookup",
            query_plate=body.plate_number,
            query_state=body.state,
            ori=jnet_settings.jnet_ori,
            source_ip=client_ip,
            device_id=device_id,
            success=success,
            error_message=error_msg,
            response_time_ms=response_time_ms,
        )

        # Fire-and-forget anomaly checks
        if audit_entry:
            await check_query_anomalies(
                audit_log_id=audit_entry.id,
                user_id=jnet_user.id,
                user_email=jnet_user.email,
                query_plate=body.plate_number,
                source_ip=client_ip,
            )

    return result.model_dump()


@router.get("/status")
async def jnet_status(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return JNET integration status and current user's authorization.
    No CJI in this response.
    """
    enabled = jnet_settings.jnet_enabled

    # Check if user is authorized
    authorized = False
    prerequisites_met = False
    role = None
    missing_prerequisites: list[str] = []

    if enabled:
        result = await db.execute(
            select(JNETAuthorizedUser).where(
                JNETAuthorizedUser.okta_sub == user.sub
            )
        )
        jnet_user = result.scalars().first()

        if jnet_user and jnet_user.jnet_authorized:
            authorized = True
            role = jnet_user.role

            if jnet_user.jnet_background_check_date is None:
                missing_prerequisites.append("background_check")
            if jnet_user.jnet_training_completed_at is None:
                missing_prerequisites.append("training")
            elif jnet_user.jnet_training_completed_at.replace(
                tzinfo=None
            ) < (
                __import__("datetime").datetime.utcnow()
                - __import__("datetime").timedelta(
                    days=jnet_settings.jnet_training_validity_days
                )
            ):
                missing_prerequisites.append("training_expired")

            prerequisites_met = len(missing_prerequisites) == 0

    # Last successful query time (no CJI)
    last_success = None
    if enabled:
        result = await db.execute(
            select(func.max(CJISAuditLog.timestamp)).where(
                CJISAuditLog.success == True  # noqa: E712
            )
        )
        last_success_dt = result.scalar()
        if last_success_dt:
            last_success = last_success_dt.isoformat()

    return {
        "enabled": enabled,
        "authorized": authorized,
        "role": role,
        "prerequisites_met": prerequisites_met,
        "missing_prerequisites": missing_prerequisites,
        "last_successful_query": last_success,
    }
