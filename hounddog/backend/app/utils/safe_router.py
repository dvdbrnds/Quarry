"""
APIRouter subclass that refuses to register HTTP PATCH routes.

Moravian's WAF silently blocks PATCH in production. This was discovered
and re-discovered multiple times (10+ commits, ~6 hours wasted).
SafeRouter makes the failure happen at import time with a clear message
instead of silently in production weeks later.

HTTP DELETE is allowed here because MethodOverrideMiddleware in main.py
translates the frontend's POST + X-HTTP-Method-Override: DELETE header
into a real DELETE internally — the WAF never sees the DELETE verb.

See INFRASTRUCTURE.md for the full list of WAF constraints.
"""

from fastapi import APIRouter


class SafeRouter(APIRouter):

    def api_route(self, path, *, methods=None, **kwargs):
        if methods:
            blocked = {"PATCH"} & {m.upper() for m in methods}
            if blocked:
                raise ValueError(
                    f"WAF blocks {blocked} -- see INFRASTRUCTURE.md. "
                    f"Use PUT for full updates or POST for partial updates."
                )
        return super().api_route(path, methods=methods, **kwargs)

    def patch(self, *args, **kwargs):
        raise ValueError(
            "WAF blocks HTTP PATCH -- use PUT or POST. "
            "See INFRASTRUCTURE.md."
        )
