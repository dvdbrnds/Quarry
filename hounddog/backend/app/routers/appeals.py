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


class AppealResult(BaseModel):
    status: str
    message: str


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

    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    appeal_window_days = es.appeal_window_days if es else 5
    now = datetime.now(timezone.utc)

    summaries: list[TicketSummary] = []
    for t in tickets:
        issued = t.issued_at
        if issued and issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        deadline = issued + timedelta(days=appeal_window_days) if issued else None

        not_final = t.status not in ("paid", "voided", "resolved_permit")
        no_pending = t.appeal_decision != "pending"
        within_window = deadline and now <= deadline
        can_appeal = bool(not_final and no_pending and within_window)

        summaries.append(TicketSummary(
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
        ))

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

    if ticket.status in ("paid", "voided", "resolved_permit"):
        raise HTTPException(
            400,
            f"Cannot appeal a {ticket.status} ticket. "
            "Once payment is processed, the citation is considered resolved.",
        )

    if ticket.appeal_decision == "pending":
        raise HTTPException(400, "An appeal has already been submitted for this ticket.")

    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    appeal_window_days = es.appeal_window_days if es else 5

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
    ticket.appeal_note = data.explanation
    ticket.appeal_decision = "pending"
    ticket.dispute_name = user.display_name or f"{user.given_name} {user.family_name}".strip()
    ticket.dispute_email = user.email
    await db.flush()

    return AppealResult(
        status="received",
        message="Your appeal has been submitted and will be reviewed within 5 business days. "
                "You will be contacted at your university email address.",
    )
