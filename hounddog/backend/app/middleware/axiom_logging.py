"""
Pure ASGI middleware that ships one structured event per HTTP request to Axiom.

Uses the same ASGI pattern as AuditMiddleware (not BaseHTTPMiddleware) to
avoid known issues with request.state propagation and body consumption.

Complete no-op when AXIOM_TOKEN is unset. Every external call is wrapped in
try/except so a logging failure can never crash a user request.
"""

import os
import time

import httpx
import sentry_sdk
import structlog
from starlette.types import ASGIApp, Receive, Scope, Send, Message

logger = structlog.get_logger("quarry.axiom_request")

AXIOM_TOKEN = os.environ.get("AXIOM_TOKEN", "")
AXIOM_DATASET = os.environ.get("AXIOM_DATASET", "hounddog")
AXIOM_URL = f"https://api.axiom.co/v1/datasets/{AXIOM_DATASET}/ingest"

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/favicon.ico"}
SKIP_PREFIXES = ("/static/", "/assets/")


class AxiomRequestLogger:
    """Pure ASGI middleware -- logs method, path, status, duration, user, and deploy SHA."""

    def __init__(self, app: ASGIApp):
        self.app = app
        self.enabled = bool(AXIOM_TOKEN)

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not self.enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in SKIP_PATHS or any(path.startswith(p) for p in SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        status_code = 0

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        error_str = None
        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)
            error_str = str(exc)
            raise
        finally:
            try:
                duration_ms = round((time.monotonic() - start) * 1000, 1)
                method = scope.get("method", "")

                # Extract user from headers (best-effort, no DB calls)
                user_email = None
                headers = scope.get("headers", [])
                for name, value in headers:
                    if name == b"authorization":
                        token_str = value.decode("latin-1", errors="replace")
                        if token_str.startswith("Bearer ") and token_str.count(".") == 2:
                            try:
                                import json
                                import base64
                                payload_b64 = token_str.split(".")[1]
                                padding = 4 - len(payload_b64) % 4
                                payload_b64 += "=" * padding
                                payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                                user_email = payload.get("email") or payload.get("sub")
                            except Exception as e:
                                pass  # intentional: non-JWT tokens are normal
                        break

                user_agent = ""
                for name, value in headers:
                    if name == b"user-agent":
                        user_agent = value.decode("latin-1", errors="replace")[:200]
                        break

                query = scope.get("query_string", b"").decode("latin-1", errors="replace")

                event = {
                    "_time": time.time(),
                    "method": method,
                    "path": path,
                    "query": query or None,
                    "status": status_code or 500,
                    "duration_ms": duration_ms,
                    "user": user_email,
                    "user_agent": user_agent,
                    "error": error_str,
                    "deploy_sha": os.environ.get("GIT_SHA", "unknown"),
                }

                async with httpx.AsyncClient() as client:
                    await client.post(
                        AXIOM_URL,
                        json=[event],
                        headers={
                            "Authorization": f"Bearer {AXIOM_TOKEN}",
                            "Content-Type": "application/json",
                        },
                        timeout=2.0,
                    )
            except Exception as e:
                pass  # intentional: logging must never break the app
