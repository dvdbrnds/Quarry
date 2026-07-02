"""Website banner channel. Maintains an in-memory active alert state
that the public GET /api/alerts/active endpoint returns. No push needed --
website JS polls the endpoint."""

import logging

from . import AlertChannel, ChannelResult

logger = logging.getLogger("quarry.channels.banner")

_active_banner: dict | None = None


def get_active_banner() -> dict | None:
    return _active_banner


class BannerChannel(AlertChannel):
    name = "banner"
    emergency_only = False

    def is_configured(self) -> bool:
        return True

    async def send(self, alert, subscribers) -> ChannelResult:
        global _active_banner
        _active_banner = {
            "id": str(alert.id),
            "category": alert.category,
            "subject": alert.subject,
            "body_text": alert.body_text,
            "sent_at": alert.sent_at.isoformat() if alert.sent_at else "",
            "status": "active",
        }
        return ChannelResult(channel=self.name, sent=1)

    async def clear(self, alert) -> None:
        global _active_banner
        _active_banner = None
