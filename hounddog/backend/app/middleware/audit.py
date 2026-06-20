"""
System-wide audit middleware. Captures every mutating request (POST, PUT, DELETE, PATCH)
from authenticated users and writes an AuditLog entry.
"""

import json
import logging
import re
from datetime import datetime, timezone

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from ..database import async_session
from ..models.audit_log import AuditLog

logger = logging.getLogger("quarry.audit")

MUTATING_METHODS = {"POST", "PUT", "DELETE", "PATCH"}

SKIP_PATHS = {
    "/api/auth",
    "/api/sync",
    "/api/payments/webhook",
    "/ws",
    "/health",
}

RESOURCE_PATTERN = re.compile(r"^/api/([^/]+)(?:/([^/]+))?")

SENSITIVE_FIELDS = {"password", "secret", "api_key", "token", "stripe"}


def _sanitize_body(body: dict | list | None) -> dict | list | None:
    if body is None:
        return None
    if isinstance(body, list):
        return body[:10]
    sanitized = {}
    for k, v in body.items():
        if any(s in k.lower() for s in SENSITIVE_FIELDS):
            sanitized[k] = "***"
        elif isinstance(v, str) and len(v) > 500:
            sanitized[k] = v[:500] + "...(truncated)"
        else:
            sanitized[k] = v
    return sanitized


def _extract_resource_type(path: str) -> str:
    match = RESOURCE_PATTERN.match(path)
    if not match:
        return "unknown"
    segment = match.group(1)
    return segment.replace("-", "_")


def _extract_resource_id(path: str) -> str | None:
    match = RESOURCE_PATTERN.match(path)
    if not match:
        return None
    candidate = match.group(2)
    if candidate and len(candidate) > 8 and candidate not in ("import", "export", "stats", "bulk-status", "duplicates", "active", "config", "renew"):
        return candidate
    parts = path.rstrip("/").split("/")
    if len(parts) >= 4:
        last = parts[-1]
        if len(last) > 8 and last not in ("import", "export", "stats", "bulk-status", "duplicates", "active", "config", "renew"):
            return last
    return None


def _generate_summary(method: str, resource_type: str, resource_id: str | None, path: str) -> str:
    action_map = {"POST": "Created", "PUT": "Updated", "DELETE": "Deleted", "PATCH": "Updated"}
    verb = action_map.get(method, method)
    readable_type = resource_type.replace("_", " ")

    if "import" in path:
        return f"Imported {readable_type}"
    if "bulk" in path:
        return f"Bulk action on {readable_type}"
    if "renew" in path:
        return f"Renewed {readable_type} {resource_id or ''}"
    if resource_id:
        return f"{verb} {readable_type} {resource_id}"
    return f"{verb} {readable_type}"


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in MUTATING_METHODS:
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(skip) for skip in SKIP_PATHS):
            return await call_next(request)

        body_bytes = await request.body()
        request_body = None
        if body_bytes:
            try:
                request_body = json.loads(body_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError):
                request_body = None

        response = await call_next(request)

        user_email = getattr(request.state, "audit_user_email", None)
        user_sub = getattr(request.state, "audit_user_sub", None)

        if not user_email:
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer ") and len(auth_header) > 20:
                try:
                    from jose import jwt
                    payload = jwt.get_unverified_claims(auth_header[7:])
                    user_email = payload.get("email", payload.get("sub", "unknown"))
                    user_sub = payload.get("sub", "")
                except Exception:
                    user_email = None

        if not user_email:
            return response

        resource_type = _extract_resource_type(path)
        resource_id = _extract_resource_id(path)
        changes = getattr(request.state, "audit_changes", None)

        try:
            async with async_session() as session:
                async with session.begin():
                    log_entry = AuditLog(
                        user_email=user_email,
                        user_sub=user_sub or "",
                        action=request.method,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        endpoint=path,
                        summary=_generate_summary(request.method, resource_type, resource_id, path),
                        request_body=_sanitize_body(request_body),
                        response_status=response.status_code,
                        ip_address=request.client.host if request.client else None,
                        changes=changes,
                    )
                    session.add(log_entry)
        except Exception as e:
            logger.warning(f"Audit log write failed: {e}")

        return response
