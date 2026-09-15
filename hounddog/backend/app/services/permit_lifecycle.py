"""Permit lifecycle: auto-expiration, hold computation, duplicate detection, ticket escalation."""

from datetime import date, datetime, timedelta, timezone

import structlog
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.enforcement_settings import EnforcementSettings
from .timeutils import today_local

logger = structlog.get_logger("quarry.permits")


async def auto_expire_permits(db: AsyncSession) -> int:
    """Set status='expired' for active permits past their end_date. Returns count."""
    today = today_local()
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


async def auto_escalate_tickets(db: AsyncSession) -> tuple[int, int]:
    """Transition ticket statuses based on enforcement settings.

    - issued   → overdue   after payment_due_days from issued_at
    - overdue  → escalated after another payment_due_days (2× total)

    Warnings ($0 fine) are never escalated — they stay as-is.

    Returns (overdue_count, escalated_count).
    """
    settings_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    settings = settings_result.scalar()
    due_days = settings.payment_due_days if settings else 5

    now = datetime.now(timezone.utc)
    overdue_cutoff = now - timedelta(days=due_days)
    escalated_cutoff = now - timedelta(days=due_days * 2)

    # Fix any $0 tickets that were incorrectly escalated — revert to "warning"
    fix_result = await db.execute(
        select(Ticket).where(
            Ticket.fine_amount <= 0,
            Ticket.status.in_(["issued", "overdue", "escalated"]),
        )
    )
    fixed_tickets = fix_result.scalars().all()
    for t in fixed_tickets:
        t.status = "warning"
    if fixed_tickets:
        logger.info("Reverted %d $0 tickets back to warning status", len(fixed_tickets))

    # issued → overdue (only tickets with a fine > $0)
    issued_result = await db.execute(
        select(Ticket).where(
            Ticket.status == "issued",
            Ticket.fine_amount > 0,
            Ticket.issued_at <= overdue_cutoff,
        )
    )
    issued_tickets = issued_result.scalars().all()
    for t in issued_tickets:
        t.status = "overdue"
    overdue_count = len(issued_tickets)

    # overdue → escalated (only tickets with a fine > $0)
    overdue_result = await db.execute(
        select(Ticket).where(
            Ticket.status == "overdue",
            Ticket.fine_amount > 0,
            Ticket.issued_at <= escalated_cutoff,
        )
    )
    overdue_tickets = overdue_result.scalars().all()
    for t in overdue_tickets:
        t.status = "escalated"
    escalated_count = len(overdue_tickets)

    if overdue_count or escalated_count or fixed_tickets:
        await db.flush()
        logger.info(
            "Ticket escalation: %d issued→overdue, %d overdue→escalated, %d $0→warning",
            overdue_count,
            escalated_count,
            len(fixed_tickets),
        )

    return overdue_count, escalated_count


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
            Ticket.fine_amount > 0,
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
    today = today_local()
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

    cancelled_count = (await db.execute(
        select(func.count()).select_from(
            base.where(Permit.status == "cancelled").subquery()
        )
    )).scalar() or 0

    total_count = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0

    unique_users = (await db.execute(
        select(func.count(func.distinct(Permit.email))).where(
            Permit.deleted_at.is_(None),
            Permit.status == "active",
            Permit.email.isnot(None),
        )
    )).scalar() or 0

    return {
        "total": total_count,
        "active": active_count,
        "expired": expired_count,
        "expiring_soon": expiring_soon_count,
        "revoked": revoked_count,
        "cancelled": cancelled_count,
        "unique_users": unique_users,
    }
