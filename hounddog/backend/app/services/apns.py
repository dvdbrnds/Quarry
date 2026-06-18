"""
APNs silent push notification service.

Sends content-available pushes to all registered BirdDog devices when permit
data changes, prompting them to sync immediately.

Requires a .p8 APNs auth key from Apple Developer portal. Configure via env:
  QUARRY_APNS_KEY_PATH  - path to the .p8 key file
  QUARRY_APNS_KEY_ID    - 10-character Key ID from Apple
  QUARRY_APNS_TEAM_ID   - Apple Developer Team ID
  QUARRY_APNS_BUNDLE_ID - app bundle identifier (default: edu.moravian.birddog)
  QUARRY_APNS_USE_SANDBOX - True for development, False for production
"""

import json
import logging
import time
from pathlib import Path

import httpx
import jwt
from sqlalchemy import select

from ..config import settings
from ..database import async_session
from ..models.device import Device

logger = logging.getLogger("quarry.apns")

_cached_token: str | None = None
_token_issued_at: float = 0
TOKEN_LIFETIME = 3500  # Refresh ~2 min before the 1-hour expiry


def _get_apns_token() -> str | None:
    """Generate or return cached APNs JWT bearer token."""
    global _cached_token, _token_issued_at

    if not settings.apns_key_path or not settings.apns_key_id or not settings.apns_team_id:
        return None

    now = time.time()
    if _cached_token and (now - _token_issued_at) < TOKEN_LIFETIME:
        return _cached_token

    key_path = Path(settings.apns_key_path)
    if not key_path.exists():
        logger.warning("APNs key file not found: %s", key_path)
        return None

    private_key = key_path.read_text()
    payload = {"iss": settings.apns_team_id, "iat": int(now)}
    headers = {"alg": "ES256", "kid": settings.apns_key_id}

    _cached_token = jwt.encode(payload, private_key, algorithm="ES256", headers=headers)
    _token_issued_at = now
    return _cached_token


def _apns_host() -> str:
    if settings.apns_use_sandbox:
        return "https://api.sandbox.push.apple.com"
    return "https://api.push.apple.com"


async def _get_device_tokens() -> list[str]:
    """Fetch all non-null push tokens from the database."""
    async with async_session() as session:
        result = await session.execute(
            select(Device.push_token).where(Device.push_token.isnot(None))
        )
        return [row[0] for row in result.all()]


async def send_permit_push(action: str, count: int):
    """Send a silent push to all registered devices notifying of permit changes."""
    token = _get_apns_token()
    if not token:
        logger.debug("APNs not configured, skipping push notification")
        return

    device_tokens = await _get_device_tokens()
    if not device_tokens:
        logger.debug("No devices registered for push notifications")
        return

    payload = json.dumps({
        "aps": {"content-available": 1},
        "permit_change": {"action": action, "count": count},
    })

    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": settings.apns_bundle_id,
        "apns-push-type": "background",
        "apns-priority": "5",
    }

    async with httpx.AsyncClient(http2=True) as client:
        for device_token in device_tokens:
            url = f"{_apns_host()}/3/device/{device_token}"
            try:
                resp = await client.post(url, content=payload, headers=headers)
                if resp.status_code == 410:
                    await _remove_token(device_token)
                elif resp.status_code != 200:
                    logger.warning(
                        "APNs push failed for token %s...: %d %s",
                        device_token[:8], resp.status_code, resp.text,
                    )
            except Exception as e:
                logger.warning("APNs push error for token %s...: %s", device_token[:8], e)

    logger.info("Sent permit_changed push to %d device(s)", len(device_tokens))


async def _remove_token(token: str):
    """Remove an invalid push token (device unregistered)."""
    async with async_session() as session:
        result = await session.execute(
            select(Device).where(Device.push_token == token)
        )
        device = result.scalar_one_or_none()
        if device:
            device.push_token = None
            await session.commit()
