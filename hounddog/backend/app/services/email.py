"""Shared async SMTP email service with branded templates."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select

from ..config import settings

logger = logging.getLogger("quarry.email")

_FOOTER_BG = "#f5f5f5"


def extract_first_name(full_name: str) -> str:
    """Extract a first name from various name formats.

    Handles:
      - "First Last" → "First"
      - "Last, First" → "First"
      - "Last, First Middle" → "First"
      - "First" → "First"
      - Strips trailing commas/punctuation from naive splits
    """
    if not full_name or not full_name.strip():
        return "Student"
    name = full_name.strip()
    if "," in name:
        parts = name.split(",", 1)
        after_comma = parts[1].strip()
        if after_comma:
            return after_comma.split()[0]
        return parts[0].strip().split()[0]
    return name.split()[0].rstrip(",")

_cached_branding: dict | None = None


async def _load_branding() -> dict:
    """Read branding from the database, with a module-level cache."""
    global _cached_branding
    if _cached_branding is not None:
        return _cached_branding
    try:
        from ..database import async_session
        from ..models.branding_settings import BrandingSettings
        async with async_session() as session:
            result = await session.execute(select(BrandingSettings).where(BrandingSettings.id == 1))
            bs = result.scalar()
            if bs:
                _cached_branding = {
                    "brand_name": bs.brand_name if bs.brand_name is not None else settings.brand_name,
                    "primary_color": bs.primary_color or settings.brand_primary_color,
                    "accent_color": bs.accent_color or settings.brand_accent_color,
                    "has_logo": bs.logo_data is not None and len(bs.logo_data) > 0,
                    "department_name": bs.department_name or "Parking Authority",
                }
                return _cached_branding
    except Exception:
        pass
    return {
        "brand_name": settings.brand_name,
        "primary_color": settings.brand_primary_color,
        "accent_color": settings.brand_accent_color,
        "has_logo": False,
        "department_name": "Parking Authority",
    }


def invalidate_branding_cache():
    global _cached_branding
    _cached_branding = None


def email_shell(
    school: str, inner_html: str, footer_extra: str = "",
    *, primary: str = "", accent: str = "", brand_name: str | None = None,
    has_logo: bool = False, category_stripe_html: str = "",
    department_name: str = "Parking Authority",
) -> str:
    """Wrap inner content in the branded email shell.

    *category_stripe_html* is an optional colored bar injected between the
    header and the body (used by alert emails to indicate severity).
    """
    primary = primary or settings.brand_primary_color or "#1a2744"
    accent = accent or settings.brand_accent_color or "#c9a84c"
    if brand_name is None:
        brand_name = settings.brand_name or ""

    if has_logo:
        logo_url = f"{settings.public_url}/api/branding/logo"
        logo_html = (
            f'<img src="{logo_url}" alt="{brand_name or school}" '
            'style="max-height:48px;max-width:280px;margin:0 auto;" />'
        )
    elif brand_name:
        logo_html = (
            f'<h1 style="color:{accent};margin:0;font-size:22px;'
            f'letter-spacing:1px;font-weight:700;">{brand_name.upper()}</h1>'
        )
    else:
        logo_html = ""

    footer_brand = f" &middot; Powered by {brand_name}" if brand_name else ""

    return (
        '<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',sans-serif;'
        'max-width:600px;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;">'
        f'<div style="background:{primary};padding:28px 32px;text-align:center;">'
        f'{logo_html}'
        f'<p style="color:#f5f0e8;margin:6px 0 0;font-size:12px;letter-spacing:0.5px;">{school} {department_name}</p>'
        '</div>'
        f'{category_stripe_html}'
        f'<div style="padding:32px 32px 24px;">{inner_html}</div>'
        f'<div style="background:{_FOOTER_BG};padding:20px 32px;text-align:center;">'
        f'{footer_extra}'
        f'<p style="font-size:12px;color:#999;margin:0;">{school} {department_name}{footer_brand}</p>'
        '</div>'
        '</div>'
    )


async def branded_email_shell(school: str, inner_html: str, footer_extra: str = "") -> str:
    """Async wrapper: loads branding from DB then builds the email shell."""
    b = await _load_branding()
    return email_shell(
        school, inner_html, footer_extra,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )


async def get_department_name() -> str:
    """Get the configured department name from branding settings."""
    b = await _load_branding()
    return b.get("department_name", "Parking Authority")


async def send_email(
    to: list[str],
    subject: str,
    body_html: str,
    body_text: str | None = None,
    from_override: str | None = None,
) -> bool:
    if not settings.smtp_host:
        logger.error("SMTP not configured -- email not sent to %s: %s", ", ".join(to), subject)
        from .notification_health import stats
        for r in to:
            stats.record_email_failure(r, subject, "SMTP not configured")
        return False

    if not to:
        logger.warning("No recipients -- email not sent: %s", subject)
        return False

    from_addr = from_override or settings.smtp_from_address
    if not from_addr:
        logger.error("No from address configured -- email not sent: %s", subject)
        from .notification_health import stats
        for r in to:
            stats.record_email_failure(r, subject, "No from address configured")
        return False

    branding = await _load_branding()
    brand_name = branding.get("brand_name") or ""
    school = settings.school_name or ""
    if brand_name and school:
        display_name = f"{school} {brand_name}"
    elif school:
        display_name = f"{school} Parking"
    elif brand_name:
        display_name = brand_name
    else:
        display_name = settings.smtp_from_name
    from_display = f"{display_name} <{from_addr}>"

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
            timeout=10,
        )
        logger.info("Email sent to %d recipients: %s", len(to), subject)
        from .notification_health import stats
        for r in to:
            stats.record_email_success(r, subject)
        return True
    except Exception as e:
        logger.error("Email send failed to %s: %s", ", ".join(to), e, exc_info=True)
        from .notification_health import stats
        for r in to:
            stats.record_email_failure(r, subject, str(e))
        return False


async def send_lot_closure_notification(
    lot_name: str,
    reason: str,
    recipients: list[str],
    closes_at: str,
    reopens_at: str | None = None,
    school_name: str | None = None,
) -> bool:
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Lot Closed: {lot_name}"

    from .email_templates import render_lot_closure_email
    body_html, body_text = render_lot_closure_email(
        lot_name, reason, closes_at,
        reopens_at=reopens_at, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )
    return await send_email(recipients, subject, body_html, body_text)


def build_preference_footer(token: str) -> str:
    """Build an HTML footer linking to the notification preferences page."""
    if not token:
        return ""
    url = f"{settings.student_facing_url}/notifications/{token}"
    return (
        f'<p style="font-size: 11px; color: #aaa; margin-top: 8px;">'
        f'<a href="{url}" style="color: #aaa;">Manage notification preferences</a></p>'
    )


async def send_lot_reopen_notification(
    lot_name: str,
    recipients: list[str],
    school_name: str | None = None,
) -> bool:
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Lot Reopened: {lot_name}"

    from .email_templates import render_lot_reopen_email
    body_html, body_text = render_lot_reopen_email(
        lot_name, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
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
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    from_addr = settings.citation_from_address or None
    subject = f"Parking Citation Issued \u2014 {plate}"

    from .email_templates import render_citation_email
    body_html, body_text = render_citation_email(
        plate, ticket_id, violation_label, lot, issued_at, fine_amount, payment_url,
        officer_name=officer_name, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
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
    lot_assignments: list[str] | None = None,
    school_name: str | None = None,
) -> bool:
    if not settings.selection_emails_enabled:
        logger.info("Selection email suppressed (disabled) for %s: %s", recipient_email, permit_type_label)
        return True
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    first_name = extract_first_name(student_name)
    subject = f"You\u2019ve Been Selected \u2014 {permit_type_label} Parking Permit"

    from .email_templates import render_lottery_selection_email
    body_html, body_text = render_lottery_selection_email(
        first_name, permit_type_label, price, deadline, portal_url,
        assigned_lot=assigned_lot,
        lot_assignments=lot_assignments,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
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
    portal_url: str | None = None,
) -> bool:
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    portal = portal_url or (settings.student_facing_url.rstrip("/") + "/employee-parking")
    subject = "Parking Permit Renewal \u2014 Action Required by June 30"

    from .email_templates import render_renewal_email
    body_html, body_text = render_renewal_email(
        name, permit_type, lot_assignment, renew_url, decline_url, portal,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )
    return await send_email([recipient_email], subject, body_html, body_text)


async def send_permit_confirmation_email(
    recipient_email: str,
    student_name: str,
    permit_type_label: str,
    permit_number: str,
    plate: str,
    lot_assignment: str,
    start_date: str,
    end_date: str,
) -> bool:
    """Send a permit-issued confirmation email after successful purchase."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    portal_url = settings.student_facing_url.rstrip("/") + "/parking"
    subject = f"Parking Permit Issued — {permit_type_label}"

    from .email_templates import render_permit_confirmation_email
    body_html, body_text = render_permit_confirmation_email(
        student_name, permit_type_label, permit_number, plate, lot_assignment,
        start_date, end_date, portal_url,
        school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
        department_name=b.get("department_name", "Parking Authority"),
    )
    return await send_email([recipient_email], subject, body_html, body_text)


