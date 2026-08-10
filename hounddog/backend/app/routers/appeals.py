import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, or_, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.permit import Permit
from ..models.ticket import Ticket


router = APIRouter(dependencies=[Depends(get_current_user)])
public_router = APIRouter()


class TicketSummary(BaseModel):
    id: uuid.UUID
    ticket_number: str | None = None
    plate: str
    lot: str
    violation_type: str
    fine_amount: str
    status: str
    issued_at: datetime
    appeal_note: str | None = None
    appeal_decision: str | None = None
    appeal_decided_by: str | None = None
    can_appeal: bool = False
    appeal_deadline: datetime | None = None


class MyTicketsResponse(BaseModel):
    tickets: list[TicketSummary]
    appeal_window_days: int


class AppealSubmit(BaseModel):
    ticket_id: uuid.UUID
    explanation: str


class PublicAppealSubmit(BaseModel):
    ticket_id: uuid.UUID
    explanation: str
    name: str
    email: str
    phone: str = ""


class AppealResult(BaseModel):
    status: str
    message: str


class PublicLookupResponse(BaseModel):
    ticket: TicketSummary
    appeal_window_days: int


def _ticket_to_summary(t: "Ticket", appeal_window_days: int) -> TicketSummary:
    now = datetime.now(timezone.utc)
    issued = t.issued_at
    if issued and issued.tzinfo is None:
        issued = issued.replace(tzinfo=timezone.utc)
    deadline = issued + timedelta(days=appeal_window_days) if issued else None

    not_final = t.status not in ("paid", "voided", "resolved_permit")
    no_pending = t.appeal_decision != "pending"
    within_window = deadline and now <= deadline
    can_appeal = bool(not_final and no_pending and within_window)

    return TicketSummary(
        id=t.id,
        ticket_number=t.ticket_number,
        plate=t.plate,
        lot=t.lot,
        violation_type=t.violation_type,
        fine_amount=str(t.fine_amount),
        status=t.status,
        issued_at=t.issued_at,
        appeal_note=t.appeal_note,
        appeal_decision=t.appeal_decision,
        appeal_decided_by=t.appeal_decided_by,
        can_appeal=can_appeal,
        appeal_deadline=deadline,
    )


async def _get_appeal_window(db: AsyncSession) -> int:
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    return es.appeal_window_days if es else 5


async def _validate_and_appeal(ticket: "Ticket", explanation: str, appeal_window_days: int):
    """Shared validation logic for both authenticated and public appeals."""
    if ticket.status in ("paid", "voided", "resolved_permit"):
        raise HTTPException(
            400,
            f"Cannot appeal a {ticket.status} ticket. "
            "Once payment is processed, the citation is considered resolved.",
        )

    if ticket.appeal_decision == "pending":
        raise HTTPException(400, "An appeal has already been submitted for this ticket.")

    if ticket.issued_at:
        issued = ticket.issued_at
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        deadline = issued + timedelta(days=appeal_window_days)
        if datetime.now(timezone.utc) > deadline:
            raise HTTPException(
                400,
                f"The appeal window for this citation has closed. "
                f"Appeals must be submitted within {appeal_window_days} day(s) of issuance.",
            )

    ticket.status = "appealed"
    ticket.appeal_note = explanation
    ticket.appeal_decision = "pending"


# ---------------------------------------------------------------------------
# Authenticated endpoints (Moravian students/staff)
# ---------------------------------------------------------------------------

@router.get("/my-tickets", response_model=MyTicketsResponse)
async def my_tickets(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    email = user.email.lower()

    permits_q = await db.execute(
        select(Permit.plates).where(
            func.lower(Permit.email) == email,
            Permit.deleted_at.is_(None),
        )
    )
    all_plates: set[str] = set()
    for (plates,) in permits_q.all():
        if plates:
            for p in plates:
                all_plates.add(p.upper().replace(" ", ""))

    conditions = [func.lower(Ticket.dispute_email) == email]
    if all_plates:
        normalized_plates = list(all_plates)
        conditions.append(
            func.upper(func.replace(Ticket.plate, " ", "")).in_(normalized_plates)
        )

    tickets_q = await db.execute(
        select(Ticket)
        .where(or_(*conditions))
        .order_by(Ticket.issued_at.desc())
    )
    tickets = tickets_q.scalars().all()

    appeal_window_days = await _get_appeal_window(db)

    summaries = [_ticket_to_summary(t, appeal_window_days) for t in tickets]
    return MyTicketsResponse(tickets=summaries, appeal_window_days=appeal_window_days)


@router.post("/submit", response_model=AppealResult)
async def submit_appeal(
    data: AppealSubmit,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    ticket = await db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    appeal_window_days = await _get_appeal_window(db)
    await _validate_and_appeal(ticket, data.explanation, appeal_window_days)

    ticket.dispute_name = user.display_name or f"{user.given_name} {user.family_name}".strip()
    ticket.dispute_email = user.email
    await db.flush()

    return AppealResult(
        status="received",
        message="Your appeal has been submitted and will be reviewed within 5 business days. "
                "You will be contacted at your university email address.",
    )


# ---------------------------------------------------------------------------
# Public endpoints (community members, visitors, non-Moravian)
# ---------------------------------------------------------------------------

@public_router.get("/lookup/{ticket_id}", response_model=PublicLookupResponse)
async def public_lookup(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — look up a ticket by ID for appeal purposes."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    appeal_window_days = await _get_appeal_window(db)
    summary = _ticket_to_summary(ticket, appeal_window_days)
    return PublicLookupResponse(ticket=summary, appeal_window_days=appeal_window_days)


@public_router.post("/public-submit", response_model=AppealResult)
async def public_submit_appeal(
    data: PublicAppealSubmit,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — community members appeal a ticket without Okta auth."""
    ticket = await db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    appeal_window_days = await _get_appeal_window(db)
    await _validate_and_appeal(ticket, data.explanation, appeal_window_days)

    ticket.dispute_name = data.name
    ticket.dispute_email = data.email
    ticket.dispute_phone = data.phone
    await db.flush()

    return AppealResult(
        status="received",
        message="Your appeal has been submitted and will be reviewed within 5 business days. "
                "You will be contacted at the email address provided.",
    )
