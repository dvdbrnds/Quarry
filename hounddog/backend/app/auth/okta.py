"""Okta OIDC token verification for the dashboard."""

from fastapi import Depends, HTTPException, Request
from jose import JWTError, jwt
import httpx

from ..config import settings

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


async def _fetch_userinfo_groups(access_token: str) -> list[str]:
    """Fetch groups from Okta's /userinfo endpoint when the access token
    doesn't contain the groups claim (common default configuration)."""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{settings.okta_domain}/oauth2/default/v1/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                info = resp.json()
                return info.get(settings.okta_claim, [])
    except Exception:
        pass
    return []


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("access_token")


class OktaUser:
    def __init__(self, sub: str, email: str, groups: list[str]):
        self.sub = sub
        self.email = email
        self.groups = groups

    @property
    def is_admin(self) -> bool:
        return settings.admin_okta_groups in self.groups

    @property
    def is_staff(self) -> bool:
        return self.is_admin or settings.staff_okta_groups in self.groups

    @property
    def role(self) -> str:
        if self.is_admin:
            return "admin"
        if settings.staff_okta_groups in self.groups:
            return "staff"
        return "none"

    def has_role(self, *roles: str) -> bool:
        return self.role in roles


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

        if not groups:
            groups = await _fetch_userinfo_groups(token)

        user = OktaUser(
            sub=payload.get("sub", ""),
            email=email,
            groups=groups,
        )
        request.state.audit_user_email = user.email
        request.state.audit_user_sub = user.sub
        return user
    except JWTError as e:
        raise HTTPException(401, f"Token verification failed: {e}")


def require_role(*roles: str):
    async def dependency(user: OktaUser = Depends(get_current_user)):
        if not user.has_role(*roles):
            raise HTTPException(403, f"Requires one of: {', '.join(roles)}")
        return user
    return dependency


def require_admin():
    async def dependency(user: OktaUser = Depends(get_current_user)):
        if not user.is_admin:
            raise HTTPException(403, "Admin access required")
        return user
    return dependency
