"""
JNET system settings endpoint.

GET  /api/settings/jnet  — view JNET system configuration status
PUT  /api/settings/jnet  — toggle JNET system on/off

Both require cjis_admin role; non-admin users get 404 (stealth).
"""

from datetime import datetime, timezone

from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.safe_router import SafeRouter
from ..database import get_db
from ..models.jnet_authorized_user import JNETAuthorizedUser
from ..models.cjis_audit_log import CJISAuditLog
from ..models.system_setting import SystemSetting
from ..services.jnet.config import jnet_settings
from ..services.jnet.dependencies import require_cjis_admin_visible
from ..services.jnet.audit import log_jnet_query
from ..services.jnet.middleware import _rate_limit_windows

router = SafeRouter(prefix="/api/settings/jnet", tags=["JNET Settings"])


def _compute_system_status(
    env_enabled: bool,
    db_enabled: bool,
    base_url: str,
    cert_path: str,
    ori: str,
    has_live_query: bool,
) -> str:
    """Compute the overall JNET system status string."""
    if not env_enabled or not db_enabled:
        return "disabled"
    if not base_url:
        return "mock_mode"
    if not cert_path or not ori:
        return "misconfigured"
    if has_live_query:
        return "live"
    return "ready"


@router.get("")
async def get_jnet_settings(
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """View JNET system configuration status."""
    # DB toggle
    result = await db.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == "jnet_system_enabled"
        )
    )
    db_enabled = result.scalar() == "true"

    # Authorized user count
    user_count = (
        await db.execute(
            select(func.count()).where(
                JNETAuthorizedUser.jnet_authorized == True  # noqa: E712
            )
        )
    ).scalar() or 0

    # Check if at least one real (non-mock) successful query exists
    has_live_query = False
    if jnet_settings.jnet_base_url:
        result = await db.execute(
            select(func.count()).where(
                CJISAuditLog.success == True  # noqa: E712
            )
        )
        has_live_query = (result.scalar() or 0) > 0

    env_enabled = jnet_settings.jnet_enabled
    status = _compute_system_status(
        env_enabled=env_enabled,
        db_enabled=db_enabled,
        base_url=jnet_settings.jnet_base_url,
        cert_path=jnet_settings.jnet_client_cert_path,
        ori=jnet_settings.jnet_ori,
        has_live_query=has_live_query,
    )

    return {
        "jnet_enabled": db_enabled,
        "env_enabled": env_enabled,
        "mock_mode": env_enabled and not jnet_settings.jnet_base_url,
        "jnet_base_url_configured": bool(jnet_settings.jnet_base_url),
        "client_cert_configured": bool(jnet_settings.jnet_client_cert_path),
        "ori_configured": bool(jnet_settings.jnet_ori),
        "authorized_user_count": user_count,
        "status": status,
    }


class ToggleJNETBody(BaseModel):
    jnet_enabled: bool


@router.put("")
async def update_jnet_settings(
    body: ToggleJNETBody,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Toggle the JNET system on or off (database-level flag)."""
    new_value = "true" if body.jnet_enabled else "false"

    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "jnet_system_enabled")
    )
    setting = result.scalars().first()
    if setting:
        setting.value = new_value
        setting.updated_by = jnet_user.email
        setting.updated_at = datetime.now(timezone.utc)
    else:
        db.add(SystemSetting(
            key="jnet_system_enabled",
            value=new_value,
            updated_by=jnet_user.email,
        ))

    # If toggling OFF, clear in-memory rate limit windows
    if not body.jnet_enabled:
        _rate_limit_windows.clear()

    # Log the toggle to CJIS audit
    await log_jnet_query(
        user_id=jnet_user.id,
        user_email=jnet_user.email,
        user_full_name=jnet_user.full_name,
        action="jnet_system_toggle",
        query_plate=None,
        query_state=None,
        ori=jnet_settings.jnet_ori,
        source_ip="admin",
        device_id=None,
        success=True,
        error_message=f"JNET system {'enabled' if body.jnet_enabled else 'disabled'}",
        response_time_ms=0,
    )

    return {"status": "ok", "jnet_enabled": body.jnet_enabled}
