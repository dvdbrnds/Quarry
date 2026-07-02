"""Zoom Phone paging channel.

Zoom Phone supports paging groups. On emergency, page all phones with
a TTS alert via the Zoom API.

When Zoom Phone rollout is further along, implement:
  - OAuth2 server-to-server auth with zoom_client_id / zoom_client_secret
  - POST /phone/call_queues/{id}/calls or use the paging group API
  - TTS body derived from alert subject + body

Expected config:
  QUARRY_ZOOM_ACCOUNT_ID
  QUARRY_ZOOM_CLIENT_ID
  QUARRY_ZOOM_CLIENT_SECRET
  QUARRY_ZOOM_PAGING_GROUP_ID
"""

import logging

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.zoom_phone")


class ZoomPhoneChannel(AlertChannel):
    name = "zoom_phone"
    emergency_only = True

    def is_configured(self) -> bool:
        return bool(
            settings.zoom_account_id
            and settings.zoom_client_id
            and settings.zoom_client_secret
            and settings.zoom_paging_group_id
        )

    async def send(self, alert, subscribers) -> ChannelResult:
        logger.warning(
            "Zoom Phone channel not implemented -- alert '%s' not sent to paging group. "
            "Configure QUARRY_ZOOM_* env vars and implement the API calls.",
            alert.subject,
        )
        return ChannelResult(channel=self.name, error="Not implemented")
