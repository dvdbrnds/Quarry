import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..services.email import send_citation_email
from ..websocket import manager
from ..schemas.ticket import (
    AppealDecision,
    AppealRequest,
    TicketCreate,
    TicketList,
    TicketPipeline,
    TicketRead,
    TicketUpdate,
)

router = APIRouter(dependencies=[Depends(get_current_user)])

VALID_STATUSES = {"issued", "pending_payment", "paid", "appealed", "escalated", "voided", "resolved_permit"}


@router.get("", response_model=TicketList)
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Ticket)

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(Ticket.plate.ilike(like), Ticket.officer_id.ilike(like))
        )
    if status:
        query = query.where(Ticket.status == status)
    if lot:
        query = query.where(Ticket.lot == lot)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(Ticket.issued_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return TicketList(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(data: TicketCreate, db: AsyncSession = Depends(get_db)):
    ticket = Ticket(**data.model_dump())
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)

    await manager.broadcast("ticket_created", {
        "id": str(ticket.id),
        "plate": ticket.plate,
        "lot": ticket.lot,
        "status": ticket.status,
        "violation_type": ticket.violation_type,
    })

    if ticket.plate:
        permit_result = await db.execute(
            select(Permit).where(
                Permit.plates.contains([ticket.plate.upper()]),
                Permit.email.isnot(None),
                Permit.deleted_at.is_(None),
            ).limit(1)
        )
        permit = permit_result.scalar()
        if permit and permit.email:
            vtype_label = ticket.violation_type or "Parking Violation"
            if ticket.violation_type:
                vt_row = await db.execute(
                    select(ViolationType.label).where(ViolationType.code == ticket.violation_type)
                )
                vt_lbl = vt_row.scalar()
                if vt_lbl:
                    vtype_label = vt_lbl
            payment_url = f"{settings.public_url}/pay?ticket={ticket.id}"
            await send_citation_email(
                recipient_email=permit.email,
                plate=ticket.plate,
                lot=ticket.lot or "",
                violation_label=vtype_label,
                fine_amount=str(ticket.fine_amount),
                payment_url=payment_url,
                officer_name=ticket.officer_name,
                issued_at=ticket.issued_at.strftime("%b %d, %Y %I:%M %p") if ticket.issued_at else "",
                ticket_id=str(ticket.id),
            )

    return ticket


@router.get("/pipeline", response_model=TicketPipeline)
async def ticket_pipeline(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Ticket.status, func.count()).group_by(Ticket.status)
    )
    counts = dict(result.all())
    total = sum(counts.values())
    return TicketPipeline(
        issued=counts.get("issued", 0),
        pending_payment=counts.get("pending_payment", 0),
        paid=counts.get("paid", 0),
        appealed=counts.get("appealed", 0),
        escalated=counts.get("escalated", 0),
        voided=counts.get("voided", 0),
        resolved_permit=counts.get("resolved_permit", 0),
        total=total,
    )


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.put("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    ticket_id: uuid.UUID, data: TicketUpdate, db: AsyncSession = Depends(get_db)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "status" and value not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status: {value}")
        setattr(ticket, field, value)

    await db.flush()
    await db.refresh(ticket)

    await manager.broadcast("ticket_updated", {
        "id": str(ticket.id),
        "plate": ticket.plate,
        "status": ticket.status,
    })

    return ticket


@router.post("/{ticket_id}/void", response_model=TicketRead)
async def void_ticket(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status == "paid":
        raise HTTPException(400, "Cannot void a paid ticket")
    ticket.status = "voided"
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/appeal", response_model=TicketRead)
async def appeal_ticket(
    ticket_id: uuid.UUID, appeal: AppealRequest, db: AsyncSession = Depends(get_db)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided"):
        raise HTTPException(400, f"Cannot appeal a {ticket.status} ticket")

    ticket.status = "appealed"
    ticket.appeal_note = appeal.note
    ticket.appeal_decision = "pending"
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/appeal/decide", response_model=TicketRead)
async def decide_appeal(
    ticket_id: uuid.UUID, decision: AppealDecision, db: AsyncSession = Depends(get_db)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.appeal_decision != "pending":
        raise HTTPException(400, "No pending appeal on this ticket")

    if decision.decision not in ("approved", "denied"):
        raise HTTPException(400, "Decision must be 'approved' or 'denied'")

    ticket.appeal_decision = decision.decision
    ticket.appeal_decided_by = decision.decided_by

    if decision.decision == "approved":
        ticket.status = "voided"
    else:
        ticket.status = "pending_payment"

    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/photo")
async def upload_photo(
    ticket_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    import os
    upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "photos")
    os.makedirs(upload_dir, exist_ok=True)

    filename = f"{ticket_id}_{file.filename}"
    filepath = os.path.join(upload_dir, filename)
    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    ticket.photo_url = f"/uploads/photos/{filename}"
    await db.flush()
    return {"photo_url": ticket.photo_url}
