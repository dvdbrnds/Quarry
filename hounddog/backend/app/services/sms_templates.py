"""Centralized SMS message formatters.

Every SMS Quarry sends is formatted through this module for consistent
school-name prefixing and category labeling.
"""

from __future__ import annotations

CATEGORY_PREFIXES: dict[str, str] = {
    "emergency": "EMERGENCY",
    "weather": "WEATHER",
    "campus_closing": "CAMPUS CLOSING",
    "parking": "PARKING",
    "general": "ALERT",
}


def render_alert_sms(
    category: str,
    subject: str,
    body_sms: str,
    *,
    school_name: str = "",
) -> str:
    """Format an alert SMS with a bracketed school+category prefix.

    Emergency alerts get ALL-CAPS prefix: ``[MORAVIAN EMERGENCY] Subject. Body``
    """
    school = (school_name or "CAMPUS").upper()
    prefix = CATEGORY_PREFIXES.get(category, "ALERT")
    return f"[{school} {prefix}] {subject}. {body_sms}"


def render_citation_sms(
    plate: str,
    fine: str,
    payment_url: str,
    *,
    school_name: str = "",
) -> str:
    school = school_name or "Campus"
    return f"{school} Parking: Citation issued for {plate}. Fine: ${fine}. Pay: {payment_url}"


def render_lot_closure_sms(
    lot_name: str,
    reason: str,
    *,
    school_name: str = "",
) -> str:
    school = school_name or "Campus"
    return f"{school} Parking: {lot_name} is CLOSED. {reason}."
