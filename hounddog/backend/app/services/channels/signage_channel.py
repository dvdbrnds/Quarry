"""Digital signage channel. Broadcasts alert state via SSE to connected
signage players so they switch to alert-override mode."""

import logging

from . import AlertChannel, ChannelResult

logger = logging.getLogger("quarry.channels.signage")


class SignageChannel(AlertChannel):
    name = "signage"
    emergency_only = False

    def is_configured(self) -> bool:
        return True

    async def send(self, alert, subscribers) -> ChannelResult:
        data = {
            "id": str(alert.id),
            "category": alert.category,
            "subject": alert.subject,
            "body_text": alert.body_text,
            "sent_at": alert.sent_at.isoformat() if alert.sent_at else "",
        }

        try:
            from ...routers.signage import broadcast_to_screens
            count = await broadcast_to_screens("alert_override", data)
            return ChannelResult(channel=self.name, sent=count)
        except Exception as e:
            logger.error("Signage broadcast failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=str(e))

    async def clear(self, alert) -> None:
        try:
            from ...routers.signage import broadcast_to_screens
            await broadcast_to_screens("alert_clear", {"id": str(alert.id)})
        except Exception:
            pass
