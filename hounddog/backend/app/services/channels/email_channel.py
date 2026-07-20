import logging

from . import AlertChannel, ChannelResult
from ..email import send_email, _load_branding
from ..email_templates import render_alert_email
from ...config import settings

logger = logging.getLogger("quarry.channels.email")


class EmailChannel(AlertChannel):
    name = "email"
    emergency_only = False

    def is_configured(self) -> bool:
        return bool(settings.smtp_host and settings.smtp_from_address)

    async def send(self, alert, subscribers) -> ChannelResult:
        email_recipients = [s for s in subscribers if s.email and s.email_enabled]
        if not email_recipients or not alert.subject:
            return ChannelResult(channel=self.name)

        b = await _load_branding()
        school = settings.school_name or "Campus"
        sent = 0
        failed = 0

        for sub in email_recipients:
            unsub_url = f"{settings.student_facing_url}/alerts/unsubscribe/{sub.unsubscribe_token}"
            html, text_body = render_alert_email(
                alert.category, alert.subject, alert.body_text,
                unsubscribe_url=unsub_url, school_name=school,
                primary=b["primary_color"], accent=b["accent_color"],
                brand_name=b["brand_name"], has_logo=b["has_logo"],
            )
            success = await send_email([sub.email], alert.subject, html, text_body)
            if success:
                sent += 1
            else:
                failed += 1

        return ChannelResult(channel=self.name, sent=sent, failed=failed)
