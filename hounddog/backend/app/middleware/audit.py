"""
Comprehensive audit middleware for chain of evidence and legal compliance.
Captures EVERY request to the API -- reads, writes, device syncs, auth events,
payments -- so every interaction with ticket/evidence data is traceable.
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

SKIP_PATHS = {"/health", "/ws", "/docs", "/openapi.json", "/favicon.ico"}
SKIP_PREFIXES = ("/static/", "/assets/", "/uploads/")

RESOURCE_PATTERN = re.compile(r"^/api/([^/]+)(?:/([^/]+))?")

SENSITIVE_FIELDS = {"password", "secret", "api_key", "token", "stripe",
                    "photo_base64", "photo"}

ACTION_WORDS = {
    "GET": "Viewed",
    "POST": "Created",
    "PUT": "Updated",
    "PATCH": "Updated",
    "DELETE": "Deleted",
}

SYNC_SUMMARIES = {
    "GET /api/sync/permits": "Device synced permit database",
    "GET /api/sync/lots": "Device synced lot data",
    "GET /api/sync/violation-types": "Device synced violation types",
    "GET /api/sync/calendar": "Device synced academic calendar",
    "GET /api/sync/settings": "Device synced enforcement settings",
    "GET /api/sync/status": "Device checked sync status",
    "POST /api/sync/tickets": "Device submitted ticket",
    "POST /api/sync/register-push": "Device registered push token",
}


def _sanitize_body(body: dict | list | None) -> dict | list | None:
    if body is None:
        return None
    if isinstance(body, list):
        return [_sanitize_body(item) if isinstance(item, dict) else item
                for item in body[:10]]
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
    non_id_segments = {
        "import", "export", "stats", "bulk-status", "duplicates",
        "active", "config", "renew", "pipeline", "me", "callback",
        "permits", "lots", "violation-types", "calendar", "settings",
        "status", "register-push", "tickets", "webhook", "public",
    }
    candidate = match.group(2)
    if candidate and len(candidate) > 8 and candidate not in non_id_segments:
        return candidate
    parts = path.rstrip("/").split("/")
    if len(parts) >= 4:
        last = parts[-1]
        if len(last) > 8 and last not in non_id_segments:
            return last
    return None


def _generate_summary(method: str, resource_type: str, resource_id: str | None,
                      path: str) -> str:
    key = f"{method} {path.rstrip('/')}"
    if key in SYNC_SUMMARIES:
        return SYNC_SUMMARIES[key]

    verb = ACTION_WORDS.get(method, method)
    readable_type = resource_type.replace("_", " ")

    if "import" in path:
        return f"Imported {readable_type}"
    if "bulk" in path:
        return f"Bulk action on {readable_type}"
    if "renew" in path:
        return f"Renewed {readable_type} {resource_id or ''}".strip()
    if "void" in path:
        return f"Voided {readable_type} {resource_id or ''}".strip()
    if "appeal" in path:
        return f"Appeal action on {readable_type} {resource_id or ''}".strip()
    if path.startswith("/api/auth"):
        if "callback" in path:
            return "OAuth callback"
        if "me" in path:
            return "Checked auth session"
        if "config" in path:
            return "Loaded auth config"
        return f"Auth {method}"
    if path.startswith("/api/payments"):
        if "webhook" in path:
            return "Payment webhook received"
        return f"{verb} payment"

    if method == "GET":
        if resource_id:
            return f"Viewed {readable_type} {resource_id}"
        return f"Listed {readable_type}"

    if resource_id:
        return f"{verb} {readable_type} {resource_id}"
    return f"{verb} {readable_type}"


def _extract_user(request: Request) -> tuple[str | None, str]:
    email = getattr(request.state, "audit_user_email", None)
    sub = getattr(request.state, "audit_user_sub", None) or ""
    if email:
        return email, sub

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer ") and len(auth_header) > 20:
        try:
            from jose import jwt as jose_jwt
            payload = jose_jwt.get_unverified_claims(auth_header[7:])
            email = payload.get("email") or payload.get("sub") or "unknown"
            sub = payload.get("sub", "")
            return email, sub
        except Exception as exc:
            logger.debug(f"Audit JWT extraction failed: {exc}")

    return None, ""


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path

        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            return await call_next(request)

        if not path.startswith("/api"):
            return await call_next(request)

        request_body = None
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            body_bytes = await request.body()
            if body_bytes:
                try:
                    request_body = json.loads(body_bytes)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        response = await call_next(request)

        user_email, user_sub = _extract_user(request)

        if not user_email:
            if path.startswith("/api/auth"):
                user_email = "anonymous"
            else:
                return response

        resource_type = _extract_resource_type(path)
        resource_id = _extract_resource_id(path)
        changes = getattr(request.state, "audit_changes", None)

        try:
            async with async_session() as session:
                async with session.begin():
                    log_entry = AuditLog(
                        user_email=user_email,
                        user_sub=user_sub,
                        action=request.method,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        endpoint=path,
                        summary=_generate_summary(
                            request.method, resource_type, resource_id, path),
                        request_body=_sanitize_body(request_body)
                        if request.method != "GET" else None,
                        response_status=response.status_code,
                        ip_address=request.client.host if request.client else None,
                        changes=changes,
                    )
                    session.add(log_entry)
        except Exception as e:
            logger.error(f"Audit log write failed: {e}", exc_info=True)

        return response
