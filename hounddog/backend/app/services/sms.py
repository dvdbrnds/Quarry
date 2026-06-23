"""Twilio SMS service for lot closure and general notifications."""

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
    """Send SMS to multiple recipients. Returns count of successful sends."""
    sent = 0
    for phone in recipients:
        if send_sms(phone, body):
            sent += 1
    return sent
