"""Helpers for permit.lot_assignment (single lot or comma-separated list).

Per-permit lot_assignment always supersedes permit-type defaults when set.
Empty custom → fall back to the type's lot_assignments.
"""

from sqlalchemy import ColumnElement, func, or_

from ..models.permit import Permit


def parse_lot_assignment(lots: list[str] | str | None) -> list[str]:
    """Parse a CSV string or list into a de-duplicated ordered list of lot names."""
    if lots is None:
        return []
    if isinstance(lots, str):
        parts = [p.strip() for p in lots.split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in lots if str(p).strip()]
    seen: set[str] = set()
    unique: list[str] = []
    for p in parts:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


def format_lot_assignment(lots: list[str] | str | None) -> str:
    """Normalize a list or string into a comma-separated lot_assignment value."""
    return ", ".join(parse_lot_assignment(lots))


def effective_lot_assignment(
    custom: list[str] | str | None,
    type_defaults: list[str] | str | None = None,
) -> str:
    """Resolve lots for a permit: custom values supersede type defaults."""
    custom_lots = parse_lot_assignment(custom)
    if custom_lots:
        return ", ".join(custom_lots)
    return format_lot_assignment(type_defaults)


def resolve_lot_code(assigned_lot: str | None, type_lots: list[str]) -> str:
    """Pick the single lot code for a permit: explicit assignment wins,
    otherwise first lot from the type config."""
    if assigned_lot:
        return assigned_lot
    if type_lots:
        return type_lots[0]
    return ""


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