async def send_waitlist_position_update_email(
    recipient_email: str,
    student_name: str,
    permit_type_label: str,
    new_position: int,
    total_waitlisted: int,
    school_name: str | None = None,
) -> bool:
    """Send a waitlist position update email when a student moves up."""
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    primary = b["primary_color"]
    first_name = extract_first_name(student_name)
    subject = f"Waitlist Update — {permit_type_label}"

    inner = (
        f'<h2 style="color:{primary};margin:0 0 8px;font-size:20px;">'
        f'Waitlist Update &mdash; {permit_type_label}</h2>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name}, '
        f'good news! Your position on the <strong>{permit_type_label}</strong> waitlist has moved up.</p>'
        '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;border-radius:8px;margin:20px 0;">'
        '<tr><td colspan="2" style="padding:12px 16px 4px;font-size:11px;color:#999;'
        'text-transform:uppercase;letter-spacing:1px;">Updated Waitlist Position</td></tr>'
        '<tr style="border-bottom:1px solid #eee;">'
        '<td style="padding:10px 16px;color:#666;font-size:14px;">Your Position</td>'
        f'<td style="padding:10px 16px;font-weight:600;font-size:16px;color:{primary};">#{new_position}</td></tr>'
        '<tr>'
        '<td style="padding:10px 16px;color:#666;font-size:14px;">Total Waitlisted</td>'
        f'<td style="padding:10px 16px;font-size:14px;">{total_waitlisted}</td></tr>'
        '</table>'
        '<p style="color:#333;font-size:14px;line-height:1.6;">A spot ahead of you has been filled or declined, '
        'moving you closer to the front of the line. If a permit becomes available, '
        'you will receive an offer via email.</p>'
        '<div style="background:#f8f9fa;border-radius:8px;padding:14px 20px;margin:20px 0;text-align:center;">'
        '<p style="font-size:14px;color:#666;margin:0;">No action is required at this time.</p>'
        '</div>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"WAITLIST UPDATE — {permit_type_label}\n\n"
        f"Dear {first_name},\n\n"
        f"Good news! Your position on the {permit_type_label} waitlist has moved up.\n\n"
        f"New position: #{new_position} out of {total_waitlisted}\n\n"
        f"A spot ahead of you has been filled or declined, moving you closer to "
        f"the front of the line. If a permit becomes available, you will receive "
        f"an offer via email.\n\n"
        f"You do not need to take any action at this time.\n\n"
        f"{school} {b.get('department_name', 'Parking Authority')}"
    )
    return await send_email([recipient_email], subject, body_html, body_text)


