import logging

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user
from ..config import settings
from ..database import get_db, async_session
from ..models.audit_log import AuditLog

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


@router.get("/me")
async def me(request: Request, user: OktaUser = Depends(get_current_user)):
    ip = request.client.host if request.client else None
    await _write_auth_event(
        user, "LOGIN",
        f"User signed in: {user.email} (role: {user.role})",
        ip,
    )
    return {
        "sub": user.sub,
        "email": user.email,
        "role": user.role,
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
