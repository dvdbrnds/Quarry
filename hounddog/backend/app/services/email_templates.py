"""Centralized email HTML renderers.

Every email Quarry sends is rendered through this module. Renderers are
**synchronous** pure-string functions so they can be tested without a DB.
Callers load branding (async) and pass the values in.
"""

from __future__ import annotations

from ..config import settings

CATEGORY_COLORS: dict[str, dict[str, str]] = {
    "emergency": {"bg": "#dc2626", "text": "EMERGENCY ALERT", "text_color": "#ffffff"},
    "weather": {"bg": "#d97706", "text": "WEATHER ALERT", "text_color": "#ffffff"},
    "campus_closing": {"bg": "#2563eb", "text": "CAMPUS CLOSING", "text_color": "#ffffff"},
    "parking": {"bg": "#6b7280", "text": "PARKING NOTICE", "text_color": "#ffffff"},
    "general": {"bg": "#6b7280", "text": "CAMPUS NOTICE", "text_color": "#ffffff"},
}


def _category_stripe(category: str | None) -> str:
    if not category or category not in CATEGORY_COLORS:
        return ""
    c = CATEGORY_COLORS[category]
    return (
        f'<div style="background:{c["bg"]};padding:10px 32px;text-align:center;">'
        f'<span style="color:{c["text_color"]};font-size:13px;font-weight:700;'
        f'letter-spacing:1.5px;">{c["text"]}</span>'
        '</div>'
    )


def _detail_table(heading: str, rows: list[tuple[str, str, str]]) -> str:
    """Build a styled detail table.

    *rows* is a list of (label, value, extra_style) tuples.
    """
    row_html = ""
    for label, value, extra in rows:
        row_html += (
            '<tr style="border-bottom:1px solid #eee;">'
            f'<td style="padding:10px 16px;color:#666;font-size:14px;">{label}</td>'
            f'<td style="padding:10px 16px;font-size:14px;{extra}">{value}</td></tr>'
        )
    return (
        '<table style="width:100%;border-collapse:collapse;background:#f8f9fa;'
        'border-radius:8px;margin:20px 0;">'
        '<tr><td colspan="2" style="padding:12px 16px 4px;font-size:11px;color:#999;'
        f'text-transform:uppercase;letter-spacing:1px;">{heading}</td></tr>'
        f'{row_html}'
        '</table>'
    )


def _cta_button(url: str, label: str, color: str = "#16a34a") -> str:
    return (
        '<div style="text-align:center;margin:28px 0;">'
        f'<a href="{url}" style="display:inline-block;padding:16px 40px;'
        f'background:{color};color:#ffffff;text-decoration:none;border-radius:8px;'
        f'font-weight:700;font-size:16px;">{label}</a></div>'
    )


def _heading(text: str, primary: str) -> str:
    return f'<h2 style="color:{primary};margin:0 0 8px;font-size:20px;">{text}</h2>'


def _para(text: str) -> str:
    return f'<p style="color:#333;font-size:15px;line-height:1.6;">{text}</p>'


def _small(text: str) -> str:
    return f'<p style="font-size:13px;color:#666;text-align:center;">{text}</p>'


# ---------------------------------------------------------------------------
# Core render function
# ---------------------------------------------------------------------------

def render_email(
    heading: str,
    body_html: str,
    *,
    school_name: str = "",
    category: str | None = None,
    footer_extra: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
) -> str:
    """Wrap *body_html* in the full branded email shell with optional category stripe."""
    from .email import email_shell

    stripe = _category_stripe(category)
    return email_shell(
        school_name or "Campus",
        body_html,
        footer_extra,
        primary=primary,
        accent=accent,
        brand_name=brand_name,
        has_logo=has_logo,
        category_stripe_html=stripe,
    )


# ---------------------------------------------------------------------------
# Alert email
# ---------------------------------------------------------------------------

