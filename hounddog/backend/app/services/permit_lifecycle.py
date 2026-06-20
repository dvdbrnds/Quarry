"""Permit lifecycle: auto-expiration, hold computation, duplicate detection."""

import logging
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.enforcement_settings import EnforcementSettings

logger = logging.getLogger("quarry.permits")


async def auto_expire_permits(db: AsyncSession) -> int:
    """Set status='expired' for active permits past their end_date. Returns count."""
    today = date.today()
    result = await db.execute(
        select(Permit).where(
            Permit.status == "active",
            Permit.end_date.isnot(None),
            Permit.end_date < today,
            Permit.deleted_at.is_(None),
        )
    )
    permits = result.scalars().all()
    for p in permits:
        p.status = "expired"

    count = len(permits)
    if count > 0:
        await db.flush()
        logger.info(f"Auto-expired {count} permits")
    return count


async def compute_hold(db: AsyncSession, permit: Permit) -> tuple[bool, Decimal]:
    """Check if a permit holder has unpaid tickets exceeding threshold."""
    settings_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    settings = settings_result.scalar()
    threshold = settings.escalation_threshold if settings else 3

    unpaid_result = await db.execute(
        select(func.count(), func.coalesce(func.sum(Ticket.fine_amount), 0))
        .where(
            Ticket.plate == func.any_(permit.plates),
            Ticket.status.in_(["issued", "overdue"]),
        )
    )
    row = unpaid_result.one()
    unpaid_count = row[0]
    unpaid_amount = Decimal(str(row[1]))

    has_hold = unpaid_count >= threshold
    return has_hold, unpaid_amount


async def find_duplicates(db: AsyncSession, plates: list[str], exclude_id=None) -> list[dict]:
    """Find other active permits sharing any of the given plates."""
    if not plates:
        return []

    query = select(Permit).where(
        Permit.status == "active",
        Permit.deleted_at.is_(None),
    )

    if exclude_id:
        query = query.where(Permit.id != exclude_id)

    result = await db.execute(query)
    all_active = result.scalars().all()

    conflicts = []
    plates_upper = {p.upper() for p in plates}
    for p in all_active:
        overlap = plates_upper & {plate.upper() for plate in p.plates}
        if overlap:
            conflicts.append({
                "permit_id": str(p.id),
                "name": p.name,
                "plates": p.plates,
                "overlapping_plates": list(overlap),
                "lot_assignment": p.lot_assignment,
                "permit_type": p.permit_type,
            })

    return conflicts


async def get_permit_stats(db: AsyncSession) -> dict:
    """Compute permit summary statistics."""
    today = date.today()
    soon = today + timedelta(days=30)

    base = select(Permit).where(Permit.deleted_at.is_(None))

    active_count = (await db.execute(
        select(func.count()).select_from(
            base.where(Permit.status == "active").subquery()
        )
    )).scalar() or 0

    expired_count = (await db.execute(
        select(func.count()).select_from(
            base.where(Permit.status == "expired").subquery()
        )
    )).scalar() or 0

    expiring_soon_count = (await db.execute(
        select(func.count()).select_from(
            base.where(
                Permit.status == "active",
                Permit.end_date.isnot(None),
                Permit.end_date <= soon,
                Permit.end_date >= today,
            ).subquery()
        )
    )).scalar() or 0

    revoked_count = (await db.execute(
        select(func.count()).select_from(
            base.where(Permit.status == "revoked").subquery()
        )
    )).scalar() or 0

    total_count = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    return {
        "total": total_count,
        "active": active_count,
        "expired": expired_count,
        "expiring_soon": expiring_soon_count,
        "revoked": revoked_count,
    }
