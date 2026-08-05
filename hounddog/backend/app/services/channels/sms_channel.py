import logging

from . import AlertChannel, ChannelResult
from ..sms import send_sms_async
from ..sms_templates import render_alert_sms
from ...config import settings

logger = logging.getLogger("quarry.channels.sms")


class SmsChannel(AlertChannel):
    name = "sms"
    emergency_only = False
    settings_schema = [
        {"key": "account_sid", "label": "Twilio Account SID", "type": "string", "required": True},
        {"key": "auth_token", "label": "Twilio Auth Token", "type": "password", "required": True},
        {"key": "from_number", "label": "From Phone Number", "type": "string", "required": True},
    ]

    def is_configured(self) -> bool:
        return bool(
            self.get_setting("account_sid", settings.twilio_account_sid)
            and self.get_setting("auth_token", settings.twilio_auth_token)
            and self.get_setting("from_number", settings.twilio_from_number)
        )

    async def send(self, alert, subscribers) -> ChannelResult:
        sms_recipients = [s for s in subscribers if s.phone and s.sms_enabled]
        if not sms_recipients:
            return ChannelResult(channel=self.name)

        school = settings.school_name or "Campus"
        body_sms = alert.body_sms or alert.body_text
        formatted = render_alert_sms(
            alert.category, alert.subject, body_sms,
            school_name=school,
        )

        sent = 0
        failed = 0
        for sub in sms_recipients:
            unsub_url = f"{settings.student_facing_url}/alerts/unsubscribe/{sub.unsubscribe_token}"
            body = f"{formatted}\n\nUnsubscribe: {unsub_url}"
            if await send_sms_async(sub.phone, body):
                sent += 1
            else:
                failed += 1

        return ChannelResult(channel=self.name, sent=sent, failed=failed)