def render_alert_email(
    category: str,
    subject: str,
    body_text: str,
    *,
    unsubscribe_url: str | None = None,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    inner = (
        _heading(subject, primary)
        + f'<div style="color:#333;font-size:15px;line-height:1.7;white-space:pre-wrap;">'
        f'{body_text}</div>'
    )
    footer_extra = ""
    if unsubscribe_url:
        footer_extra = (
            f'<p style="font-size:11px;color:#aaa;margin:0 0 8px;">'
            f'<a href="{unsubscribe_url}" style="color:#aaa;text-decoration:underline;">'
            f'Unsubscribe from alerts</a></p>'
        )
    html = render_email(
        subject, inner,
        school_name=school_name, category=category,
        footer_extra=footer_extra,
        primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )
    plain = f"{body_text}"
    if unsubscribe_url:
        plain += f"\n\nUnsubscribe: {unsubscribe_url}"
    return html, plain


# ---------------------------------------------------------------------------
# Lot closure / reopen
# ---------------------------------------------------------------------------

def render_lot_closure_email(
    lot_name: str,
    reason: str,
    closes_at: str,
    *,
    reopens_at: str | None = None,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    rows: list[tuple[str, str, str]] = [
        ("Lot", lot_name, "font-weight:600;"),
        ("Reason", reason, ""),
    ]
    if reopens_at:
        rows.append(("Expected Reopening", reopens_at, "font-weight:600;"))

    inner = (
        _heading("Parking Lot Closure", primary)
        + _para(
            f'This is to inform you that <strong>{lot_name}</strong> at {school} '
            f'has been closed effective <strong>{closes_at}</strong>.'
        )
        + _detail_table("Closure Details", rows)
        + '<p style="color:#333;font-size:14px;line-height:1.6;">Please make alternative '
        'parking arrangements. Vehicles remaining in the closed lot may be subject to towing.</p>'
    )
    html = render_email(
        "Parking Lot Closure", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"PARKING LOT CLOSURE NOTICE\n\n"
        f"Lot: {lot_name}\n"
        f"Closed: {closes_at}\n"
        f"Reason: {reason}\n"
    )
    if reopens_at:
        plain += f"Expected Reopening: {reopens_at}\n"
    plain += (
        f"\nPlease make alternative parking arrangements.\n"
        f"\n{school} {department_name}"
    )
    return html, plain


def render_lot_reopen_email(
    lot_name: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    inner = (
        _heading("Parking Lot Reopened", primary)
        + _para(
            f'<strong>{lot_name}</strong> at {school} has been reopened and is '
            'available for parking.'
        )
        + '<div style="text-align:center;margin:24px 0;">'
        '<span style="display:inline-block;padding:10px 24px;background:#dcfce7;color:#166534;'
        'border-radius:8px;font-weight:600;font-size:15px;">Lot Open</span>'
        '</div>'
    )
    html = render_email(
        "Parking Lot Reopened", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"PARKING LOT REOPENED\n\n"
        f"Lot: {lot_name}\n"
        f"{lot_name} is now open and available for parking.\n"
        f"\n{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Citation
# ---------------------------------------------------------------------------

def render_citation_email(
    plate: str,
    ticket_id: str,
    violation_label: str,
    lot: str,
    issued_at: str,
    fine_amount: str,
    payment_url: str,
    *,
    officer_name: str | None = None,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    rows: list[tuple[str, str, str]] = [
        ("Citation ID", ticket_id, "font-weight:600;"),
        ("Plate", plate, "font-family:monospace;font-weight:600;"),
        ("Violation", violation_label, ""),
        ("Location", lot, ""),
        ("Date/Time", issued_at, ""),
    ]
    if officer_name:
        rows.append(("Officer", officer_name, ""))
    rows.append(("Fine Amount", f"${fine_amount}", "font-weight:700;color:#dc2626;font-size:16px;"))

    inner = (
        _heading("Parking Citation Notice", primary)
        + _para(
            f'A parking citation has been issued for vehicle '
            f'<strong style="font-family:monospace;">{plate}</strong>.'
        )
        + _detail_table("Citation Details", rows)
        + _cta_button(payment_url, "Pay Citation Online", primary)
        + _small(
            'A processing fee will be added at checkout for online payments. '
            'If you believe this citation was issued in error, you may file '
            'an appeal through the payment portal above.'
        )
    )
    html = render_email(
        "Parking Citation Notice", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"PARKING CITATION NOTICE\n\n"
        f"Citation ID: {ticket_id}\n"
        f"Plate: {plate}\n"
        f"Violation: {violation_label}\n"
        f"Location: {lot}\n"
        f"Date/Time: {issued_at}\n"
        f"Fine: ${fine_amount}\n"
    )
    if officer_name:
        plain += f"Officer: {officer_name}\n"
    plain += (
        f"\nPay online: {payment_url}\n"
        f"\nNote: A processing fee will be added at checkout for online payments.\n"
        f"\n{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Lottery selection
# ---------------------------------------------------------------------------

def render_lottery_selection_email(
    first_name: str,
    permit_type_label: str,
    price: str,
    deadline: str,
    portal_url: str,
    *,
    assigned_lot: str | None = None,
    lot_assignments: list[str] | None = None,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"
    has_price = price and price != "0" and price != "0.00"

    lots = [str(x).strip() for x in (lot_assignments or []) if str(x).strip()]
    lots_display = ", ".join(lots) if lots else (assigned_lot or "")

    rows: list[tuple[str, str, str]] = [
        ("Permit Type", permit_type_label, "font-weight:600;"),
    ]
    if lots_display:
        rows.append(("Allowed Lot(s)", lots_display, "font-weight:600;"))
    if has_price:
        rows.append(("Permit Fee", f"${price}", "font-weight:600;"))
    rows.append(("Accept By", deadline, "font-weight:600;color:#dc2626;"))

    payment_note = " and complete payment" if has_price else ""

    inner = (
        _heading(f"Congratulations, {first_name}!", primary)
        + f'<p style="color:#333;font-size:15px;line-height:1.6;margin:0 0 20px;">'
        f'You\'ve been selected for a <strong>{permit_type_label}</strong> parking permit.</p>'
        + _detail_table("Permit Details", rows)
        + f'<p style="color:#333;font-size:14px;line-height:1.6;margin:0 0 24px;">'
        f'Log in to the student parking portal to accept your offer{payment_note}. '
        f'If you do not respond by <strong>{deadline}</strong>, your spot will be released '
        'to the next student on the waitlist.</p>'
        + _cta_button(portal_url, "Accept &amp; Pay Now", "#16a34a")
        + _small(
            "Don't want this permit? You can decline from the portal and your "
            "spot will go to the next student."
        )
    )
    html = render_email(
        f"Congratulations, {first_name}!", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"CONGRATULATIONS, {first_name.upper()}!\n\n"
        f"You've been selected for a {permit_type_label} parking permit.\n\n"
        f"Permit Type: {permit_type_label}\n"
    )
    if lots_display:
        plain += f"Allowed Lot(s): {lots_display}\n"
    if has_price:
        plain += f"Permit Fee: ${price}\n"
    plain += (
        f"Accept By: {deadline}\n\n"
        f"Log in to accept your offer: {portal_url}\n\n"
        f"If you do not respond by {deadline}, your spot will be released.\n\n"
        f"{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Permit Confirmation (post-purchase)
# ---------------------------------------------------------------------------

def render_permit_confirmation_email(
    student_name: str,
    permit_type_label: str,
    permit_number: str,
    plate: str,
    lot_assignment: str,
    start_date: str,
    end_date: str,
    portal_url: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"
    first_name = student_name.split()[0] if student_name else "Student"

    rows: list[tuple[str, str, str]] = [
        ("Permit", f"{permit_type_label} ({permit_number})", "font-weight:600;"),
        ("Vehicle", plate, "font-weight:600;font-family:monospace;"),
    ]
    if lot_assignment:
        rows.append(("Lot(s)", lot_assignment, "font-weight:600;"))
    rows.append(("Valid", f"{start_date} — {end_date}", ""))

    inner = (
        _heading(f"Permit Issued, {first_name}!", primary)
        + f'<p style="color:#333;font-size:15px;line-height:1.6;margin:0 0 20px;">'
        f'Your <strong>{permit_type_label}</strong> parking permit is now active.</p>'
        + _detail_table("Your Permit", rows)
        + f'<p style="color:#333;font-size:14px;line-height:1.6;margin:0 0 24px;">'
        f'Your vehicle is now registered in the system. Park in your assigned lot(s) and '
        f'display your plate clearly. You can manage your permit (including vehicle changes) '
        f'from the student portal.</p>'
        + _cta_button(portal_url, "View My Permit", primary)
        + _small("Keep this email for your records.")
    )
    html = render_email(
        f"Permit Issued, {first_name}!", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"PERMIT ISSUED — {first_name}\n\n"
        f"Your {permit_type_label} parking permit is now active.\n\n"
        f"Permit: {permit_type_label} ({permit_number})\n"
        f"Vehicle: {plate}\n"
    )
    if lot_assignment:
        plain += f"Lot(s): {lot_assignment}\n"
    plain += (
        f"Valid: {start_date} — {end_date}\n\n"
        f"View your permit: {portal_url}\n\n"
        f"{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Renewal
# ---------------------------------------------------------------------------

def render_renewal_email(
    name: str,
    permit_type: str,
    lot_assignment: str,
    renew_url: str,
    decline_url: str,
    portal_url: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"
    type_label = permit_type.replace("_", " ").title()

    inner = (
        _heading("Parking Permit Renewal", primary)
        + _para(f'Hello {name},')
        + _para(
            f'Your <strong>{type_label}</strong> parking permit '
            f'(lots: {lot_assignment}) expires on <strong>June 30</strong>.'
        )
        + '<p style="color:#333;font-size:14px;line-height:1.6;">All faculty/staff parking permits '
        'expire annually on June 30 and must be renewed for the upcoming year. Please let us '
        'know if you\'d like to keep your permit by clicking one of the buttons below.</p>'
        '<table role="presentation" cellspacing="0" cellpadding="0" '
        'style="margin:28px auto;text-align:center;">'
        '<tr>'
        '<td style="padding-right:12px;">'
        f'<a href="{renew_url}" style="display:inline-block;padding:16px 32px;background:#16a34a;'
        'color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:15px;">'
        'Yes, Renew My Permit</a></td>'
        '<td style="padding-right:12px;">'
        f'<a href="{decline_url}" style="display:inline-block;padding:16px 32px;background:#dc2626;'
        'color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:15px;">'
        'No, I Don\'t Need It</a></td>'
        '<td>'
        f'<a href="{portal_url}" style="display:inline-block;padding:16px 32px;background:{primary};'
        'color:#ffffff;text-decoration:none;border-radius:8px;font-weight:700;font-size:15px;">'
        'Add/Manage Vehicles</a></td>'
        '</tr></table>'
        '<div style="background:#f8f9fa;border-radius:8px;padding:16px 20px;margin:20px 0;">'
        '<p style="font-size:13px;color:#666;margin:0 0 8px;">No payment is required. '
        'Clicking &ldquo;Yes&rdquo; will automatically renew your permit through June 30 of '
        'next year with the same lot assignment.</p>'
        '<p style="font-size:13px;color:#666;margin:0 0 8px;">If you need to update your '
        'license plate, you can change it during the renewal process.</p>'
        '<p style="font-size:13px;color:#666;margin:0;">If you do not respond by June 30, '
        'your permit will expire and your spot will be released.</p>'
        '</div>'
    )
    html = render_email(
        "Parking Permit Renewal", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"PARKING PERMIT RENEWAL \u2014 ACTION REQUIRED\n\n"
        f"Hello {name},\n\n"
        f"Your {permit_type} parking permit (lots: {lot_assignment}) "
        f"expires on June 30.\n\n"
        f"All faculty/staff permits expire annually on June 30.\n\n"
        f"To RENEW your permit, visit: {renew_url}\n\n"
        f"To DECLINE (you no longer need a permit), visit: {decline_url}\n\n"
        f"No payment is required for renewal.\n"
        f"If you do not respond by June 30, your permit will expire.\n\n"
        f"To add or manage vehicles, visit: {portal_url}\n\n"
        f"{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Escalation: conduct referral (Maxient)
# ---------------------------------------------------------------------------

def render_conduct_referral_email(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
    ticket_ids: list[str],
    threshold: int,
    detail_url: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    rows: list[tuple[str, str, str]] = [
        ("Student", f"{student_name or 'Unknown'} ({student_id})", "font-weight:600;"),
        ("Email", student_email or "Unknown", ""),
        ("License Plate", plate, "font-family:monospace;font-weight:600;"),
        ("Unpaid Violations", str(ticket_count), "font-weight:600;color:#dc2626;"),
        ("Threshold", str(threshold), ""),
    ]
    ticket_list = "".join(
        f'<li style="font-size:14px;padding:2px 0;">{tid}</li>' for tid in ticket_ids
    )

    inner = (
        _heading("Automatic Conduct Referral", primary)
        + _detail_table("Student Details", rows)
        + f'<p style="color:#333;font-size:14px;font-weight:600;margin:16px 0 4px;">Ticket IDs:</p>'
        f'<ul style="margin:0 0 20px;padding-left:20px;color:#333;">{ticket_list}</ul>'
        + _small(
            f'This referral was generated automatically when the student exceeded '
            f'{threshold} unpaid parking violations.'
        )
        + _cta_button(detail_url, "View Details", primary)
    )
    html = render_email(
        "Automatic Conduct Referral", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"AUTOMATIC CONDUCT REFERRAL\n\n"
        f"Student: {student_name or 'Unknown'} ({student_id})\n"
        f"Email: {student_email or 'Unknown'}\n"
        f"Plate: {plate}\n"
        f"Unpaid Violations: {ticket_count}\n"
        f"Threshold: {threshold}\n\n"
        f"Ticket IDs: {', '.join(ticket_ids)}\n\n"
        f"View details: {detail_url}\n\n"
        f"{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Escalation: registration hold (student notification)
# ---------------------------------------------------------------------------

def render_hold_student_email(
    student_name: str | None,
    ticket_count: int,
    pay_url: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    inner = (
        _heading("Registration Hold Notice", primary)
        + _para(f'Dear {student_name or "Student"},')
        + '<p style="color:#333;font-size:15px;line-height:1.6;">A hold has been placed on your '
        f'university account due to <strong>{ticket_count} unpaid parking violations</strong>. '
        'You will be unable to register for classes until all outstanding parking fines are paid.</p>'
        + _cta_button(pay_url, "Pay Citations Now", primary)
        + _small('If you believe this is in error, please contact the Parking Office.')
    )
    html = render_email(
        "Registration Hold Notice", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"REGISTRATION HOLD NOTICE\n\n"
        f"Dear {student_name or 'Student'},\n\n"
        f"A hold has been placed on your university account due to "
        f"{ticket_count} unpaid parking violations.\n\n"
        f"Pay now: {pay_url}\n\n"
        f"{school} {department_name}"
    )
    return html, plain


# ---------------------------------------------------------------------------
# Escalation: registration hold (admin notification)
# ---------------------------------------------------------------------------

def render_hold_admin_email(
    student_id: str,
    student_name: str | None,
    student_email: str | None,
    plate: str,
    ticket_count: int,
    sis_configured: bool,
    detail_url: str,
    *,
    school_name: str = "",
    primary: str = "",
    accent: str = "",
    brand_name: str | None = None,
    has_logo: bool = False,
    department_name: str = "Parking Authority",
) -> tuple[str, str]:
    primary = primary or settings.brand_primary_color or "#1a2744"
    school = school_name or "Campus"

    rows: list[tuple[str, str, str]] = [
        ("Student", f"{student_name or 'Unknown'} ({student_id})", "font-weight:600;"),
        ("Email", student_email or "Unknown", ""),
        ("Plate", plate, "font-family:monospace;font-weight:600;"),
        ("Unpaid Violations", str(ticket_count), "font-weight:600;color:#dc2626;"),
    ]

    if sis_configured:
        status_badge = (
            '<div style="background:#dcfce7;color:#166534;padding:10px 16px;border-radius:8px;'
            'font-size:14px;font-weight:600;margin:20px 0;">Hold placed via SIS API</div>'
        )
    else:
        status_badge = (
            '<div style="background:#fef2f2;color:#991b1b;padding:10px 16px;border-radius:8px;'
            'font-size:14px;font-weight:600;margin:20px 0;">SIS API not configured &mdash; '
            'please place the hold manually in Banner/Workday</div>'
        )

    inner = (
        _heading("Registration Hold Triggered", primary)
        + _detail_table("Student Details", rows)
        + status_badge
        + _cta_button(detail_url, "View Details", primary)
    )
    html = render_email(
        "Registration Hold Triggered", inner,
        school_name=school, primary=primary, accent=accent,
        brand_name=brand_name, has_logo=has_logo,
    )

    plain = (
        f"REGISTRATION HOLD TRIGGERED\n\n"
        f"Student: {student_name or 'Unknown'} ({student_id})\n"
        f"Email: {student_email or 'Unknown'}\n"
        f"Plate: {plate}\n"
        f"Unpaid Violations: {ticket_count}\n"
        f"SIS hold: {'placed via API' if sis_configured else 'NOT configured \u2014 place manually'}\n\n"
        f"View details: {detail_url}\n\n"
        f"{school} {department_name}"
    )
    return html, plain
