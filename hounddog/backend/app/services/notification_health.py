"""
Notification health monitor.

Tracks notification send attempts and failures in-memory. Provides:
- Startup diagnostics (logged at WARNING when config is missing)
- Runtime counters for sent/failed emails and SMS
- An admin-queryable summary of recent failures
"""

import logging
from collections import deque
from datetime import datetime, timezone
from dataclasses import dataclass, field

from ..config import settings

logger = logging.getLogger("quarry.notifications")

MAX_RECENT_FAILURES = 100


@dataclass
class NotificationFailure:
    timestamp: str
    channel: str
    recipient: str
    subject_or_context: str
    error: str


class NotificationStats:
    def __init__(self):
        self.emails_attempted: int = 0
        self.emails_sent: int = 0
        self.emails_failed: int = 0
        self.sms_attempted: int = 0
        self.sms_sent: int = 0
        self.sms_failed: int = 0
        self.recent_failures: deque[NotificationFailure] = deque(maxlen=MAX_RECENT_FAILURES)

    def record_email_success(self, recipient: str, subject: str):
        self.emails_attempted += 1
        self.emails_sent += 1

    def record_email_failure(self, recipient: str, subject: str, error: str):
        self.emails_attempted += 1
        self.emails_failed += 1
        self.recent_failures.append(NotificationFailure(
            timestamp=datetime.now(timezone.utc).isoformat(),
            channel="email",
            recipient=recipient,
            subject_or_context=subject,
            error=error,
        ))
        logger.error(
            "EMAIL FAILED | to=%s | subject=%s | error=%s",
            recipient, subject, error,
        )

    def record_sms_success(self, recipient: str):
        self.sms_attempted += 1
        self.sms_sent += 1

    def record_sms_failure(self, recipient: str, context: str, error: str):
        self.sms_attempted += 1
        self.sms_failed += 1
        self.recent_failures.append(NotificationFailure(
            timestamp=datetime.now(timezone.utc).isoformat(),
            channel="sms",
            recipient=recipient,
            subject_or_context=context,
            error=error,
        ))
        logger.error(
            "SMS FAILED | to=%s | context=%s | error=%s",
            recipient, context, error,
        )

    def summary(self) -> dict:
        return {
            "emails": {"attempted": self.emails_attempted, "sent": self.emails_sent, "failed": self.emails_failed},
            "sms": {"attempted": self.sms_attempted, "sent": self.sms_sent, "failed": self.sms_failed},
            "recent_failures": [
                {"timestamp": f.timestamp, "channel": f.channel, "recipient": f.recipient,
                 "context": f.subject_or_context, "error": f.error}
                for f in self.recent_failures
            ],
        }


stats = NotificationStats()


def check_notification_config() -> list[str]:
    """Check notification configuration and return list of warnings.

    Call at startup — logs prominently for any missing config.
    """
    warnings: list[str] = []

    if not settings.smtp_host:
        warnings.append("SMTP_HOST not set — email notifications will not be sent")
    elif not settings.smtp_from_address:
        warnings.append("SMTP_FROM_ADDRESS not set — email notifications will not be sent")
    elif not settings.smtp_user or not settings.smtp_password:
        warnings.append("SMTP_USER/SMTP_PASSWORD not set — email auth may fail")

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        warnings.append("TWILIO_ACCOUNT_SID/AUTH_TOKEN not set — SMS notifications will not be sent")
    elif not settings.twilio_from_number:
        warnings.append("TWILIO_FROM_NUMBER not set — SMS notifications will not be sent")

    if warnings:
        logger.warning("=" * 60)
        logger.warning("NOTIFICATION CONFIG WARNINGS (check before go-live):")
        for w in warnings:
            logger.warning("  ⚠ %s", w)
        logger.warning("=" * 60)
    else:
        logger.info("Notification config OK: SMTP and Twilio both configured")

    return warnings
