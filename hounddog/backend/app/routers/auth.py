from fastapi import APIRouter, Depends

from ..auth.okta import OktaUser, get_current_user
from ..config import settings

router = APIRouter()


@router.get("/config/public")
async def public_config():
    """Non-sensitive config the frontend needs at runtime (no rebuild required)."""
    return {
        "okta_domain": settings.okta_domain,
        "okta_client_id": settings.okta_client_id,
        "auth_enabled": bool(settings.okta_domain),
    }


@router.get("/me")
async def me(user: OktaUser = Depends(get_current_user)):
    return {
        "sub": user.sub,
        "email": user.email,
        "role": user.role,
        "groups": user.groups,
    }
