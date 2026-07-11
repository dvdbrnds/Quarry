"""Twilio SMS service for lot closure and general notifications."""

import asyncio
import logging

from ..config import settings

logger = logging.getLogger("quarry.sms")

_client = None


def _get_client():
    global _client
    if _client is None:
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            return None
        from twilio.rest import Client
        _client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client


def send_sms(to: str, body: str) -> bool:
    client = _get_client()
    if not client:
        logger.warning("Twilio not configured -- SMS not sent to %s", to)
        return False

    if not settings.twilio_from_number:
        logger.warning("No Twilio from number configured -- SMS not sent")
        return False

    try:
        client.messages.create(
            body=body,
            from_=settings.twilio_from_number,
            to=to,
        )
        logger.info("SMS sent to %s", to)
        return True
    except Exception as e:
        logger.error("SMS send failed to %s: %s", to, e, exc_info=True)
        return False


def send_bulk_sms(recipients: list[str], body: str) -> int:
    """Send SMS to multiple recipients (sync). Returns count of successful sends."""
    sent = 0
    for phone in recipients:
        if send_sms(phone, body):
            sent += 1
    return sent


async def send_sms_async(to: str, body: str) -> bool:
    """Non-blocking wrapper around send_sms."""
    return await asyncio.to_thread(send_sms, to, body)


async def send_bulk_sms_async(recipients: list[str], body: str) -> int:
    """Send SMS to multiple recipients without blocking the event loop."""
    count = 0
    for phone in recipients:
        if await send_sms_async(phone, body):
            count += 1
    return count
