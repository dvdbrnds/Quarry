"""Format check for US mailing addresses stored as "street, city, ST ZIP" (mirrors frontend AddressFields)."""

import re

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "PR", "VI", "GU", "AS", "MP", "AA", "AE", "AP",
}

_ADDRESS_RE = re.compile(r"^(?P<street>.+?),\s*(?P<city>[^,]+?),?\s+(?P<state>[A-Za-z]{2})\.?\s+(?P<zip>\d{5}(?:-\d{4})?)$")
_STREET_RE = re.compile(r"^\d+[A-Za-z]?(-\d+[A-Za-z]?)?\s+([NSEW]\.?\s+)?[A-Za-z0-9][A-Za-z0-9.'\- ]*[A-Za-z][A-Za-z0-9.'\- ]*$")
_PO_BOX_RE = re.compile(r"^(P\.?\s*O\.?\s*Box|Post\s+Office\s+Box)\s+\d+(\s+.*)?$", re.IGNORECASE)
_CITY_RE = re.compile(r"^[A-Za-z][A-Za-z.'\- ]*[A-Za-z]$")


def mailing_address_error(address: str) -> str | None:
    """Returns a user-facing problem with the address, or None if it is a well-formed US address."""
    text = re.sub(r"\s*\n\s*", ", ", address or "").strip()
    m = _ADDRESS_RE.match(text)
    if not m:
        return "Address must be: street number and name, city, state, ZIP (e.g. 119 W Greenwich St, Bethlehem, PA 18018)"
    street = m.group("street").strip()
    if not (_STREET_RE.match(street) or _PO_BOX_RE.match(street)):
        return "Street must start with a house number and include the street name (or be a PO Box)"
    if not _CITY_RE.match(m.group("city").strip()):
        return "City must be letters only"
    if m.group("state").upper() not in US_STATES:
        return "State must be a valid two-letter US state code"
    return None