async def send_sponsor_approval_email(
    sponsor_email: str,
    sponsor_name: str,
    visitor_name: str,
    company_name: str,
    plate: str,
    work_description: str,
    start_date: str,
    end_date: str,
    approval_url: str,
    student_name: str = "",
) -> bool:
    """Send a vendor parking permit approval request to a department sponsor."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    primary = b["primary_color"]
    department = b.get("department_name", "Parking Authority")
    subject = f"Vendor Parking Permit Approval - {company_name}"

    inner = (
        f'<h2 style="color:{primary};margin:0 0 16px;">Vendor Parking Permit — Approval Required</h2>'
        f'<p>Hello {sponsor_name},</p>'
        f'<p>A vendor has requested a long-term parking permit and listed you as their campus sponsor. '
        f'Please review the details below and approve or deny the request.</p>'
        f'<table style="width:100%;border-collapse:collapse;margin:16px 0;background:#f9f9f9;border-radius:8px;">'
        f'<tr><td style="padding:10px 16px;color:#666;">Visitor</td><td style="padding:10px 16px;font-weight:600;">{visitor_name}</td></tr>'
        f'<tr><td style="padding:10px 16px;color:#666;">Company</td><td style="padding:10px 16px;font-weight:600;">{company_name}</td></tr>'
        f'{f\'<tr><td style="padding:10px 16px;color:#666;">Student</td><td style="padding:10px 16px;font-weight:600;">{student_name}</td></tr>\' if student_name else ""}'
        f'<tr><td style="padding:10px 16px;color:#666;">Vehicle</td><td style="padding:10px 16px;font-weight:600;">{plate}</td></tr>'
        f'<tr><td style="padding:10px 16px;color:#666;">Work</td><td style="padding:10px 16px;">{work_description or "Not specified"}</td></tr>'
        f'<tr><td style="padding:10px 16px;color:#666;">Duration</td><td style="padding:10px 16px;font-weight:600;">{start_date} to {end_date}</td></tr>'
        f'</table>'
        f'<div style="text-align:center;margin:24px 0;">'
        f'<a href="{approval_url}" style="display:inline-block;background:{primary};color:#ffffff;'
        f'padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;">Review &amp; Approve</a>'
        f'</div>'
        f'<p style="color:#999;font-size:13px;">This link expires in 7 days. If you did not expect this request, you can ignore this email.</p>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"VENDOR PARKING PERMIT — APPROVAL REQUIRED\n\n"
        f"Hello {sponsor_name},\n\n"
        f"A vendor has requested a long-term parking permit and listed you as their campus sponsor.\n\n"
        f"Visitor: {visitor_name}\n"
        f"Company: {company_name}\n"
        f"{f'Student: {student_name}\n' if student_name else ''}"
        f"Vehicle: {plate}\n"
        f"Work: {work_description or 'Not specified'}\n"
        f"Duration: {start_date} to {end_date}\n\n"
        f"Review and approve: {approval_url}\n\n"
        f"This link expires in 7 days.\n\n"
        f"{school} {department}"
    )
    return await send_email([sponsor_email], subject, body_html, body_text)


async def send_visitor_confirmation_email(
    recipient_email: str,
    visitor_name: str,
    permit_number: str,
    plate: str,
    start_date: str,
    end_date: str,
) -> bool:
    """Send confirmation to a visitor after their permit is created or approved."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    primary = b["primary_color"]
    department = b.get("department_name", "Parking Authority")
    subject = f"Visitor Parking Permit - {plate}"

    inner = (
        f'<h2 style="color:{primary};margin:0 0 16px;">Visitor Parking Permit Confirmed</h2>'
        f'<p>Hello {visitor_name},</p>'
        f'<p>Your temporary parking permit has been issued:</p>'
        f'<table style="width:100%;border-collapse:collapse;margin:16px 0;">'
        f'<tr><td style="padding:8px 0;color:#666;">Permit #</td><td style="padding:8px 0;font-weight:600;">{permit_number or "—"}</td></tr>'
        f'<tr><td style="padding:8px 0;color:#666;">Vehicle</td><td style="padding:8px 0;font-weight:600;">{plate}</td></tr>'
        f'<tr><td style="padding:8px 0;color:#666;">Valid</td><td style="padding:8px 0;font-weight:600;">{start_date} — {end_date}</td></tr>'
        f'</table>'
        f'<p style="color:#666;font-size:14px;">No physical permit is required. Your license plate has been registered in our system.</p>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"VISITOR PARKING PERMIT CONFIRMED\n\n"
        f"Hello {visitor_name},\n\n"
        f"Your temporary parking permit has been issued.\n\n"
        f"Permit #: {permit_number or 'N/A'}\n"
        f"Vehicle: {plate}\n"
        f"Valid: {start_date} - {end_date}\n\n"
        f"No physical permit is required. Your license plate has been registered in our system.\n\n"
        f"{school} {department}"
    )
    return await send_email([recipient_email], subject, body_html, body_text)


