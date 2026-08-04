"""Match fee-exempt / discount roster rows to active permits."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.permit import Permit


@dataclass
class PermitMatch:
    has_permit: bool = False
    permit_number: str | None = None
    permit_type: str | None = None
    permit_status: str | None = None
    matched_by: str | None = None


def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _full_name(first: str | None, last: str | None) -> str:
    return _norm(f"{(first or '').strip()} {(last or '').strip()}")


async def load_active_permit_indexes(
    db: AsyncSession,
) -> tuple[dict[str, Permit], dict[str, Permit], dict[str, Permit]]:
    """Return (by_email, by_student_id, by_name) for active permits."""
    permits = (
        await db.execute(
            select(Permit).where(
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )
    ).scalars().all()

    by_email: dict[str, Permit] = {}
    by_student_id: dict[str, Permit] = {}
    by_name: dict[str, Permit] = {}
    for p in permits:
        email = _norm(p.email)
        if email and email not in by_email:
            by_email[email] = p
        sid = (p.student_id or "").strip()
        if sid and sid not in by_student_id:
            by_student_id[sid] = p
        name = _norm(p.name)
        if name and name not in by_name:
            by_name[name] = p
    return by_email, by_student_id, by_name


def match_roster_to_permit(
    *,
    student_id: str | None,
    email: str | None,
    first_name: str | None,
    last_name: str | None,
    by_email: dict[str, Permit],
    by_student_id: dict[str, Permit],
    by_name: dict[str, Permit],
) -> PermitMatch:
    """Prefer email, then student_id, then full name."""
    email_key = _norm(email)
    if email_key and email_key in by_email:
        p = by_email[email_key]
        return PermitMatch(
            has_permit=True,
            permit_number=p.permit_number,
            permit_type=p.permit_type,
            permit_status=p.status,
            matched_by="email",
        )

    sid = (student_id or "").strip()
    if sid and sid in by_student_id:
        p = by_student_id[sid]
        return PermitMatch(
            has_permit=True,
            permit_number=p.permit_number,
            permit_type=p.permit_type,
            permit_status=p.status,
            matched_by="student_id",
        )

    name = _full_name(first_name, last_name)
    if name and name in by_name:
        p = by_name[name]
        return PermitMatch(
            has_permit=True,
            permit_number=p.permit_number,
            permit_type=p.permit_type,
            permit_status=p.status,
            matched_by="name",
        )

    return PermitMatch()
