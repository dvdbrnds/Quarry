import logging
import sentry_sdk

from fastapi import APIRouter, Depends, Request
from ..utils.safe_router import SafeRouter
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, _fetch_userinfo, _extract_token
from ..config import settings
from ..database import get_db, async_session
from ..models.audit_log import AuditLog
from ..models.jnet_authorized_user import JNETAuthorizedUser
from ..services.sis_student_data import lookup_student_parking_data
from ..services.jnet.dependencies import get_effective_jnet_enabled
from ..services.jnet.config import jnet_settings

logger = logging.getLogger("quarry.audit")

router = SafeRouter()


@router.get("/config/public")
async def public_config():
    """Non-sensitive config the frontend needs at runtime (no rebuild required)."""
    return {
        "okta_domain": settings.okta_domain,
        "okta_client_id": settings.okta_client_id,
        "auth_enabled": bool(settings.okta_domain),
        "google_maps_api_key": settings.google_maps_api_key,
        "campus_lat": settings.campus_lat,
        "campus_lng": settings.campus_lng,
        "public_map_requires_auth": settings.public_map_requires_auth,
        "school_name": settings.school_name or settings.brand_name,
    }


async def _write_auth_event(user: OktaUser, action: str, summary: str,
                            ip: str | None = None):
    try:
        async with async_session() as session:
            async with session.begin():
                session.add(AuditLog(
                    user_email=user.email,
                    user_sub=user.sub,
                    action=action,
                    resource_type="auth",
                    endpoint="/api/auth/me",
                    summary=summary,
                    response_status=200,
                    ip_address=ip,
                ))
    except Exception as e:
        sentry_sdk.capture_exception(e)
        logger.warning("Auth audit write failed: %s", e)


def _extract_moravian_id(user: OktaUser) -> str | None:
    """Extract Moravian numeric ID from Okta profile fields."""
    profile = getattr(user, "profile", None) or {}
    for field in ("altId", "studentId", "employeeNumber", "moravianId"):
        val = profile.get(field)
        if val:
            return str(val).split("@")[0].strip()
    return None


@router.get("/me")
async def me(
    request: Request,
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ip = request.client.host if request.client else None

    role = user.role

    # For non-office users, check Jenzabar SIS for authoritative employment status.
    # Rule: current students who are also employees default to student.
    # A class_year alone doesn't mean current student -- alumni who become
    # faculty still have their old class_year in Okta (e.g. class of 2007).
    # Do not overwrite admin or operator (parking office) roles.
    if role not in ("admin", "operator"):
        from datetime import datetime
        current_year = datetime.now().year
        has_current_class_year = (
            bool(user.class_year) and user.class_year >= current_year
        )

        moravian_id = _extract_moravian_id(user)
        if moravian_id:
            try:
                sis = await lookup_student_parking_data(moravian_id)
                if sis:
                    is_current_student = has_current_class_year or sis.housing_status in ("R", "C")
                    if is_current_student:
                        role = "student"
                    elif sis.employee:
                        role = "staff"
            except Exception as e:
                sentry_sdk.capture_exception(e)
                logger.debug("SIS lookup failed during auth for %s", user.email)

    await _write_auth_event(
        user, "LOGIN",
        f"User signed in: {user.email} (role: {role})",
        ip,
    )

    # JNET status: null for non-authorized users (stealth)
    jnet_status = None
    try:
        jnet_effective = await get_effective_jnet_enabled(db)
        if jnet_effective:
            from sqlalchemy import select
            result = await db.execute(
                select(JNETAuthorizedUser).where(
                    JNETAuthorizedUser.okta_sub == user.sub
                )
            )
            jnet_user = result.scalars().first()
            if jnet_user and jnet_user.jnet_authorized:
                from datetime import datetime as _dt, timedelta, timezone
                bg_valid = jnet_user.jnet_background_check_date is not None
                training_valid = False
                if jnet_user.jnet_training_completed_at is not None:
                    cutoff = _dt.now(timezone.utc) - timedelta(
                        days=jnet_settings.jnet_training_validity_days
                    )
                    t = jnet_user.jnet_training_completed_at
                    if t.tzinfo is None:
                        t = t.replace(tzinfo=timezone.utc)
                    training_valid = t >= cutoff

                # Compute system_status
                from ..routers.jnet_settings import _compute_system_status
                from ..models.cjis_audit_log import CJISAuditLog
                from ..models.system_setting import SystemSetting
                from sqlalchemy import func as sa_func
                db_setting = await db.execute(
                    select(SystemSetting.value).where(
                        SystemSetting.key == "jnet_system_enabled"
                    )
                )
                db_enabled = db_setting.scalar() == "true"
                has_live = False
                if jnet_settings.jnet_base_url:
                    lq = await db.execute(
                        select(sa_func.count()).where(
                            CJISAuditLog.success == True  # noqa: E712
                        )
                    )
                    has_live = (lq.scalar() or 0) > 0
                sys_status = _compute_system_status(
                    env_enabled=jnet_settings.jnet_enabled,
                    db_enabled=db_enabled,
                    base_url=jnet_settings.jnet_base_url,
                    cert_path=jnet_settings.jnet_client_cert_path,
                    ori=jnet_settings.jnet_ori,
                    has_live_query=has_live,
                )

                jnet_status = {
                    "role": jnet_user.role,
                    "authorized": True,
                    "background_check_valid": bg_valid,
                    "training_valid": training_valid,
                    "system_status": sys_status,
                }
    except Exception:
        pass

    return {
        "sub": user.sub,
        "email": user.email,
        "role": role,
        "groups": user.groups,
        "jnet_status": jnet_status,
    }


@router.get("/profile")
async def profile(user: OktaUser = Depends(get_current_user)):
    """Return enriched Okta profile data for form pre-fill."""
    return {
        "sub": user.sub,
        "email": user.email,
        "given_name": user.given_name,
        "family_name": user.family_name,
        "display_name": user.display_name,
        "class_year": user.class_year,
        "groups": user.groups,
        "role": user.role,
    }


@router.get("/okta-debug")
async def okta_debug(request: Request, user: OktaUser = Depends(get_current_user)):
    """Admin-only: show full Okta userinfo payload to discover available attributes."""
    if not user.is_admin:
        return {"error": "Admin only"}
    token = _extract_token(request)
    raw_userinfo = await _fetch_userinfo(token) if token else {}
    return {
        "token_profile": user.profile,
        "userinfo": raw_userinfo,
        "groups": user.groups,
    }


@router.post("/logout")
async def logout_event(request: Request,
                       user: OktaUser = Depends(get_current_user)):
    ip = request.client.host if request.client else None
    await _write_auth_event(
        user, "LOGOUT",
        f"User signed out: {user.email}",
        ip,
    )
    return {"ok": True}
