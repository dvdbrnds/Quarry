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
        {{preference_footer}}
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


def build_preference_footer(token: str) -> str:
    """Build an HTML footer linking to the notification preferences page."""
    if not token:
        return ""
    url = f"{settings.public_url}/notifications/{token}"
    return (
        f'<p style="font-size: 11px; color: #aaa; margin-top: 8px;">'
        f'<a href="{url}" style="color: #aaa;">Manage notification preferences</a></p>'
    )


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


async def send_lottery_selection_email(
    recipient_email: str,
    student_name: str,
    permit_type_label: str,
    price: str,
    deadline: str,
    portal_url: str,
    assigned_lot: str | None = None,
    school_name: str | None = None,
) -> bool:
    school = school_name or settings.school_name or "Campus"
    first_name = student_name.split()[0] if student_name else "Student"
    subject = f"You've Been Selected — {permit_type_label} Parking Permit"

    lot_line = ""
    if assigned_lot:
        lot_line = f'<tr><td style="padding: 8px 0; color: #666; font-size: 14px;">Assigned Lot</td><td style="padding: 8px 0; font-weight: bold; font-size: 14px;">{assigned_lot}</td></tr>'

    price_line = ""
    if price and price != "0" and price != "0.00":
        price_line = f'<tr><td style="padding: 8px 0; color: #666; font-size: 14px;">Permit Fee</td><td style="padding: 8px 0; font-weight: bold; font-size: 14px;">${price}</td></tr>'

    body_html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 600px; margin: 0 auto; background: #ffffff;">
        <div style="background: #1a2744; padding: 24px 32px; text-align: center;">
            <h1 style="color: #c9a84c; margin: 0; font-size: 22px; letter-spacing: 1px;">QUARRY</h1>
            <p style="color: #f5f0e8; margin: 4px 0 0; font-size: 12px;">{school} Parking Services</p>
        </div>

        <div style="padding: 32px;">
            <h2 style="color: #1a2744; margin: 0 0 8px; font-size: 20px;">Congratulations, {first_name}!</h2>
            <p style="color: #333; font-size: 15px; line-height: 1.6; margin: 0 0 20px;">
                You've been selected for a <strong>{permit_type_label}</strong> parking permit.
            </p>

            <table style="width: 100%; border-collapse: collapse; background: #f8f9fa; border-radius: 8px; margin: 20px 0;">
                <tr><td colspan="2" style="padding: 12px 16px 4px; font-size: 11px; color: #999; text-transform: uppercase; letter-spacing: 1px;">Permit Details</td></tr>
                <tr style="border-bottom: 1px solid #eee;"><td style="padding: 8px 16px; color: #666; font-size: 14px;">Permit Type</td><td style="padding: 8px 16px; font-weight: bold; font-size: 14px;">{permit_type_label}</td></tr>
                {lot_line.replace('padding: 8px 0', 'padding: 8px 16px') if lot_line else ''}
                {price_line.replace('padding: 8px 0', 'padding: 8px 16px') if price_line else ''}
                <tr><td style="padding: 8px 16px; color: #666; font-size: 14px;">Accept By</td><td style="padding: 8px 16px; font-weight: bold; color: #dc2626; font-size: 14px;">{deadline}</td></tr>
            </table>

            <p style="color: #333; font-size: 14px; line-height: 1.6; margin: 0 0 24px;">
                Log in to the student parking portal to accept your offer{' and complete payment' if price and price != '0' and price != '0.00' else ''}. 
                If you do not respond by <strong>{deadline}</strong>, your spot will be released to the next student on the waitlist.
            </p>

            <div style="text-align: center; margin: 28px 0;">
                <a href="{portal_url}"
                   style="display: inline-block; padding: 16px 40px; background: #16a34a;
                          color: white; text-decoration: none; border-radius: 8px;
                          font-weight: bold; font-size: 16px;">
                    Accept &amp; Pay Now
                </a>
            </div>

            <p style="font-size: 13px; color: #666; text-align: center;">
                Don't want this permit? You can decline from the portal and your spot will go to the next student.</p>
        </div>

        <div style="background: #f5f0e8; padding: 20px 32px; text-align: center;">
            <p style="font-size: 12px; color: #888; margin: 0;">{school} Parking Services &middot; Powered by Quarry</p>
        </div>
    </div>
    """

    body_text = (
        f"CONGRATULATIONS, {first_name.upper()}!\n\n"
        f"You've been selected for a {permit_type_label} parking permit.\n\n"
        f"Permit Type: {permit_type_label}\n"
    )
    if assigned_lot:
        body_text += f"Assigned Lot: {assigned_lot}\n"
    if price and price != "0" and price != "0.00":
        body_text += f"Permit Fee: ${price}\n"
    body_text += (
        f"Accept By: {deadline}\n\n"
        f"Log in to accept your offer: {portal_url}\n\n"
        f"If you do not respond by {deadline}, your spot will be released.\n\n"
        f"{school} Parking Services"
    )

    return await send_email([recipient_email], subject, body_html, body_text)


async def send_renewal_email(
    recipient_email: str,
    name: str,
    permit_type: str,
    lot_assignment: str,
    end_date: str,
    renew_url: str,
    decline_url: str,
    school_name: str | None = None,
) -> bool:
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Permit Renewal — Action Required by June 30"

    body_html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a2744;">Parking Permit Renewal</h2>
        <p>Hello {name},</p>
        <p>Your <strong>{permit_type}</strong> parking permit
        (lots: {lot_assignment}) expires on <strong>June 30</strong>.</p>
        <p>All faculty/staff parking permits expire annually on June 30 and must
        be renewed for the upcoming year. Please let us know if you'd like to
        keep your permit by clicking one of the buttons below.</p>

        <table role="presentation" cellspacing="0" cellpadding="0" style="margin: 28px 0;">
            <tr>
                <td style="padding-right: 12px;">
                    <a href="{renew_url}"
                       style="display: inline-block; padding: 14px 28px; background: #16a34a;
                              color: white; text-decoration: none; border-radius: 8px;
                              font-weight: bold; font-size: 15px;">
                        Yes, Renew My Permit
                    </a>
                </td>
                <td>
                    <a href="{decline_url}"
                       style="display: inline-block; padding: 14px 28px; background: #dc2626;
                              color: white; text-decoration: none; border-radius: 8px;
                              font-weight: bold; font-size: 15px;">
                        No, I Don't Need It
                    </a>
                </td>
            </tr>
        </table>

        <p style="font-size: 13px; color: #666;">
        No payment is required. Clicking "Yes" will automatically renew your permit
        through June 30 of next year with the same lot assignment.</p>

        <p style="font-size: 13px; color: #666;">
        If you need to update your license plate, click "Yes" first, then contact
        Parking Services to update your plate information.</p>

        <p style="font-size: 13px; color: #666; margin-top: 16px;">
        If you do not respond by June 30, your permit will expire and your spot
        will be released.</p>

        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p>
    </div>
    """

    body_text = (
        f"PARKING PERMIT RENEWAL — ACTION REQUIRED\n\n"
        f"Hello {name},\n\n"
        f"Your {permit_type} parking permit (lots: {lot_assignment}) "
        f"expires on June 30.\n\n"
        f"All faculty/staff permits expire annually on June 30.\n\n"
        f"To RENEW your permit, visit: {renew_url}\n\n"
        f"To DECLINE (you no longer need a permit), visit: {decline_url}\n\n"
        f"No payment is required for renewal.\n"
        f"If you do not respond by June 30, your permit will expire.\n\n"
        f"{school} Parking Services"
    )

    return await send_email([recipient_email], subject, body_html, body_text)

