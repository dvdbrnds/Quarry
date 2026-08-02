"""Okta OIDC token verification for the dashboard."""

import logging
from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
import httpx

from ..config import settings

log = logging.getLogger(__name__)

_jwks_cache: dict | None = None


async def _get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    if not settings.okta_domain:
        return {}
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"https://{settings.okta_domain}/oauth2/default/v1/keys")
        resp.raise_for_status()
        _jwks_cache = resp.json()
        return _jwks_cache


async def _fetch_userinfo(access_token: str) -> dict:
    """Fetch the full userinfo payload from Okta's /userinfo endpoint."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{settings.okta_domain}/oauth2/default/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                return resp.json()
            log.warning("Okta userinfo returned status %s", resp.status_code)
    except Exception as exc:
        log.warning("Failed to fetch Okta userinfo: %s", exc)
    return {}


async def _fetch_userinfo_groups(access_token: str) -> list[str]:
    """Fetch groups from Okta's /userinfo endpoint when the access token
    doesn't contain the groups claim (common default configuration)."""
    info = await _fetch_userinfo(access_token)
    return info.get(settings.okta_claim, [])


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("access_token")


# Okta groups that identify faculty/staff for employee parking (not students)
FACULTY_STAFF_OKTA_GROUPS = frozenset({
    "_Bethlehem - All - Faculty",
    "_Bethlehem - All - Staff",
    "_MU - Faculty, Adjunct",
})


class OktaUser:
    def __init__(
        self,
        sub: str,
        email: str,
        groups: list[str],
        given_name: str = "",
        family_name: str = "",
        display_name: str = "",
        class_year: int | None = None,
        profile: dict | None = None,
    ):
        self.sub = sub
        self.email = email
        self.groups = groups
        self.given_name = given_name
        self.family_name = family_name
        self.display_name = display_name or f"{given_name} {family_name}".strip()
        self.class_year = class_year
        self.profile = profile or {}

    @property
    def is_admin(self) -> bool:
        return settings.admin_okta_groups in self.groups

    @property
    def is_staff(self) -> bool:
        """True for Quarry staff/admin or Moravian faculty/staff Okta groups."""
        if self.is_admin or settings.staff_okta_groups in self.groups:
            return True
        return bool(set(self.groups) & FACULTY_STAFF_OKTA_GROUPS)

    @property
    def role(self) -> str:
        if self.is_admin:
            return "admin"
        if self.is_staff:
            return "staff"
        return "none"

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


async def verify_token_string(token: str) -> OktaUser:
    """Verify a raw bearer token string. Used for WebSocket auth where there is no Request object."""
    if not settings.okta_domain:
        return OktaUser(sub="dev", email="dev@local", groups=["admin"])

    try:
        jwks = await _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        key = None
        for k in jwks.get("keys", []):
            if k["kid"] == unverified_header.get("kid"):
                key = k
                break
        if not key:
            raise ValueError("Invalid token key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.okta_audience or settings.okta_client_id,
            issuer=f"https://{settings.okta_domain}/oauth2/default",
        )

        groups = payload.get(settings.okta_claim, [])
        email = payload.get("email", payload.get("sub", ""))
        given_name = payload.get("given_name", "")
        family_name = payload.get("family_name", "")
        display_name = payload.get("name", "")

        class_year_raw = payload.get(settings.okta_class_year_claim)
        class_year = int(class_year_raw) if class_year_raw else None

        _need_userinfo = (
            not groups
            or not given_name
            or (settings.admin_okta_groups not in groups
                and settings.staff_okta_groups not in groups)
        )

        userinfo: dict = {}
        if _need_userinfo:
            userinfo = await _fetch_userinfo(token)
            ui_groups = userinfo.get(settings.okta_claim, [])
            if ui_groups:
                merged = set(groups) | set(ui_groups)
                groups = list(merged)
            if not given_name:
                given_name = userinfo.get("given_name", "")
                family_name = userinfo.get("family_name", family_name)
                display_name = userinfo.get("name", display_name)
            if class_year is None:
                cy = userinfo.get(settings.okta_class_year_claim)
                class_year = int(cy) if cy else None

        return OktaUser(
            sub=payload.get("sub", ""),
            email=email,
            groups=groups,
            given_name=given_name,
            family_name=family_name,
            display_name=display_name,
            class_year=class_year,
            profile=userinfo or payload,
        )
    except JWTError as e:
        raise ValueError(f"Token verification failed: {e}")


