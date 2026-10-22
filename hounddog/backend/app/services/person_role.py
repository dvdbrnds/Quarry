"""Student vs faculty/staff for non-office users (see BUSINESS_RULES "On sign-in, employees go to...")."""

import asyncio
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import error_reporting
from ..auth.okta import OktaUser
from ..models.permit import Permit

GRADUATED_OKTA_GROUPS = frozenset({"Okta_All_Students_Graduated_Within_One_Year"})


def class_year_is_current(class_year: int | None, now: datetime | None = None) -> bool:
    if not class_year:
        return False
    now = now or datetime.now()
    return class_year > now.year or (class_year == now.year and now.month <= 5)


async def decide_role(
    db: AsyncSession, *, email: str, groups: list[str], class_year: int | None, moravian_id: str | None,
) -> str:
    """'staff', 'student', or 'none' (no signal either way)."""
    from ..routers.housing_overrides import get_classification_override_by_email

    override = await get_classification_override_by_email(email, db) if email else None
    if override in ("F", "S"):
        return "staff"
    if override in ("R", "C"):
        return "student"

    okta_staff = OktaUser(sub="", email=email, groups=groups).is_staff
    graduated = bool(set(groups) & GRADUATED_OKTA_GROUPS)

    sis = None
    if moravian_id:
        try:
            from .sis_student_data import lookup_student_parking_data
            sis = await asyncio.wait_for(lookup_student_parking_data(moravian_id), timeout=8)
        except Exception as e:
            error_reporting.capture_exception(e)
    employee = okta_staff or bool(sis and sis.employee)

    # Jenzabar keeps the last housing flag after graduation; Okta's graduated group wins for employees.
    sis_current = bool(sis and sis.housing_status in ("R", "C")) and not (graduated and employee)
    if class_year_is_current(class_year) or sis_current:
        return "student"
    if employee:
        return "staff"
    if email:
        had_staff_permit = (await db.execute(
            select(Permit.id).where(func.lower(Permit.email) == email.lower(), Permit.permit_type == "faculty_staff")
            .limit(1)
        )).first()
        if had_staff_permit:
            return "staff"
    return "none"
