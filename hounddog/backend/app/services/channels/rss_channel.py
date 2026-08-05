"""RSS feed channel. Maintains an in-memory list of recent alert items
served as RSS 2.0 XML by the public GET /api/alerts/feed.xml endpoint."""

import logging
from collections import deque

from . import AlertChannel, ChannelResult

logger = logging.getLogger("quarry.channels.rss")

MAX_FEED_ITEMS = 50

_feed_items: deque[dict] = deque(maxlen=MAX_FEED_ITEMS)


def get_feed_items() -> list[dict]:
    return list(_feed_items)


class RssChannel(AlertChannel):
    name = "rss"
    emergency_only = False

    def is_configured(self) -> bool:
        return True

    async def send(self, alert, subscribers) -> ChannelResult:
        _feed_items.appendleft({
            "id": str(alert.id),
            "category": alert.category,
            "subject": alert.subject,
            "body_text": alert.body_text,
            "sent_at": alert.sent_at.isoformat() if alert.sent_at else "",
            "status": "active",
        })
        return ChannelResult(channel=self.name, sent=1)

    async def clear(self, alert) -> None:
        alert_id = str(alert.id)
        for item in _feed_items:
            if item["id"] == alert_id:
                item["status"] = "cleared"
                item["subject"] = f"[CLEARED] {item['subject']}"
                break
