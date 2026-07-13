"""
Desktop alert SSE broadcast.

Maintains in-memory SSE connections for desktop alert clients and
provides broadcast functions called by the alert dispatcher.
"""

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..models.alert_log import AlertLog

logger = logging.getLogger("quarry.desktop")

_connections: list[asyncio.Queue] = []


def get_connections() -> list[asyncio.Queue]:
    return _connections


async def broadcast_alert(alert: "AlertLog"):
    data = json.dumps({
        "id": str(alert.id),
        "category": alert.category,
        "subject": alert.subject,
        "body_text": alert.body_text,
        "sent_by": alert.sent_by,
        "sent_at": alert.sent_at.isoformat() if alert.sent_at else None,
    })
    payload = f"event: alert\ndata: {data}\n\n"

    for q in _connections[:]:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


async def broadcast_clear(alert_id: str):
    payload = f'event: clear\ndata: {json.dumps({"id": alert_id})}\n\n'
    for q in _connections[:]:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass
