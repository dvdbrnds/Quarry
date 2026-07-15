import logging

from . import AlertChannel, ChannelResult
from ..email import send_email, email_shell
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

        school = settings.school_name or "Campus"
        sent = 0
        failed = 0

        for sub in email_recipients:
            unsub_url = f"{settings.student_facing_url}/alerts/unsubscribe/{sub.unsubscribe_token}"
            inner = (
                f'<h2 style="color:#1a2744;margin:0 0 12px;font-size:20px;">{alert.subject}</h2>'
                f'<div style="color:#333;font-size:15px;line-height:1.7;white-space:pre-wrap;">'
                f'{alert.body_text}</div>'
            )
            footer_extra = (
                f'<p style="font-size:11px;color:#aaa;margin:0 0 8px;">'
                f'<a href="{unsub_url}" style="color:#aaa;text-decoration:underline;">'
                f'Unsubscribe from alerts</a></p>'
            )
            html = email_shell(school, inner, footer_extra=footer_extra)
            text_body = f"{alert.body_text}\n\nUnsubscribe: {unsub_url}"
            success = await send_email([sub.email], alert.subject, html, text_body)
            if success:
                sent += 1
            else:
                failed += 1

        return ChannelResult(channel=self.name, sent=sent, failed=failed)
