"""Fee-exempt roster matching (Res Life Staff and similar).

Checks the manual roster first, then falls back to SIS ResLifeStaff flag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser
from ..models.fee_exempt_roster import FeeExemptRoster

logger = logging.getLogger(__name__)

_PROFILE_ID_FIELDS = (
    "employeeNumber",
    "employee_number",
    "studentId",
    "student_id",
    "altId",
    "moravianId",
    "preferred_username",
    "login",
    "uid",
)


@dataclass
class FeeExemptMatch:
    entry: FeeExemptRoster
    matched_by: str


def _norm_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    return email or None


def _norm_name(value: str | None) -> str | None:
    name = " ".join((value or "").strip().lower().split())
    return name or None


async def lookup_fee_exempt(
    db: AsyncSession,
    user: OktaUser | None = None,
    *,
    extra_emails: list[str | None] | None = None,
    extra_names: list[str | None] | None = None,
    extra_student_ids: list[str | None] | None = None,
) -> FeeExemptMatch | None:
    """Match a student against the fee-exempt roster.

    Order of preference is irrelevant for the query — any hit grants exemption.
    Matching uses email (case-insensitive), Moravian/student ID, and full name.
    """
    filters = []
    emails: set[str] = set()
    names: set[str] = set()
    student_ids: set[str] = set()

    if user and user.email:
        emails.add(user.email.lower().strip())
    for e in extra_emails or []:
        ne = _norm_email(e)
        if ne:
            emails.add(ne)

    if user and user.sub:
        student_ids.add(str(user.sub).strip())
    for sid in extra_student_ids or []:
        if sid and str(sid).strip():
            student_ids.add(str(sid).strip().split("@")[0])

    profile = (user.profile if user else None) or {}
    for field in _PROFILE_ID_FIELDS:
        val = profile.get(field)
        if val:
            student_ids.add(str(val).split("@")[0].strip())

    if user:
        full = _norm_name(f"{user.given_name} {user.family_name}")
        if full:
            names.add(full)
        display = _norm_name(user.display_name)
        if display and "@" not in display:
            names.add(display)
    for n in extra_names or []:
        nn = _norm_name(n)
        if nn and "@" not in nn:
            names.add(nn)

    for email in emails:
        filters.append(func.lower(FeeExemptRoster.email) == email)
    for sid in student_ids:
        filters.append(FeeExemptRoster.student_id == sid)
    for name in names:
        filters.append(
            func.lower(func.concat(FeeExemptRoster.first_name, " ", FeeExemptRoster.last_name))
            == name
        )

    if not filters:
        return None

    entry = (
        await db.execute(select(FeeExemptRoster).where(or_(*filters)).limit(1))
    ).scalar_one_or_none()
    if entry:
        matched_by = "roster"
        entry_email = _norm_email(entry.email)
        if entry_email and entry_email in emails:
            matched_by = "email"
        elif entry.student_id and entry.student_id in student_ids:
            matched_by = "student_id"
        else:
            entry_name = _norm_name(f"{entry.first_name} {entry.last_name}")
            if entry_name and entry_name in names:
                matched_by = "name"

        # Backfill missing roster email when we have a confident match
        if not entry.email and emails:
            preferred = next(iter(emails))
            if preferred and "@" in preferred:
                entry.email = preferred

        return FeeExemptMatch(entry=entry, matched_by=matched_by)

    # Fallback: check SIS ResLifeStaff flag using student IDs from Okta profile
    if student_ids:
        from .sis_student_data import is_res_life_staff

        for sid in student_ids:
            if not sid or "@" in sid:
                continue
            try:
                if await is_res_life_staff(sid):
                    logger.info("SIS ResLifeStaff match for student_id=%s", sid)
                    # Create a synthetic roster entry so callers get a consistent object
                    synthetic = FeeExemptRoster(
                        student_id=sid,
                        first_name=user.given_name if user else "",
                        last_name=user.family_name if user else "",
                        email=user.email if user else (next(iter(emails)) if emails else ""),
                    )
                    return FeeExemptMatch(entry=synthetic, matched_by="sis_res_life_staff")
            except Exception:
                logger.exception("SIS ResLifeStaff lookup failed for %s", sid)

    return None
