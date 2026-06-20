"""Shared async SMTP email service for lot closures and citation delivery."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib

from ..config import settings

logger = logging.getLogger("quarry.email")


async def send_email(
    to: list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
    from_override: str | None = None,
) -> bool:
    if not settings.smtp_host:
        logger.warning("SMTP not configured -- email not sent: %s", subject)
        return False

    if not to:
        logger.warning("No recipients -- email not sent: %s", subject)
        return False

    from_addr = from_override or settings.smtp_from_address
    if not from_addr:
        logger.warning("No from address configured -- email not sent")
        return False

    from_display = f"{settings.smtp_from_name} <{from_addr}>"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_display
    msg["To"] = ", ".join(to)

    if body_text:
        msg.attach(MIMEText(body_text, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            use_tls=settings.smtp_use_tls,
            start_tls=not settings.smtp_use_tls,
        )
        logger.info("Email sent to %d recipients: %s", len(to), subject)
        return True
    except Exception as e:
        logger.error("Email send failed: %s", e, exc_info=True)
        return False


async def send_lot_closure_notification(
    lot_name: str,
    reason: str,
    recipients: list[str],
    closes_at: str,
    reopens_at: str | None = None,
    school_name: str | None = None,
) -> bool:
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Lot Closed: {lot_name}"

    reopen_line = ""
    if reopens_at:
        reopen_line = f"<p><strong>Expected Reopening:</strong> {reopens_at}</p>"

    body_html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a2744;">Parking Lot Closure Notice</h2>
        <p>This is to inform you that <strong>{lot_name}</strong> at {school}
        has been closed effective <strong>{closes_at}</strong>.</p>
        <p><strong>Reason:</strong> {reason}</p>
        {reopen_line}
        <p>Please make alternative parking arrangements. Vehicles remaining in the
        closed lot may be subject to towing.</p>
        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p>
    </div>
    """

    body_text = (
        f"PARKING LOT CLOSURE NOTICE\n\n"
        f"Lot: {lot_name}\n"
        f"Closed: {closes_at}\n"
        f"Reason: {reason}\n"
    )
    if reopens_at:
        body_text += f"Expected Reopening: {reopens_at}\n"
    body_text += (
        f"\nPlease make alternative parking arrangements.\n"
        f"\n{school} Parking Services"
    )

    return await send_email(recipients, subject, body_html, body_text)


async def send_lot_reopen_notification(
    lot_name: str,
    recipients: list[str],
    school_name: str | None = None,
) -> bool:
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Lot Reopened: {lot_name}"

    body_html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a2744;">Parking Lot Reopened</h2>
        <p><strong>{lot_name}</strong> at {school} has been reopened and is
        available for parking.</p>
        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p>
    </div>
    """

    body_text = (
        f"PARKING LOT REOPENED\n\n"
        f"Lot: {lot_name}\n"
        f"{lot_name} is now open and available for parking.\n"
        f"\n{school} Parking Services"
    )

    return await send_email(recipients, subject, body_html, body_text)


async def send_citation_email(
    recipient_email: str,
    plate: str,
    lot: str,
    violation_label: str,
    fine_amount: str,
    payment_url: str,
    officer_name: str | None = None,
    issued_at: str = "",
    ticket_id: str = "",
    school_name: str | None = None,
) -> bool:
    school = school_name or settings.school_name or "Campus"
    from_addr = settings.citation_from_address or None
    subject = f"Parking Citation Issued — {plate}"

    officer_line = ""
    if officer_name:
        officer_line = f"<p><strong>Issuing Officer:</strong> {officer_name}</p>"

    body_html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a2744;">Parking Citation Notice</h2>
        <p>A parking citation has been issued for vehicle <strong>{plate}</strong>.</p>

        <table style="width: 100%; border-collapse: collapse; margin: 16px 0;">
            <tr><td style="padding: 6px 0; color: #666;">Citation ID</td>
                <td style="padding: 6px 0; font-weight: bold;">{ticket_id}</td></tr>
            <tr><td style="padding: 6px 0; color: #666;">Plate</td>
                <td style="padding: 6px 0; font-family: monospace; font-weight: bold;">{plate}</td></tr>
            <tr><td style="padding: 6px 0; color: #666;">Violation</td>
                <td style="padding: 6px 0;">{violation_label}</td></tr>
            <tr><td style="padding: 6px 0; color: #666;">Location</td>
                <td style="padding: 6px 0;">{lot}</td></tr>
            <tr><td style="padding: 6px 0; color: #666;">Date/Time</td>
                <td style="padding: 6px 0;">{issued_at}</td></tr>
            <tr><td style="padding: 6px 0; color: #666;">Fine Amount</td>
                <td style="padding: 6px 0; font-weight: bold; color: #c0392b;">${fine_amount}</td></tr>
        </table>

        {officer_line}

        <p><a href="{payment_url}"
              style="display: inline-block; padding: 12px 24px; background: #1a2744;
                     color: white; text-decoration: none; border-radius: 6px;
                     font-weight: bold;">Pay Citation Online</a></p>

        <p style="font-size: 13px; color: #666; margin-top: 16px;">
        If you believe this citation was issued in error, you may file an appeal
        through the payment portal above.</p>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p>
    </div>
    """

    body_text = (
        f"PARKING CITATION NOTICE\n\n"
        f"Citation ID: {ticket_id}\n"
        f"Plate: {plate}\n"
        f"Violation: {violation_label}\n"
        f"Location: {lot}\n"
        f"Date/Time: {issued_at}\n"
        f"Fine: ${fine_amount}\n"
    )
    if officer_name:
        body_text += f"Officer: {officer_name}\n"
    body_text += (
        f"\nPay online: {payment_url}\n"
        f"\n{school} Parking Services"
    )

    return await send_email([recipient_email], subject, body_html, body_text, from_override=from_addr)
