"""Microsoft Teams webhook channel. Posts an Adaptive Card to a Teams
incoming webhook URL."""

import logging

import httpx

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.teams")

CATEGORY_COLORS = {
    "emergency": "attention",
    "weather": "accent",
    "campus_closing": "warning",
    "parking": "accent",
    "general": "default",
}


class TeamsChannel(AlertChannel):
    name = "teams"
    emergency_only = False

    def is_configured(self) -> bool:
        return bool(settings.teams_webhook_url)

    async def send(self, alert, subscribers) -> ChannelResult:
        color = CATEGORY_COLORS.get(alert.category, "default")
        card = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "size": "large",
                            "weight": "bolder",
                            "text": alert.subject,
                            "color": color,
                            "wrap": True,
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Category: {alert.category.upper()}",
                            "isSubtle": True,
                            "spacing": "none",
                        },
                        {
                            "type": "TextBlock",
                            "text": alert.body_text,
                            "wrap": True,
                            "spacing": "medium",
                        },
                        {
                            "type": "TextBlock",
                            "text": f"Sent by {alert.sent_by}",
                            "isSubtle": True,
                            "size": "small",
                            "spacing": "large",
                        },
                    ],
                },
            }],
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(settings.teams_webhook_url, json=card)
                resp.raise_for_status()
            return ChannelResult(channel=self.name, sent=1)
        except Exception as e:
            logger.error("Teams webhook failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=str(e))