async def send_payment_link_email(
    recipient_email: str,
    recipient_name: str,
    permit_type_label: str,
    permit_number: str,
    amount_display: str,
    checkout_url: str,
) -> bool:
    """Send a payment link email for an admin-issued permit pending payment."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    primary = b["primary_color"]
    first_name = extract_first_name(recipient_name)
    department = b.get("department_name", "Parking Authority")
    subject = f"Payment Required — {permit_type_label} Parking Permit"

    inner = (
        f'<h2 style="color:{primary};margin:0 0 8px;font-size:20px;">'
        f'Parking Permit — Payment Required</h2>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name},</p>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">'
        f'A <strong>{permit_type_label}</strong> parking permit (#{permit_number}) has been issued to you '
        f'by the {department}. Please complete payment of <strong>{amount_display}</strong> to activate it.</p>'
        '<div style="text-align:center;margin:28px 0;">'
        f'<a href="{checkout_url}" style="display:inline-block;background:{primary};'
        'color:#fff;padding:14px 36px;border-radius:6px;text-decoration:none;'
        f'font-size:16px;font-weight:600;">Pay {amount_display}</a></div>'
        '<p style="color:#666;font-size:13px;line-height:1.5;">'
        'Your permit will remain inactive until payment is received. '
        'If you have questions, please contact the parking office.</p>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"PARKING PERMIT — PAYMENT REQUIRED\n\n"
        f"Dear {first_name},\n\n"
        f"A {permit_type_label} parking permit (#{permit_number}) has been issued to you "
        f"by the {department}. Please complete payment of {amount_display} to activate it.\n\n"
        f"Pay here: {checkout_url}\n\n"
        f"Your permit will remain inactive until payment is received.\n\n"
        f"{school} {department}"
    )
    return await send_email([recipient_email], subject, body_html, body_text)


async def send_multi_vehicle_request_email(
    admin_email: str,
    student_name: str,
    student_email: str,
    plate: str,
    permit_number: str,
    approval_url: str = "",
) -> bool:
    """Notify admin/chief that a student has requested to add a second vehicle."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    primary = b["primary_color"]
    department = b.get("department_name", "Parking Authority")
    subject = f"Multi-Vehicle Request — {student_name}"

    buttons_html = ""
    if approval_url:
        buttons_html = (
            '<div style="text-align:center;margin:24px 0;">'
            f'<a href="{approval_url}" style="display:inline-block;background:{primary};'
            'color:#fff;padding:14px 36px;border-radius:6px;text-decoration:none;'
            'font-size:16px;font-weight:600;margin-right:12px;">Review &amp; Approve</a>'
            '</div>'
        )

    inner = (
        f'<h2 style="color:{primary};margin:0 0 8px;font-size:20px;">'
        f'Multi-Vehicle Request</h2>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">'
        f'<strong>{student_name}</strong> ({student_email}) has requested to add '
        f'an additional vehicle to their commuter permit.</p>'
        f'<table style="margin:16px 0;font-size:14px;border-collapse:collapse;">'
        f'<tr><td style="padding:4px 12px 4px 0;color:#666;">Permit #</td>'
        f'<td style="padding:4px 0;font-weight:600;">{permit_number}</td></tr>'
        f'<tr><td style="padding:4px 12px 4px 0;color:#666;">Requested Plate</td>'
        f'<td style="padding:4px 0;font-weight:600;">{plate}</td></tr>'
        f'</table>'
        f'{buttons_html}'
        f'<p style="color:#666;font-size:13px;">You can also review this request in the '
        f'admin panel under Permits &rarr; Vehicle Requests.</p>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"MULTI-VEHICLE REQUEST\n\n"
        f"{student_name} ({student_email}) has requested to add an additional "
        f"vehicle to their commuter permit.\n\n"
        f"Permit #: {permit_number}\n"
        f"Requested Plate: {plate}\n\n"
    )
    if approval_url:
        body_text += f"Review and approve: {approval_url}\n\n"
    body_text += (
        f"You can also review this request in the admin panel under Permits > Vehicle Requests.\n\n"
        f"{school} {department}"
    )
    return await send_email([admin_email], subject, body_html, body_text)


