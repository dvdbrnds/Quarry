"""Helpers for permit.lot_assignment (single lot or comma-separated list)."""

from sqlalchemy import ColumnElement, func, or_

from ..models.permit import Permit


def permit_lot_matches(lot: str) -> ColumnElement[bool]:
    """Match permits assigned to exactly this lot or including it in a CSV list."""
    lot = (lot or "").strip()
    if not lot:
        return Permit.lot_assignment == ""
    # Escape LIKE wildcards in lot names
    escaped = lot.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    normalized = func.replace(Permit.lot_assignment, ", ", ",")
    return or_(
        Permit.lot_assignment == lot,
        normalized == lot,
        normalized.like(f"{escaped},%", escape="\\"),
        normalized.like(f"%,{escaped}", escape="\\"),
        normalized.like(f"%,{escaped},%", escape="\\"),
    )


def format_lot_assignment(lots: list[str] | str | None) -> str:
    """Normalize a list or string into a comma-separated lot_assignment value."""
    if lots is None:
        return ""
    if isinstance(lots, str):
        parts = [p.strip() for p in lots.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in lots if str(p).strip()]
    # Preserve order, drop dupes
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return ", ".join(unique)
