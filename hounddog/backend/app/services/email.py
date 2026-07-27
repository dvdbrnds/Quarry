"""Shared async SMTP email service with branded templates."""

import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import aiosmtplib
from sqlalchemy import select

from ..config import settings

logger = logging.getLogger("quarry.email")

_FOOTER_BG = "#f5f5f5"

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
                }
                return _cached_branding
    except Exception:
        pass
    return {
        "brand_name": settings.brand_name,
        "primary_color": settings.brand_primary_color,
        "accent_color": settings.brand_accent_color,
        "has_logo": False,
    }


def invalidate_branding_cache():
    global _cached_branding
    _cached_branding = None


def email_shell(
    school: str, inner_html: str, footer_extra: str = "",
    *, primary: str = "", accent: str = "", brand_name: str | None = None,
    has_logo: bool = False, category_stripe_html: str = "",
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
        f'<p style="color:#f5f0e8;margin:6px 0 0;font-size:12px;letter-spacing:0.5px;">{school} Parking Services</p>'
        '</div>'
        f'{category_stripe_html}'
        f'<div style="padding:32px 32px 24px;">{inner_html}</div>'
        f'<div style="background:{_FOOTER_BG};padding:20px 32px;text-align:center;">'
        f'{footer_extra}'
        f'<p style="font-size:12px;color:#999;margin:0;">{school} Parking Services{footer_brand}</p>'
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
    )


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
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    subject = f"Parking Lot Closed: {lot_name}"

    from .email_templates import render_lot_closure_email
    body_html, body_text = render_lot_closure_email(
        lot_name, reason, closes_at,
        reopens_at=reopens_at, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
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
    b = await _load_branding()
    school = school_name or settings.school_name or "Campus"
    first_name = student_name.split()[0] if student_name else "Student"
    subject = f"You\u2019ve Been Selected \u2014 {permit_type_label} Parking Permit"

    from .email_templates import render_lottery_selection_email
    body_html, body_text = render_lottery_selection_email(
        first_name, permit_type_label, price, deadline, portal_url,
        assigned_lot=assigned_lot, school_name=school,
        primary=b["primary_color"], accent=b["accent_color"],
        brand_name=b["brand_name"], has_logo=b["has_logo"],
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
    first_name = student_name.split()[0] if student_name else "Student"
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
        f"{school} Parking Services"
    )
    return await send_email([recipient_email], subject, body_html, body_text)

