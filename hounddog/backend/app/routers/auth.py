import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, _fetch_userinfo, _extract_token
from ..config import settings
from ..database import get_db, async_session
from ..models.audit_log import AuditLog
from ..services.sis_student_data import lookup_student_parking_data

logger = logging.getLogger("quarry.audit")

router = APIRouter()


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
async def me(request: Request, user: OktaUser = Depends(get_current_user)):
    ip = request.client.host if request.client else None

    role = user.role

    # For non-admin users, check Jenzabar SIS for authoritative employment status.
    # Rule: current students who are also employees default to student.
    # A class_year alone doesn't mean current student -- alumni who become
    # faculty still have their old class_year in Okta (e.g. class of 2007).
    if role not in ("admin",):
        from datetime import datetime
        current_year = datetime.now().year
        # class_year within 6 years of now is a reasonable current-student window
        has_current_class_year = (
            bool(user.class_year) and user.class_year >= current_year - 1
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
            except Exception:
                logger.debug("SIS lookup failed during auth for %s", user.email)

    await _write_auth_event(
        user, "LOGIN",
        f"User signed in: {user.email} (role: {role})",
        ip,
    )
    return {
        "sub": user.sub,
        "email": user.email,
        "role": role,
        "groups": user.groups,
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
