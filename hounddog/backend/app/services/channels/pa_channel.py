"""PA system / siren channel.

STUB: Hardware-dependent. If the PA system has an IP interface, trigger it
via HTTP. If analog, a relay or Crestron processor may be needed to bridge.

When hardware is identified, implement:
  - trigger_pa_alert(tone, message) where tone is "siren", "chime", or "voice"
  - For IP-based systems: HTTP POST to the PA controller
  - For analog: trigger a relay via a networked GPIO or Crestron processor

Expected config:
  QUARRY_PA_SYSTEM_HOST -- IP or hostname of the PA controller
"""

import logging

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.pa")


class PaChannel(AlertChannel):
    name = "pa"
    emergency_only = True

    def is_configured(self) -> bool:
        return bool(settings.pa_system_host)

    async def send(self, alert, subscribers) -> ChannelResult:
        logger.warning(
            "PA system channel not implemented -- alert '%s' not sent to PA. "
            "Set QUARRY_PA_SYSTEM_HOST and implement the API calls.",
            alert.subject,
        )
        return ChannelResult(channel=self.name, error="Not implemented")

    async def clear(self, alert) -> None:
        logger.info("PA clear (stub) for alert %s", alert.id)
