"""Crestron scheduling panel override channel.

STUB: Requires knowing the Crestron control processor model and API.
The panels likely talk to a Crestron Virtual Control or XiO Cloud instance.

When API docs are available, implement:
  - POST to Crestron control processor to change panel display text
  - Set room occupancy light to blink red
  - On clear, restore normal panel display

Expected config:
  QUARRY_CRESTRON_HOST -- IP or hostname of the Crestron processor
  QUARRY_CRESTRON_API_KEY -- authentication token
"""

import logging

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.crestron")


class CrestronChannel(AlertChannel):
    name = "crestron"
    emergency_only = True

    def is_configured(self) -> bool:
        return bool(settings.crestron_host and settings.crestron_api_key)

    async def send(self, alert, subscribers) -> ChannelResult:
        logger.warning(
            "Crestron channel not implemented -- alert '%s' not sent to panels. "
            "Set QUARRY_CRESTRON_HOST and implement the API calls.",
            alert.subject,
        )
        return ChannelResult(channel=self.name, error="Not implemented")

    async def clear(self, alert) -> None:
        logger.info("Crestron clear (stub) for alert %s", alert.id)
