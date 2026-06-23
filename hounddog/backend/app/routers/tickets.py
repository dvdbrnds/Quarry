import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import select, func, or_, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user
from ..config import settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..services.email import send_citation_email
from ..websocket import manager
from ..schemas.ticket import (
    ActionItem,
    ActivityEvent,
    AppealDecision,
    AppealRequest,
    DashboardData,
    IssuedCount,
    NeedsAction,
    ResolutionRate,
    Revenue,
    TicketCreate,
    TicketList,
    TicketPipeline,
    TicketRead,
    TicketUpdate,
    TrendDay,
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

    try:
        if ticket.plate:
            permit_result = await db.execute(
                select(Permit).where(
                    Permit.plates.contains([ticket.plate.upper()]),
                    Permit.deleted_at.is_(None),
                ).limit(1)
            )
            permit = permit_result.scalar()
            if permit and getattr(permit, "email", None):
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
    except Exception as e:
        import logging
        logging.getLogger("quarry.tickets").warning("Citation email failed (non-fatal): %s", e)

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


TERMINAL_STATUSES = {"paid", "voided", "resolved_permit"}


@router.get("/dashboard", response_model=DashboardData)
async def dashboard(
    period: str = Query("today", pattern="^(today|week|month)$"),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    today = now.date()
    if period == "today":
        since = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        avg_days = 7
    elif period == "week":
        since = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time(), tzinfo=timezone.utc)
        avg_days = 28
    else:
        since = datetime.combine(today.replace(day=1), datetime.min.time(), tzinfo=timezone.utc)
        avg_days = 90

    # Needs action (all time — these are currently open)
    action_q = await db.execute(
        select(Ticket.status, func.count())
        .where(Ticket.status.in_(["appealed", "escalated"]))
        .group_by(Ticket.status)
    )
    action_counts = dict(action_q.all())
    needs_action = NeedsAction(
        total=sum(action_counts.values()),
        appealed=action_counts.get("appealed", 0),
        escalated=action_counts.get("escalated", 0),
    )

    # Issued count within period (all tickets created, regardless of current status)
    issued_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(Ticket.issued_at >= since)
    )
    issued_total = issued_q.scalar() or 0

    avg_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(
            Ticket.issued_at >= datetime.combine(today - timedelta(days=avg_days), datetime.min.time(), tzinfo=timezone.utc),
        )
    )
    avg_raw = avg_q.scalar() or 0
    daily_avg = round(avg_raw / avg_days, 1) if avg_days > 0 else 0

    issued_count = IssuedCount(total=issued_total, daily_avg=daily_avg)

    # Revenue within period
    collected_q = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.paid_at >= since)
    )
    collected = collected_q.scalar()

    pending_q = await db.execute(
        select(func.count(), func.coalesce(func.sum(Ticket.fine_amount), 0))
        .select_from(Ticket)
        .where(Ticket.status == "pending_payment", Ticket.issued_at >= since)
    )
    pending_row = pending_q.one()
    revenue = Revenue(
        collected=collected,
        pending_count=pending_row[0],
        pending_amount=pending_row[1],
    )

    # Resolution rate within period
    period_total_q = await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.issued_at >= since)
    )
    period_total = period_total_q.scalar() or 0

    resolved_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(Ticket.issued_at >= since, Ticket.status.in_(list(TERMINAL_STATUSES)))
    )
    resolved = resolved_q.scalar() or 0

    rate = round(resolved / period_total * 100, 1) if period_total > 0 else 0
    resolution_rate = ResolutionRate(rate=rate, resolved=resolved, total=period_total)

    # Action items (appealed/escalated, oldest first)
    items_q = await db.execute(
        select(Ticket)
        .where(Ticket.status.in_(["appealed", "escalated"]))
        .order_by(Ticket.issued_at.asc())
        .limit(20)
    )
    action_items = [
        ActionItem.model_validate(t) for t in items_q.scalars().all()
    ]

    # Activity: tickets created or updated within the period
    activity_q = await db.execute(
        select(Ticket)
        .where(or_(Ticket.issued_at >= since, Ticket.updated_at >= since))
        .order_by(Ticket.updated_at.desc())
        .limit(30)
    )
    activity = [
        ActivityEvent.model_validate(t) for t in activity_q.scalars().all()
    ]

    # 7-day trend
    trend_start = today - timedelta(days=6)
    trend_q = await db.execute(
        select(
            cast(Ticket.issued_at, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(Ticket.issued_at >= datetime.combine(trend_start, datetime.min.time(), tzinfo=timezone.utc))
        .group_by("day")
        .order_by("day")
    )
    counts_by_day = {row[0]: row[1] for row in trend_q.all()}
    trend = []
    for i in range(7):
        d = trend_start + timedelta(days=i)
        trend.append(TrendDay(
            date=d.isoformat(),
            day=d.strftime("%a"),
            count=counts_by_day.get(d, 0),
        ))

    return DashboardData(
        needs_action=needs_action,
        issued_count=issued_count,
        revenue=revenue,
        resolution_rate=resolution_rate,
        action_items=action_items,
        activity=activity,
        trend=trend,
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

    # Enforce appeal window from EnforcementSettings
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    appeal_window_days = es.appeal_window_days if es else 5

    if ticket.issued_at:
        from datetime import timedelta
        issued = ticket.issued_at
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        deadline = issued + timedelta(days=appeal_window_days)
        if datetime.now(timezone.utc) > deadline:
            raise HTTPException(
                400,
                f"Appeal window has closed. Appeals must be submitted within "
                f"{appeal_window_days} day(s) of issuance.",
            )

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
