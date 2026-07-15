"""Zoom Phone paging channel.

Uses Zoom Server-to-Server OAuth2 to authenticate, then triggers a paging
broadcast to a configured paging group. The paging message is TTS derived
from the alert subject and body.

Config:
    ZOOM_ACCOUNT_ID
    ZOOM_CLIENT_ID
    ZOOM_CLIENT_SECRET
    ZOOM_PAGING_GROUP_ID
"""

import base64
import logging
import time

import httpx

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.zoom_phone")

_token_cache: dict = {"access_token": "", "expires_at": 0}


async def _get_access_token() -> str:
    """Get a Zoom access token via Server-to-Server OAuth2."""
    now = time.time()
    if _token_cache["access_token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["access_token"]

    credentials = base64.b64encode(
        f"{settings.zoom_client_id}:{settings.zoom_client_secret}".encode()
    ).decode()

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            "https://zoom.us/oauth/token",
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={
                "grant_type": "account_credentials",
                "account_id": settings.zoom_account_id,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return data["access_token"]


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
        try:
            token = await _get_access_token()
        except Exception as e:
            logger.error("Zoom OAuth token failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=f"OAuth failed: {e}")

        school = settings.school_name or "Campus"
        tts_message = (
            f"Attention. This is an emergency alert from {school}. "
            f"{alert.subject}. {alert.body_text}"
        ).strip()

        payload = {
            "paging_group_id": settings.zoom_paging_group_id,
            "message": tts_message[:512],
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(
                    f"https://api.zoom.us/v2/phone/paging_groups/"
                    f"{settings.zoom_paging_group_id}/paging",
                    headers={"Authorization": f"Bearer {token}"},
                    json=payload,
                )
                resp.raise_for_status()
            return ChannelResult(channel=self.name, sent=1)
        except Exception as e:
            logger.error("Zoom Phone paging failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=str(e))
