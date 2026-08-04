"""Flat program discounts (e.g. ABSN $100 off) — roster and/or Okta groups."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser
from ..config import settings
from ..models.discount_roster import DiscountRoster


@dataclass
class ProgramDiscount:
    amount: Decimal
    label: str
    source: str  # "roster" | "okta_group"


def _configured_okta_groups() -> set[str]:
    raw = (settings.auto_discount_okta_groups or "").strip()
    if not raw:
        return set()
    return {g.strip() for g in raw.split(",") if g.strip()}


def okta_group_discount(user: OktaUser) -> ProgramDiscount | None:
    """Return configured flat discount if the user is in a matching Okta group."""
    groups = _configured_okta_groups()
    if not groups:
        return None
    user_groups = set(user.groups or [])
    if not user_groups & groups:
        return None
    amount = Decimal(str(settings.auto_discount_amount or 100))
    if amount <= 0:
        return None
    label = (settings.auto_discount_label or "Program Discount").strip()
    return ProgramDiscount(amount=amount, label=label, source="okta_group")


async def roster_discount(db: AsyncSession, user: OktaUser) -> ProgramDiscount | None:
    """Match student against the program discount roster (ABSN list, etc.)."""
    filters = []
    if user.email:
        filters.append(func.lower(DiscountRoster.email) == user.email.lower())
    if user.sub:
        filters.append(DiscountRoster.student_id == user.sub)

    profile = user.profile or {}
    for field in (
        "employeeNumber", "employee_number", "studentId", "student_id",
        "altId", "moravianId", "preferred_username", "login", "uid",
    ):
        val = profile.get(field)
        if val:
            val_str = str(val).split("@")[0]
            filters.append(DiscountRoster.student_id == val_str)

    user_full_name = f"{user.given_name} {user.family_name}".strip().lower()
    if user_full_name:
        filters.append(
            func.lower(func.concat(DiscountRoster.first_name, " ", DiscountRoster.last_name))
            == user_full_name
        )

    if not filters:
        return None

    match = (
        await db.execute(select(DiscountRoster).where(or_(*filters)).limit(1))
    ).scalar()
    if not match:
        return None

    amount = match.discount_amount if match.discount_amount is not None else Decimal("100.00")
    if amount <= 0:
        return None
    label = match.program_name or "Program Discount"
    return ProgramDiscount(amount=Decimal(amount), label=label, source="roster")


async def resolve_program_discount(db: AsyncSession, user: OktaUser) -> ProgramDiscount | None:
    """Prefer roster match; fall back to Okta group config."""
    roster = await roster_discount(db, user)
    if roster:
        return roster
    return okta_group_discount(user)


def apply_flat_discount(price: Decimal, discount: ProgramDiscount | None) -> Decimal:
    if not discount:
        return price
    return max(Decimal("0.00"), price - discount.amount)
