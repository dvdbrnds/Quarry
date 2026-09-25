"""
CJIS access control middleware for JNET endpoints.

Dependency chain:
  1. get_current_user (existing Okta JWT auth)
  2. resolve JNET authorization from jnet_authorized_users table
  3. verify CJIS prerequisites (background check, training, session timeout)
  4. rate limit

Fail closed: if any check fails, deny the JNET lookup.
"""

import time
import collections
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.okta import OktaUser, get_current_user
from ...database import get_db
from ...models.jnet_authorized_user import JNETAuthorizedUser
from .config import jnet_settings

# In-memory sliding-window rate limiter: {okta_sub: [timestamps]}
_rate_limit_windows: dict[str, collections.deque] = {}


def _check_jnet_enabled() -> None:
    """Raise 404 if JNET integration is disabled (stealth)."""
    if not jnet_settings.jnet_enabled:
        raise HTTPException(status_code=404, detail="Not found")


async def _resolve_jnet_user(
    okta_user: OktaUser, db: AsyncSession
) -> JNETAuthorizedUser:
    """Look up JNET authorization record for the authenticated Okta user."""
    result = await db.execute(
        select(JNETAuthorizedUser).where(
            JNETAuthorizedUser.okta_sub == okta_user.sub
        )
    )
    jnet_user = result.scalars().first()

    if not jnet_user:
        raise HTTPException(status_code=404, detail="Not found")

    if not jnet_user.jnet_authorized:
        raise HTTPException(status_code=404, detail="Not found")

    return jnet_user


def _check_background_check(jnet_user: JNETAuthorizedUser) -> None:
    """CJIS requires fingerprint-based background check."""
    if jnet_user.jnet_background_check_date is None:
        raise HTTPException(
            status_code=403,
            detail="CJIS prerequisite missing: fingerprint-based background check not on file.",
        )


def _check_training(jnet_user: JNETAuthorizedUser) -> None:
    """CJIS requires security awareness training within the last 365 days."""
    if jnet_user.jnet_training_completed_at is None:
        raise HTTPException(
            status_code=403,
            detail="CJIS prerequisite missing: security awareness training not completed.",
        )

    validity_days = jnet_settings.jnet_training_validity_days
    cutoff = datetime.now(timezone.utc) - timedelta(days=validity_days)

    training_date = jnet_user.jnet_training_completed_at
    if training_date.tzinfo is None:
        training_date = training_date.replace(tzinfo=timezone.utc)

    if training_date < cutoff:
        raise HTTPException(
            status_code=403,
            detail=f"CJIS prerequisite expired: security awareness training is older than {validity_days} days.",
        )


def _check_session_timeout(jnet_user: JNETAuthorizedUser) -> None:
    """
    CJIS requires 30-minute inactivity timeout for JNET sessions.
    Measured from last JNET activity, not from login.
    """
    if jnet_user.jnet_last_activity is None:
        # First JNET query of the session — allowed
        return

    timeout_minutes = jnet_settings.jnet_session_timeout_minutes
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)

    last_activity = jnet_user.jnet_last_activity
    if last_activity.tzinfo is None:
        last_activity = last_activity.replace(tzinfo=timezone.utc)

    if last_activity < cutoff:
        raise HTTPException(
            status_code=401,
            detail="cjis_session_expired",
            headers={"X-CJIS-Session-Expired": "true"},
        )


def _check_rate_limit(okta_sub: str) -> None:
    """Enforce per-user rate limit (sliding window, in-memory)."""
    max_per_minute = jnet_settings.jnet_max_queries_per_minute
    now = time.monotonic()
    window = _rate_limit_windows.setdefault(okta_sub, collections.deque())

    # Evict entries older than 60 seconds
    while window and window[0] < now - 60:
        window.popleft()

    if len(window) >= max_per_minute:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: maximum {max_per_minute} JNET queries per minute.",
        )

    window.append(now)


async def enforce_cjis_prerequisites(
    jnet_user: JNETAuthorizedUser,
    okta_user: OktaUser,
    db: AsyncSession,
) -> None:
    """
    Enforce CJIS prerequisites AFTER visibility gate has passed.

    These checks return 403 with actionable details because the user
    is already known to be JNET-authorized.
    cjis_admin can also perform lookups (for testing/verification).
    """
    if jnet_user.role not in ("jnet_officer", "cjis_admin"):
        raise HTTPException(
            status_code=403,
            detail="JNET lookups require jnet_officer or cjis_admin role.",
        )

    _check_background_check(jnet_user)
    _check_training(jnet_user)
    _check_session_timeout(jnet_user)
    _check_rate_limit(okta_user.sub)

    # Update last activity timestamp
    await db.execute(
        update(JNETAuthorizedUser)
        .where(JNETAuthorizedUser.id == jnet_user.id)
        .values(jnet_last_activity=datetime.now(timezone.utc))
    )


async def require_jnet_officer(
    request: Request,
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JNETAuthorizedUser:
    """
    FastAPI dependency for JNET lookup endpoints.

    Checks: JNET enabled → authorized → role=jnet_officer →
    background check → training → session timeout → rate limit.
    """
    _check_jnet_enabled()

    jnet_user = await _resolve_jnet_user(user, db)

    if jnet_user.role != "jnet_officer":
        raise HTTPException(
            status_code=403,
            detail="JNET lookups require jnet_officer role.",
        )

    _check_background_check(jnet_user)
    _check_training(jnet_user)
    _check_session_timeout(jnet_user)
    _check_rate_limit(user.sub)

    # Update last activity timestamp
    await db.execute(
        update(JNETAuthorizedUser)
        .where(JNETAuthorizedUser.id == jnet_user.id)
        .values(jnet_last_activity=datetime.now(timezone.utc))
    )

    # Stash on request for downstream use
    request.state.jnet_user = jnet_user
    request.state.okta_user = user

    return jnet_user


async def require_cjis_admin(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JNETAuthorizedUser:
    """
    FastAPI dependency for CJIS administration endpoints.

    Requires cjis_admin role in jnet_authorized_users.
    """
    _check_jnet_enabled()

    result = await db.execute(
        select(JNETAuthorizedUser).where(
            JNETAuthorizedUser.okta_sub == user.sub
        )
    )
    jnet_user = result.scalars().first()

    if not jnet_user or jnet_user.role != "cjis_admin":
        raise HTTPException(status_code=404, detail="Not found")

    if not jnet_user.jnet_authorized:
        raise HTTPException(status_code=404, detail="Not found")

    return jnet_user
