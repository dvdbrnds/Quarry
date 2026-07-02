import logging

from . import AlertChannel, ChannelResult
from ..email import send_email
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
            unsub_url = f"{settings.public_url}/alerts/unsubscribe/{sub.unsubscribe_token}"
            html = f"""
            <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
                <h2 style="color: #1a2744;">{alert.subject}</h2>
                <div style="white-space: pre-wrap;">{alert.body_text}</div>
                <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
                <p style="font-size: 12px; color: #888;">{school} — Quarry Alerts</p>
                <p style="font-size: 11px; color: #aaa;">
                    <a href="{unsub_url}" style="color: #aaa;">Unsubscribe from alerts</a>
                </p>
            </div>
            """
            text_body = f"{alert.body_text}\n\nUnsubscribe: {unsub_url}"
            success = await send_email([sub.email], alert.subject, html, text_body)
            if success:
                sent += 1
            else:
                failed += 1

        return ChannelResult(channel=self.name, sent=sent, failed=failed)