async def send_multi_vehicle_decision_email(
    student_email: str,
    student_name: str,
    plate: str,
    approved: bool,
    note: str | None = None,
) -> bool:
    """Notify a student that their multi-vehicle request was approved or denied."""
    b = await _load_branding()
    school = settings.school_name or "Campus"
    primary = b["primary_color"]
    department = b.get("department_name", "Parking Authority")
    first_name = extract_first_name(student_name)

    if approved:
        subject = f"Multi-Vehicle Request Approved — {plate}"
        status_text = "approved"
        detail = (
            f'Your additional vehicle (<strong>{plate}</strong>) has been added to your '
            f'commuter parking permit. It is now active and recognized by our system.'
        )
    else:
        subject = f"Multi-Vehicle Request Denied — {plate}"
        status_text = "denied"
        detail = (
            f'Your request to add vehicle <strong>{plate}</strong> to your commuter '
            f'parking permit has been denied.'
        )
        if note:
            detail += f'<br><br><em>Reason: {note}</em>'

    inner = (
        f'<h2 style="color:{primary};margin:0 0 8px;font-size:20px;">'
        f'Multi-Vehicle Request {status_text.title()}</h2>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">Dear {first_name},</p>'
        f'<p style="color:#333;font-size:15px;line-height:1.6;">{detail}</p>'
        f'<p style="color:#666;font-size:13px;line-height:1.5;">'
        f'If you have questions, please contact the {department}.</p>'
    )
    body_html = await branded_email_shell(school, inner)
    body_text = (
        f"MULTI-VEHICLE REQUEST {status_text.upper()}\n\n"
        f"Dear {first_name},\n\n"
    )
    if approved:
        body_text += (
            f"Your additional vehicle ({plate}) has been added to your commuter "
            f"parking permit. It is now active and recognized by our system.\n\n"
        )
    else:
        body_text += (
            f"Your request to add vehicle {plate} to your commuter parking permit "
            f"has been denied.\n"
        )
        if note:
            body_text += f"Reason: {note}\n\n"
        else:
            body_text += "\n"
    body_text += f"{school} {department}"
    return await send_email([student_email], subject, body_html, body_text)
