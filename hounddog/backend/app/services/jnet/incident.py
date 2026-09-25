"""
CJIS incident response — IR-4, IR-6.

Creates incident records and sends email notifications to the
CJIS Information Security Officer (ISO).
"""

import sentry_sdk
import structlog

from ...database import async_session
from ...models.cjis_incident import CJISIncident
from .config import jnet_settings

logger = structlog.get_logger("quarry.cjis.incident")


async def report_cjis_incident(
    *,
    incident_type: str,
    description: str,
    affected_records: int = 0,
    detected_by: str = "system",
) -> CJISIncident | None:
    """
    Create a CJIS incident record and send email notification.

    incident_type: unauthorized_access | data_breach | system_compromise | policy_violation
    """
    try:
        incident = CJISIncident(
            incident_type=incident_type,
            description=description,
            affected_records_count=affected_records,
            detected_by=detected_by,
        )

        async with async_session() as session:
            async with session.begin():
                session.add(incident)

        logger.critical(
            "cjis_incident_created",
            incident_type=incident_type,
            description=description,
            affected_records=affected_records,
        )

        # Send email notification to CJIS ISO
        await _send_incident_email(incident)

        return incident

    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error(
            "cjis_incident_creation_failed",
            incident_type=incident_type,
            error=str(exc),
        )
        return None


async def _send_incident_email(incident: CJISIncident) -> None:
    """Send incident notification email to CJIS ISO."""
    email_addr = jnet_settings.cjis_incident_email
    if not email_addr:
        logger.warning("cjis_incident_email_not_configured")
        return

    try:
        from ...services.email import send_email
        from ...config import settings

        subject = f"[CJIS INCIDENT] {incident.incident_type.upper()} — Quarry Parking System"
        body = (
            f"CJIS Security Incident Report\n"
            f"{'=' * 40}\n\n"
            f"Type: {incident.incident_type}\n"
            f"Detected by: {incident.detected_by}\n"
            f"Timestamp: {incident.timestamp}\n"
            f"Affected records: {incident.affected_records_count}\n\n"
            f"Description:\n{incident.description}\n\n"
            f"{'=' * 40}\n"
            f"This is an automated notification from Quarry ({settings.public_url}).\n"
            f"Per CJIS Security Policy v6.1 IR-6, this incident must be reported\n"
            f"to the PA State Police CJIS ISO within the required timeframe.\n"
        )

        await send_email(
            to=email_addr,
            subject=subject,
            body=body,
        )

        logger.info("cjis_incident_email_sent", to=email_addr)

    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("cjis_incident_email_failed", error=str(exc))
