"""
Shared ticket lookup service.

Consolidates all ticket-finding logic so payments, appeals, and other
routers query tickets through one place instead of duplicating plate/email
queries across endpoints.
"""

import uuid
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.permit import Permit
from ..models.ticket import Ticket
from .plate_utils import normalize_plate

# Statuses that mean the ticket is still actionable (unpaid)
UNPAID_STATUSES = {"issued", "appealed", "escalated"}

# All non-terminal statuses (includes paid tickets for history views)
ALL_ACTIVE_STATUSES = {"issued", "appealed", "escalated", "paid", "voided", "warning", "resolved_permit"}


async def find_tickets_by_plate(
    db: AsyncSession,
    plate: str,
    *,
    unpaid_only: bool = True,
) -> list[Ticket]:
    """Find tickets matching an exact plate number."""
    norm = normalize_plate(plate)
    if len(norm) < 2:
        return []
    statuses = UNPAID_STATUSES if unpaid_only else ALL_ACTIVE_STATUSES
    result = await db.execute(
        select(Ticket).where(
            Ticket.plate == norm,
            Ticket.status.in_(statuses),
        ).order_by(Ticket.issued_at.desc())
    )
    return list(result.scalars().all())


async def find_tickets_by_plate_or_number(
    db: AsyncSession,
    query: str,
    *,
    unpaid_only: bool = False,
) -> list[Ticket]:
    """Find tickets by plate, ticket number, or ticket UUID.

    Used for guest/public lookups where the person might enter any of these.
    Returns ALL matching tickets (not just unpaid) so the user can see history.
    """
    val = query.strip()
    if not val:
        return []
    normalized = normalize_plate(val)

    conditions = [
        func.upper(func.replace(Ticket.plate, " ", "")) == normalized,
        func.upper(Ticket.ticket_number) == normalized,
    ]

    # Also try as UUID
    try:
        tid = uuid.UUID(val)
        conditions.append(Ticket.id == tid)
    except ValueError:
        pass

    q = select(Ticket).where(or_(*conditions)).order_by(Ticket.issued_at.desc())
    if unpaid_only:
        q = q.where(Ticket.status.in_(UNPAID_STATUSES))
    result = await db.execute(q)
    return list(result.scalars().all())


async def _plates_for_email(db: AsyncSession, email: str) -> set[str]:
    """Get all normalized plates linked to permits for an email."""
    permits = (await db.execute(
        select(Permit).where(
            func.lower(Permit.email) == email,
            Permit.deleted_at.is_(None),
        )
    )).scalars().all()
    plates: set[str] = set()
    for p in permits:
        if p.plates:
            for plate in p.plates:
                norm = normalize_plate(plate)
                if norm:
                    plates.add(norm)
    return plates


async def _permit_ids_for_email(db: AsyncSession, email: str) -> list:
    """Get all permit IDs linked to an email."""
    result = await db.execute(
        select(Permit.id).where(
            func.lower(Permit.email) == email,
            Permit.deleted_at.is_(None),
        )
    )
    return [row[0] for row in result.all()]


async def find_tickets_for_user(
    db: AsyncSession,
    email: str,
    *,
    unpaid_only: bool = False,
) -> list[Ticket]:
    """Find all tickets belonging to a user by email → permits → plates.

    Matches on:
    1. Plates from the user's permits
    2. notification_email on the ticket
    3. dispute_email on the ticket
    4. permit_id linked to one of the user's permits
    """
    email = email.strip().lower()
    if not email:
        return []

    user_plates = await _plates_for_email(db, email)
    permit_ids = await _permit_ids_for_email(db, email)

    conditions = [
        func.lower(Ticket.notification_email) == email,
        func.lower(Ticket.dispute_email) == email,
    ]
    if user_plates:
        conditions.append(Ticket.plate.in_(user_plates))
    if permit_ids:
        conditions.append(Ticket.permit_id.in_(permit_ids))

    q = select(Ticket).where(or_(*conditions)).order_by(Ticket.issued_at.desc())
    if unpaid_only:
        q = q.where(Ticket.status.in_(UNPAID_STATUSES))
    result = await db.execute(q)
    return list(result.scalars().all())