async def get_current_user(request: Request) -> OktaUser:
    if not settings.okta_domain:
        return OktaUser(sub="dev", email="dev@local", groups=["admin"])

    token = _extract_token(request)
    if not token:
        raise HTTPException(401, "Missing authentication token")

    try:
        jwks = await _get_jwks()
        unverified_header = jwt.get_unverified_header(token)
        key = None
        for k in jwks.get("keys", []):
            if k["kid"] == unverified_header.get("kid"):
                key = k
                break
        if not key:
            raise HTTPException(401, "Invalid token key")

        payload = jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=settings.okta_audience or settings.okta_client_id,
            issuer=f"https://{settings.okta_domain}/oauth2/default",
        )

        groups = payload.get(settings.okta_claim, [])
        email = payload.get("email", payload.get("sub", ""))
        given_name = payload.get("given_name", "")
        family_name = payload.get("family_name", "")
        display_name = payload.get("name", "")

        class_year_raw = payload.get(settings.okta_class_year_claim)
        class_year = int(class_year_raw) if class_year_raw else None

        _need_userinfo = (
            not groups
            or not given_name
            or (settings.admin_okta_groups not in groups
                and settings.staff_okta_groups not in groups)
        )

        userinfo: dict = {}
        if _need_userinfo:
            userinfo = await _fetch_userinfo(token)
            ui_groups = userinfo.get(settings.okta_claim, [])
            if ui_groups:
                merged = set(groups) | set(ui_groups)
                groups = list(merged)
            if not given_name:
                given_name = userinfo.get("given_name", "")
                family_name = userinfo.get("family_name", family_name)
                display_name = userinfo.get("name", display_name)
            if class_year is None:
                cy = userinfo.get(settings.okta_class_year_claim)
                class_year = int(cy) if cy else None

        log.debug("Auth resolved: email=%s groups=%s", email, groups)

        user = OktaUser(
            sub=payload.get("sub", ""),
            email=email,
            groups=groups,
            given_name=given_name,
            family_name=family_name,
            display_name=display_name,
            class_year=class_year,
            profile=userinfo or payload,
        )
        request.state.audit_user_email = user.email
        request.state.audit_user_sub = user.sub
        return user
    except JWTError as e:
        raise HTTPException(401, f"Token verification failed: {e}")


def require_role(*roles: str):
    async def dependency(user: OktaUser = Depends(get_current_user)):
        if not user.has_role(*roles):
            log.warning(
                "Access denied for %s (role=%s, groups=%s) — requires %s",
                user.email, user.role, user.groups, roles,
            )
            raise HTTPException(403, f"Requires one of: {', '.join(roles)}")
        return user
    return dependency


def require_admin():
    async def dependency(user: OktaUser = Depends(get_current_user)):
        if not user.is_admin:
            raise HTTPException(403, "Admin access required")
        return user
    return dependency


async def get_current_user_or_impersonated(request: Request) -> OktaUser:
    """Return the current user, or a synthetic impersonated user if admin provides X-Impersonate header."""
    user = await get_current_user(request)

    impersonate_email = request.headers.get("X-Impersonate", "").strip()
    if not impersonate_email:
        return user

    if not user.is_admin:
        raise HTTPException(403, "Only admins can impersonate")

    from ..database import async_session
    from sqlalchemy import select, text

    target_sub = ""
    target_name = impersonate_email
    target_groups: list[str] = []
    target_class_year: int | None = None

    # Fetch groups and profile from Okta (authoritative source)
    if settings.okta_domain and settings.okta_api_token:
        try:
            async with httpx.AsyncClient() as client:
                # Look up user by email (login)
                user_res = await client.get(
                    f"https://{settings.okta_domain}/api/v1/users/{impersonate_email}",
                    headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                    timeout=10,
                )
                if user_res.status_code == 200:
                    okta_user = user_res.json()
                    target_sub = okta_user.get("id", "")
                    profile = okta_user.get("profile", {})
                    target_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or impersonate_email

                    # Fetch groups
                    groups_res = await client.get(
                        f"https://{settings.okta_domain}/api/v1/users/{okta_user['id']}/groups",
                        headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                        timeout=10,
                    )
                    if groups_res.status_code == 200:
                        target_groups = [
                            g["profile"]["name"]
                            for g in groups_res.json()
                            if g.get("profile", {}).get("name")
                        ]

                    # Class year from custom claim if available
                    cy = profile.get(settings.okta_class_year_claim)
                    if cy:
                        try:
                            target_class_year = int(cy)
                        except (ValueError, TypeError):
                            pass
                else:
                    log.warning("Okta user lookup failed for %s: %d", impersonate_email, user_res.status_code)
        except Exception as e:
            log.warning("Okta API call failed during impersonation: %s", e)

    # Fallback to DB if Okta didn't return data
    if not target_sub:
        async with async_session() as db:
            app_row_result = await db.execute(text("""
                SELECT student_sub, student_name, student_email, class_year, okta_metadata
                FROM permit_applications
                WHERE LOWER(student_email) = LOWER(:email)
                ORDER BY created_at DESC LIMIT 1
            """), {"email": impersonate_email})
            app_row = app_row_result.mappings().first()

            perm_result = await db.execute(text("""
                SELECT COALESCE(p.student_id, '') as sub,
                       COALESCE(p.name, '') as name,
                       COALESCE(p.email, '') as email
                FROM permits p
                WHERE LOWER(p.email) = LOWER(:email) AND p.deleted_at IS NULL
                ORDER BY p.created_at DESC LIMIT 1
            """), {"email": impersonate_email})
            permit_row = perm_result.mappings().first()

        if app_row:
            target_sub = app_row["student_sub"] or ""
            target_name = app_row["student_name"] or impersonate_email
            target_class_year = app_row["class_year"]
            metadata = app_row["okta_metadata"] or {}
            if isinstance(metadata, dict) and not target_groups:
                target_groups = metadata.get("groups", [])
        elif permit_row:
            target_sub = permit_row["sub"] or ""
            target_name = permit_row["name"] or impersonate_email

    log.info("Admin %s impersonating %s (sub=%s, groups=%s)", user.email, impersonate_email, target_sub, target_groups)

    parts = target_name.split(" ", 1)
    given = parts[0] if parts else ""
    family = parts[1] if len(parts) > 1 else ""

    return OktaUser(
        sub=target_sub or f"impersonated:{impersonate_email}",
        email=impersonate_email,
        groups=target_groups,
        given_name=given,
        family_name=family,
        display_name=target_name,
        class_year=target_class_year,
    )
