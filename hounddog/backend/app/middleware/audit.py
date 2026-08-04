"""
Comprehensive audit middleware for chain of evidence and legal compliance.

Uses pure ASGI middleware (NOT BaseHTTPMiddleware, which has known issues
with request.state propagation, body consumption, and asyncio task isolation).
Every HTTP request is logged unconditionally.
"""

import json
import logging
import re
from io import BytesIO

from sqlalchemy import select, text
from starlette.types import ASGIApp, Receive, Scope, Send, Message

from ..database import async_session
from ..models.audit_log import AuditLog
from ..models.device import Device

logger = logging.getLogger("quarry.audit")

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/favicon.ico"}
SKIP_PREFIXES = ("/static/", "/assets/")

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
    return match.group(1).replace("-", "_")


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
                      path: str, request_body: dict | list | None = None) -> str:
    key = f"{method} {path.rstrip('/')}"
    if key in SYNC_SUMMARIES:
        return SYNC_SUMMARIES[key]

    # Lottery V2 application submit — include ranked permit choices when possible
    if (
        method == "POST"
        and path.rstrip("/") == "/api/lottery-v2/applications"
        and isinstance(request_body, dict)
    ):
        campus = (request_body.get("campus") or "").capitalize()
        prefs = request_body.get("tier_preference_labels") or request_body.get(
            "tier_preferences"
        )
        if isinstance(prefs, list) and prefs:
            # Prefer human labels when present; fall back to truncated UUIDs
            ranked = []
            for i, p in enumerate(prefs[:6], 1):
                label = str(p)
                if len(label) > 36 and "-" in label:
                    label = label[:8]
                ranked.append(f"#{i} {label}")
            joined = " → ".join(ranked)
            where = f"{campus} campus — " if campus else ""
            return f"Submitted lottery application ({where}{joined})"
        return f"Submitted lottery application{f' ({campus})' if campus else ''}"

    if method == "POST" and "/lottery-v2/applications/" in path and path.rstrip("/").endswith("/accept"):
        return "Started lottery payment (Accept & Pay → Stripe)"
    if method == "POST" and "/lottery-v2/applications/" in path and path.rstrip("/").endswith("/decline"):
        return "Declined lottery permit offer"

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
        if "logout" in path:
            return "User signed out"
        if "me" in path:
            return "User session check"
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


async def _resolve_tier_labels(pref_ids: list) -> list[str]:
    """Resolve permit type UUIDs to labels for audit summaries."""
    if not pref_ids:
        return []
    try:
        import uuid as _uuid
        from ..models.permit_type import PermitType

        ids = []
        for raw in pref_ids:
            try:
                ids.append(_uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                continue
        if not ids:
            return [str(p) for p in pref_ids]
        async with async_session() as db:
            rows = (
                await db.execute(select(PermitType).where(PermitType.id.in_(ids)))
            ).scalars().all()
            by_id = {str(pt.id): pt.label for pt in rows}
        return [by_id.get(str(p), str(p)[:8]) for p in pref_ids]
    except Exception:
        logger.exception("Failed to resolve lottery tier labels for audit")
        return [str(p)[:8] for p in pref_ids]


async def _identify_user(headers: list[tuple[bytes, bytes]]) -> tuple[str, str]:
    """Extract user identity from request headers."""
    auth_value = ""
    for name, value in headers:
        if name.lower() == b"authorization":
            auth_value = value.decode("latin-1", errors="replace")
            break

    if not auth_value or not auth_value.startswith("Bearer "):
        return "anonymous", ""

    token = auth_value[7:].strip()
    if not token:
        return "anonymous", ""

    if token.count(".") == 2:
        try:
            from jose import jwt as jose_jwt
            payload = jose_jwt.get_unverified_claims(token)
            email = payload.get("email") or payload.get("sub") or "unknown"
            sub = payload.get("sub", "")
            return email, sub
        except Exception:
            pass

    try:
        async with async_session() as db:
            result = await db.execute(
                select(Device.name, Device.id).where(Device.api_key == token)
            )
            row = result.first()
            if row:
                return f"device:{row[0]}", f"device:{row[1]}"
    except Exception:
        pass

    return "anonymous", ""


async def verify_audit_table():
    """Call at startup to confirm the audit_log table exists and is writable."""
    try:
        async with async_session() as session:
            async with session.begin():
                await session.execute(text("SELECT count(*) FROM audit_log"))
        logger.info("Audit log table verified OK")
    except Exception as e:
        logger.error("AUDIT LOG TABLE CHECK FAILED: %s", e, exc_info=True)


class AuditMiddleware:
    """Pure ASGI middleware -- no BaseHTTPMiddleware."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        method = scope["method"]
        headers = scope.get("headers", [])

        user_email, user_sub = await _identify_user(headers)

        # Collect request body for mutating requests
        request_body = None
        body_chunks: list[bytes] = []

        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            async def receive_wrapper() -> Message:
                message = await receive()
                if message["type"] == "http.request":
                    body_chunks.append(message.get("body", b""))
                return message
        else:
            receive_wrapper = receive

        # Capture response status code
        response_status = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            await send(message)

        # Process the request
        await self.app(scope, receive_wrapper, send_wrapper)

        # Parse body if captured
        if body_chunks:
            raw = b"".join(body_chunks)
            if raw:
                try:
                    request_body = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    pass

        # Extract client IP
        client = scope.get("client")
        ip_address = client[0] if client else None

        resource_type = _extract_resource_type(path)
        resource_id = _extract_resource_id(path)

        # Enrich lottery application bodies with human-readable permit ranks
        body_for_log = request_body
        if (
            method == "POST"
            and path.rstrip("/") == "/api/lottery-v2/applications"
            and isinstance(request_body, dict)
            and request_body.get("tier_preferences")
        ):
            labels = await _resolve_tier_labels(list(request_body["tier_preferences"]))
            body_for_log = {
                **request_body,
                "tier_preference_labels": labels,
            }

        summary = _generate_summary(
            method, resource_type, resource_id, path, body_for_log
        )

        # Write audit entry
        try:
            async with async_session() as session:
                async with session.begin():
                    session.add(AuditLog(
                        user_email=user_email,
                        user_sub=user_sub,
                        action=method,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        endpoint=path,
                        summary=summary,
                        request_body=_sanitize_body(body_for_log)
                        if method != "GET" else None,
                        response_status=response_status,
                        ip_address=ip_address,
                    ))
        except Exception as e:
            logger.error("AUDIT WRITE FAILED for %s %s: %s", method, path, e,
                         exc_info=True)
