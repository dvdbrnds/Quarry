"""Extron Room Agent scheduling panel override channel.

Sends an HTTP POST with JSON to the Extron Room Agent server.
On emergency: changes every panel display to the alert message (red background,
large text) and blinks the room occupancy LED red.
On clear: sends an all_clear flag to restore normal panel display.

Config: QUARRY_EXTRON_ROOM_AGENT_URL
"""

import logging

import httpx

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.extron")

SEVERITY_MAP = {
    "emergency": "critical",
    "weather": "warning",
    "campus_closing": "warning",
    "parking": "info",
    "general": "info",
}


class ExtronChannel(AlertChannel):
    name = "extron"
    emergency_only = True

    def is_configured(self) -> bool:
        return bool(settings.extron_room_agent_url)

    async def send(self, alert, subscribers) -> ChannelResult:
        payload = {
            "message": f"{alert.subject}\n{alert.body_text}".strip(),
            "severity": SEVERITY_MAP.get(alert.category, "warning"),
            "category": alert.category,
            "alert_id": str(alert.id),
            "all_clear": False,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    settings.extron_room_agent_url,
                    json=payload,
                )
                resp.raise_for_status()
            return ChannelResult(channel=self.name, sent=1)
        except Exception as e:
            logger.error("Extron Room Agent POST failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=str(e))

    async def clear(self, alert) -> None:
        if not self.is_configured():
            return

        payload = {
            "message": "All clear",
            "severity": "info",
            "category": alert.category,
            "alert_id": str(alert.id),
            "all_clear": True,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    settings.extron_room_agent_url,
                    json=payload,
                )
                resp.raise_for_status()
        except Exception as e:
            logger.error("Extron Room Agent clear failed: %s", e)
