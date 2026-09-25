"""
Stealth feature-gate dependencies for JNET/CJIS endpoints.

Philosophy: if a user is not JNET-authorized, the feature does not exist.
All denials return 404 ("Not found") — identical to a nonexistent route.
No mention of JNET, CJIS, or authorization in the error response.

Only after a user passes the visibility gate do downstream checks
(background check, training, session timeout) return 403 with
actionable details, because the user is known to be JNET-authorized.
"""

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.okta import OktaUser, get_current_user
from ...database import get_db
from ...models.jnet_authorized_user import JNETAuthorizedUser
from ...models.system_setting import SystemSetting
from .config import jnet_settings

_STEALTH_404 = HTTPException(status_code=404, detail="Not found")


async def get_effective_jnet_enabled(db: AsyncSession) -> bool:
    """
    Two-key check: env JNET_ENABLED must be true AND the database
    jnet_system_enabled setting must be 'true'.
    """
    if not jnet_settings.jnet_enabled:
        return False

    result = await db.execute(
        select(SystemSetting.value).where(
            SystemSetting.key == "jnet_system_enabled"
        )
    )
    db_value = result.scalar()
    return db_value == "true"


async def require_jnet_visible(
    request: Request,
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JNETAuthorizedUser:
    """
    Visibility gate for JNET officer endpoints.

    Returns 404 if JNET is not effectively enabled or the user is not
    an authorized JNET user.  The feature is invisible, not locked.
    """
    if not await get_effective_jnet_enabled(db):
        raise _STEALTH_404

    result = await db.execute(
        select(JNETAuthorizedUser).where(
            JNETAuthorizedUser.okta_sub == user.sub
        )
    )
    jnet_user = result.scalars().first()

    if not jnet_user or not jnet_user.jnet_authorized:
        raise _STEALTH_404

    # Stash for downstream middleware
    request.state.jnet_user = jnet_user
    request.state.okta_user = user

    return jnet_user


async def require_cjis_admin_visible(
    request: Request,
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JNETAuthorizedUser:
    """
    Visibility gate for CJIS admin endpoints.

    Same stealth 404 behavior, plus requires cjis_admin role.
    """
    if not await get_effective_jnet_enabled(db):
        raise _STEALTH_404

    result = await db.execute(
        select(JNETAuthorizedUser).where(
            JNETAuthorizedUser.okta_sub == user.sub
        )
    )
    jnet_user = result.scalars().first()

    if not jnet_user or not jnet_user.jnet_authorized:
        raise _STEALTH_404

    if jnet_user.role != "cjis_admin":
        raise _STEALTH_404

    request.state.jnet_user = jnet_user
    request.state.okta_user = user

    return jnet_user
