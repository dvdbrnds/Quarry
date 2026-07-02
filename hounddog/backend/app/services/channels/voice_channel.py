"""Twilio voice call channel. Emergency-only. Robocalls all subscribers
with a TTS reading of the alert message."""

import logging

from . import AlertChannel, ChannelResult
from ..sms import _get_client
from ...config import settings

logger = logging.getLogger("quarry.channels.voice")


class VoiceChannel(AlertChannel):
    name = "voice"
    emergency_only = True

    def is_configured(self) -> bool:
        return bool(settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_from_number)

    async def send(self, alert, subscribers) -> ChannelResult:
        client = _get_client()
        if not client:
            return ChannelResult(channel=self.name, error="Twilio not configured")

        phone_recipients = [s for s in subscribers if s.phone and s.sms_enabled]
        if not phone_recipients:
            return ChannelResult(channel=self.name)

        school = settings.school_name or "Campus"
        twiml = (
            f'<Response>'
            f'<Say voice="alice" language="en-US">'
            f'This is an automated emergency alert from {school}. '
            f'{alert.subject}. {alert.body_text}'
            f'</Say>'
            f'<Pause length="2"/>'
            f'<Say voice="alice" language="en-US">'
            f'Repeating. {alert.subject}. {alert.body_text}'
            f'</Say>'
            f'</Response>'
        )

        sent = 0
        failed = 0
        for sub in phone_recipients:
            try:
                client.calls.create(
                    twiml=twiml,
                    from_=settings.twilio_from_number,
                    to=sub.phone,
                )
                sent += 1
            except Exception as e:
                logger.error("Voice call failed to %s: %s", sub.phone, e)
                failed += 1

        return ChannelResult(channel=self.name, sent=sent, failed=failed)
