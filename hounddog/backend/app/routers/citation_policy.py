"""Citation policy v2 API: ticket policy view, fees, notices, payment plans, Barnacle, MUPD review."""

import base64
import binascii
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import cast, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin, require_office
from ..database import async_session, get_db
from ..models.citation_policy import (
    BarnacleDeployment, CitationClockPause, CitationFee, CitationNotice, MupdReview,
    OwnerNotificationEvent, PaymentAllocation, PaymentPlan, PaymentPlanCitation,
    PaymentPlanInstallment,
)
from ..models.payment import Payment
from ..models.ticket import Ticket
from ..services.citation_policy import timeline as tl
from ..services.citation_policy import payments as policy_pay
from ..services.citation_policy import vehicle as veh
from ..services.citation_policy.notices import mark_mailed
from ..services.citation_policy.service import (
    allocated_totals, appeal_deadline_for, balance_for_tickets, close_pauses, create_fee, fee_ticket_ids,
    fees_for_tickets, load_config, load_pauses, norm_plate, norm_state, open_pause,
    outstanding_items, person_balance, record_policy_event, require_barnacle, resolve_fee,
    ticket_is_unpaid, ticket_policy, tickets_for_plates,
)
from ..services.timeutils import today_local
from ..utils.safe_router import SafeRouter

router = SafeRouter(dependencies=[Depends(get_current_user)])
public_router = SafeRouter()

STAFF_FEE_TYPES = (tl.BARNACLE_DAMAGE, tl.COLLECTION_COST)
PAYMENT_METHODS = ("cash", "check", "bursar", "card_in_person", "other")


def _d(x):
    return x.isoformat() if x else None


def _fee_dict(f: CitationFee, ticket_ids: list[uuid.UUID] | None = None) -> dict:
    return {
        "id": str(f.id), "fee_type": f.fee_type, "amount": str(f.amount), "status": f.status,
        "plate": f.plate, "plate_state": f.plate_state, "reason": f.reason,
        "documentation": f.documentation, "has_attachment": bool(f.attachment_data),
        "attachment_name": f.attachment_name, "created_by": f.created_by, "created_at": _d(f.created_at),
        "resolved_by": f.resolved_by, "resolved_at": _d(f.resolved_at), "resolve_reason": f.resolve_reason,
        "ticket_ids": [str(t) for t in (ticket_ids or [])],
    }


def _notice_dict(n: CitationNotice, with_body: bool = False) -> dict:
    out = {
        "id": str(n.id), "notice_type": n.notice_type, "channel": n.channel, "recipient": n.recipient,
        "plate": n.plate, "plate_state": n.plate_state, "ticket_ids": n.ticket_ids or [],
        "subject": n.subject, "balance": str(n.balance) if n.balance is not None else None,
        "earliest_date": _d(n.earliest_date), "status": n.status, "sent_at": _d(n.sent_at),
        "attempts": n.attempts, "last_error": n.last_error, "mailed_by": n.mailed_by,
        "created_at": _d(n.created_at),
    }
    if with_body:
        out["body_text"] = n.body_text
        out["body_html"] = n.body_html
    return out


async def _ticket_or_404(db: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    t = await db.get(Ticket, ticket_id)
    if not t:
        raise HTTPException(404, "Ticket not found")
    return t


# ── Status ────────────────────────────────────────────────────────────────

@router.get("/status")
async def policy_status(db: AsyncSession = Depends(get_db)):
    cfg = await load_config(db)
    return {
        "active": cfg.active,
        "effective_date": _d(cfg.effective_date),
        "legacy_deadline": _d(cfg.legacy_deadline),
        "barnacle_enabled": cfg.barnacle_enabled,
    }


@router.post("/job/run")
async def run_job_now(_admin: OktaUser = Depends(require_admin())):
    """Run the daily job now. Safe to repeat: every fee and notice is keyed and inserted once."""
    from ..services.citation_policy.job import run_daily_job
    result = await run_daily_job(async_session, force=True)
    return {"result": result}


# ── Ticket view ───────────────────────────────────────────────────────────

@router.get("/tickets/{ticket_id}")
async def ticket_policy_view(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    t = await _ticket_or_404(db, ticket_id)
    cfg = await load_config(db)
    today = today_local()
    pauses = (await load_pauses(db, [t.id])).get(t.id, [])
    cs, start = veh.citation_state(t, pauses, cfg, today)
    deadline, _ = await appeal_deadline_for(db, t)

    fees = await fees_for_tickets(db, [t.id])
    links = await fee_ticket_ids(db, [f.id for f in fees])
    pause_rows = (await db.execute(
        select(CitationClockPause).where(CitationClockPause.ticket_id == t.id).order_by(CitationClockPause.start_date)
    )).scalars().all()
    notices = (await db.execute(
        select(CitationNotice).where(cast(CitationNotice.ticket_ids, JSONB).contains([str(t.id)]))
        .order_by(CitationNotice.created_at)
    )).scalars().all()
    plans = (await db.execute(
        select(PaymentPlan).join(PaymentPlanCitation, PaymentPlanCitation.plan_id == PaymentPlan.id)
        .where(PaymentPlanCitation.ticket_id == t.id)
    )).scalars().all()
    review = (await db.execute(select(MupdReview).where(MupdReview.ticket_id == t.id))).scalar()
    nxt = tl.next_escalation(cs.elapsed, today, cfg) if cs.on_timeline and not cs.paused_reason else None

    return {
        "policy_active": cfg.active,
        "policy_version": ticket_policy(t, cfg)[0],
        "timeline_start_date": _d(start),
        "on_timeline": cs.on_timeline,
        "stage": t.stage,
        "elapsed_days": cs.elapsed if cs.on_timeline else None,
        "delinquent_since": _d(t.delinquent_since),
        "paused_reason": cs.paused_reason,
        "next_step": {"step": nxt[0], "date": nxt[1].isoformat()} if nxt else None,
        "appeal_deadline": _d(deadline),
        "plate_state": t.plate_state,
        "balance": str(await balance_for_tickets(db, [t])),
        "fees": [_fee_dict(f, links.get(f.id)) for f in fees],
        "pauses": [{
            "id": str(p.id), "reason": p.reason, "start_date": _d(p.start_date), "end_date": _d(p.end_date),
            "created_by": p.created_by, "closed_by": p.closed_by, "close_reason": p.close_reason,
        } for p in pause_rows],
        "notices": [_notice_dict(n) for n in notices],
        "payment_plans": [{"id": str(p.id), "status": p.status, "payer_name": p.payer_name} for p in plans],
        "mupd_review": {"id": str(review.id), "status": review.status} if review else None,
        "barnacle_enabled": cfg.barnacle_enabled,
    }


class PlateStateBody(BaseModel):
    plate_state: str = Field(min_length=2, max_length=2)


@router.post("/tickets/{ticket_id}/plate-state")
async def set_plate_state(
    ticket_id: uuid.UUID,
    body: PlateStateBody,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    t = await _ticket_or_404(db, ticket_id)
    old = t.plate_state
    t.plate_state = norm_state(body.plate_state)
    await record_policy_event(
        db, user.email, "ticket", t.id,
        f"Plate state on {t.ticket_number or t.id} set to {t.plate_state}" + (f" (was {old})" if old else ""),
    )
    return {"ok": True, "plate_state": t.plate_state}


# ── Fees ──────────────────────────────────────────────────────────────────

@router.get("/fees")
async def list_fees(
    plate: str | None = None,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    q = select(CitationFee).order_by(CitationFee.created_at.desc()).limit(500)
    if plate:
        q = q.where(CitationFee.plate == norm_plate(plate))
    if status:
        q = q.where(CitationFee.status == status)
    fees = (await db.execute(q)).scalars().all()
    links = await fee_ticket_ids(db, [f.id for f in fees])
    return [_fee_dict(f, links.get(f.id)) for f in fees]


class StaffFeeBody(BaseModel):
    fee_type: str
    amount: Decimal = Field(gt=0)
    plate: str
    plate_state: str | None = None
    ticket_ids: list[uuid.UUID] | None = None
    reason: str | None = None
    documentation: str | None = None
    attachment_name: str | None = None
    attachment_mime: str | None = None
    attachment_base64: str | None = None


@router.post("/fees")
async def create_staff_fee(
    body: StaffFeeBody,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    if body.fee_type not in STAFF_FEE_TYPES:
        raise HTTPException(400, f"Staff can add {', '.join(STAFF_FEE_TYPES)} here")
    if body.fee_type == tl.BARNACLE_DAMAGE:
        await require_barnacle(db)
    if body.fee_type == tl.COLLECTION_COST and not (body.reason or "").strip():
        raise HTTPException(400, "A reason is required for collection costs")

    attachment = None
    if body.attachment_base64:
        try:
            data = base64.b64decode(body.attachment_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(400, "Attachment is not valid base64")
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(400, "Attachment must be under 10 MB")
        attachment = (body.attachment_name or "attachment", body.attachment_mime or "application/octet-stream", data)
    if body.fee_type == tl.BARNACLE_DAMAGE and not ((body.documentation or "").strip() or attachment):
        raise HTTPException(400, "Barnacle damage requires a documentation note or attachment")

    ticket_ids = body.ticket_ids
    if not ticket_ids:
        tickets = await tickets_for_plates(db, [body.plate], norm_state(body.plate_state))
        ticket_ids = [t.id for t in tickets if ticket_is_unpaid(t)] or [t.id for t in tickets]
    if not ticket_ids:
        raise HTTPException(400, "No citations found for that plate")

    fee = await create_fee(
        db, fee_type=body.fee_type, amount=body.amount, plate=body.plate, plate_state=body.plate_state,
        ticket_ids=ticket_ids, actor=user.email, reason=(body.reason or "").strip() or None,
        documentation=(body.documentation or "").strip() or None, attachment=attachment,
    )
    return _fee_dict(fee, ticket_ids)


@router.get("/fees/{fee_id}/attachment")
async def fee_attachment(
    fee_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    fee = await db.get(CitationFee, fee_id)
    if not fee or not fee.attachment_data:
        raise HTTPException(404, "No attachment")
    return Response(
        content=fee.attachment_data, media_type=fee.attachment_mime or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{fee.attachment_name or "attachment"}"'},
    )


class ReasonBody(BaseModel):
    reason: str = Field(min_length=1)


@router.post("/fees/{fee_id}/waive")
async def waive_fee(
    fee_id: uuid.UUID, body: ReasonBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    fee = await db.get(CitationFee, fee_id)
    if not fee:
        raise HTTPException(404, "Fee not found")
    await resolve_fee(db, fee, "waived", user.email, body.reason)
    return _fee_dict(fee)


@router.post("/fees/{fee_id}/void")
async def void_fee(
    fee_id: uuid.UUID, body: ReasonBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    fee = await db.get(CitationFee, fee_id)
    if not fee:
        raise HTTPException(404, "Fee not found")
    await resolve_fee(db, fee, "voided", user.email, body.reason)
    return _fee_dict(fee)


class StaffPaymentBody(BaseModel):
    method: str
    reference: str | None = None


@router.post("/fees/{fee_id}/record-payment")
async def record_fee_payment(
    fee_id: uuid.UUID, body: StaffPaymentBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    if body.method not in PAYMENT_METHODS:
        raise HTTPException(400, f"Method must be one of {', '.join(PAYMENT_METHODS)}")
    fee = await db.get(CitationFee, fee_id)
    if not fee or fee.status != "open":
        raise HTTPException(400, "Fee is not open")
    _, by_fee = await allocated_totals(db, fee_ids=[fee.id])
    owed = Decimal(fee.amount) - by_fee.get(fee.id, Decimal(0))
    links = (await fee_ticket_ids(db, [fee.id])).get(fee.id, [])
    first_ticket = await db.get(Ticket, links[0]) if links else None
    payment = Payment(
        ticket_id=first_ticket.id if first_ticket else None, amount=owed, method=body.method,
        bursar_reference=body.reference or None, payment_type="citation_fee", plate=fee.plate,
        description=f"{fee.fee_type} — {fee.plate}", paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    await db.flush()
    db.add(PaymentAllocation(payment_id=payment.id, fee_id=fee.id, fee_type=fee.fee_type, amount=owed))
    await resolve_fee(db, fee, "paid", user.email, f"Paid ({body.method})")
    return _fee_dict(fee)


# ── Owner notification ────────────────────────────────────────────────────

class OwnerNotificationBody(BaseModel):
    plate: str
    plate_state: str | None = None
    owner_name: str = Field(min_length=1)
    mailing_address: str = Field(min_length=1)
    lookup_source: str | None = None
    mailed_on: date


@router.post("/owner-notifications")
async def create_owner_notification(
    body: OwnerNotificationBody,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    cfg = await load_config(db)
    tickets = await tickets_for_plates(db, [body.plate], norm_state(body.plate_state))
    outstanding = [t for t in tickets if ticket_is_unpaid(t)]
    if not outstanding:
        raise HTTPException(400, "This vehicle has no outstanding citations")
    event = OwnerNotificationEvent(
        id=uuid.uuid4(), plate=norm_plate(body.plate), plate_state=norm_state(body.plate_state),
        owner_name=body.owner_name.strip(), mailing_address=body.mailing_address.strip(),
        lookup_source=(body.lookup_source or "").strip() or None, mailed_on=body.mailed_on,
        ticket_ids=[str(t.id) for t in outstanding], created_by=user.email,
    )
    db.add(event)
    await db.flush()
    fee = await create_fee(
        db, fee_type=tl.OWNER_NOTIFICATION, amount=cfg.owner_notification_fee, plate=event.plate,
        plate_state=event.plate_state, ticket_ids=[t.id for t in outstanding], actor=user.email,
        idempotency_key=f"{tl.OWNER_NOTIFICATION}:{event.id}", owner_notification_id=event.id,
        reason=f"Registered-owner letter mailed {body.mailed_on.isoformat()}",
    )
    event.fee_id = fee.id if fee else None
    for t in outstanding:
        if not t.owner_name:
            t.owner_name = event.owner_name
        if not t.owner_address:
            t.owner_address = event.mailing_address
    return {"id": str(event.id), "fee": _fee_dict(fee, [t.id for t in outstanding]) if fee else None}


@router.get("/owner-notifications")
async def list_owner_notifications(
    plate: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    q = select(OwnerNotificationEvent).order_by(OwnerNotificationEvent.created_at.desc()).limit(200)
    if plate:
        q = q.where(OwnerNotificationEvent.plate == norm_plate(plate))
    rows = (await db.execute(q)).scalars().all()
    return [{
        "id": str(e.id), "plate": e.plate, "plate_state": e.plate_state, "owner_name": e.owner_name,
        "mailing_address": e.mailing_address, "lookup_source": e.lookup_source,
        "mailed_on": _d(e.mailed_on), "ticket_ids": e.ticket_ids or [], "created_by": e.created_by,
        "created_at": _d(e.created_at),
    } for e in rows]


# ── Notices ───────────────────────────────────────────────────────────────

@router.get("/notices")
async def list_notices(
    plate: str | None = None,
    notice_type: str | None = None,
    status: str | None = None,
    channel: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    q = select(CitationNotice).order_by(CitationNotice.created_at.desc()).limit(500)
    if plate:
        q = q.where(CitationNotice.plate == norm_plate(plate))
    if notice_type:
        q = q.where(CitationNotice.notice_type == notice_type)
    if status:
        q = q.where(CitationNotice.status == status)
    if channel:
        q = q.where(CitationNotice.channel == channel)
    return [_notice_dict(n) for n in (await db.execute(q)).scalars().all()]


@router.get("/notices/mail-queue")
async def notice_mail_queue(
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    rows = (await db.execute(
        select(CitationNotice).where(CitationNotice.channel == "mail", CitationNotice.status == "pending")
        .order_by(CitationNotice.created_at)
    )).scalars().all()
    return [_notice_dict(n, with_body=True) for n in rows]


@router.get("/notices/{notice_id}")
async def get_notice(
    notice_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    n = await db.get(CitationNotice, notice_id)
    if not n:
        raise HTTPException(404, "Notice not found")
    return _notice_dict(n, with_body=True)


class MarkMailedBody(BaseModel):
    mailing_address: str | None = None


@router.post("/notices/{notice_id}/mark-mailed")
async def mark_notice_mailed(
    notice_id: uuid.UUID, body: MarkMailedBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    n = await db.get(CitationNotice, notice_id)
    if not n:
        raise HTTPException(404, "Notice not found")
    if n.channel != "mail":
        raise HTTPException(400, "Only mail notices can be marked mailed")
    if not (body.mailing_address or n.recipient or "").strip():
        raise HTTPException(400, "Enter the mailing address used")
    await mark_mailed(db, n, user.email, body.mailing_address)
    return _notice_dict(n)


@router.post("/notices/{notice_id}/cancel")
async def cancel_notice(
    notice_id: uuid.UUID, body: ReasonBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_admin()),
):
    n = await db.get(CitationNotice, notice_id)
    if not n:
        raise HTTPException(404, "Notice not found")
    if n.status == "sent":
        raise HTTPException(400, "A sent notice can't be cancelled")
    n.status = "cancelled"
    n.last_error = f"Cancelled by {user.email}: {body.reason}"
    await record_policy_event(db, user.email, "citation_notice", n.id, f"{n.notice_type} notice cancelled: {body.reason}")
    return _notice_dict(n)


# ── Payment plans ─────────────────────────────────────────────────────────

class InstallmentIn(BaseModel):
    due_date: date
    amount: Decimal = Field(gt=0)


class PlanCreate(BaseModel):
    payer_name: str = Field(min_length=1)
    payer_email: str | None = None
    ticket_ids: list[uuid.UUID] = Field(min_length=1)
    installments: list[InstallmentIn] = Field(min_length=1)
    notes: str | None = None


async def _plan_dict(db: AsyncSession, plan: PaymentPlan) -> dict:
    ticket_ids = (await db.execute(
        select(PaymentPlanCitation.ticket_id).where(PaymentPlanCitation.plan_id == plan.id)
    )).scalars().all()
    tickets = (await db.execute(select(Ticket).where(Ticket.id.in_(ticket_ids)))).scalars().all() if ticket_ids else []
    installments = (await db.execute(
        select(PaymentPlanInstallment).where(PaymentPlanInstallment.plan_id == plan.id)
        .order_by(PaymentPlanInstallment.due_date)
    )).scalars().all()
    return {
        "id": str(plan.id), "payer_name": plan.payer_name, "payer_email": plan.payer_email,
        "status": plan.status, "notes": plan.notes, "created_by": plan.created_by,
        "created_at": _d(plan.created_at), "defaulted_at": _d(plan.defaulted_at),
        "closed_at": _d(plan.closed_at), "closed_by": plan.closed_by,
        "balance": str(await balance_for_tickets(db, list(tickets))),
        "citations": [{
            "id": str(t.id), "ticket_number": t.ticket_number, "plate": t.plate, "plate_state": t.plate_state,
            "fine_amount": str(t.fine_amount), "status": t.status, "issued_at": _d(t.issued_at),
        } for t in tickets],
        "installments": [{
            "id": str(i.id), "due_date": _d(i.due_date), "amount": str(i.amount), "paid_at": _d(i.paid_at),
            "method": i.method, "reference": i.reference, "recorded_by": i.recorded_by,
        } for i in installments],
    }


async def _add_plan_citations(db: AsyncSession, plan: PaymentPlan, ticket_ids: list[uuid.UUID], actor: str):
    today = today_local()
    for tid in dict.fromkeys(ticket_ids):
        t = await _ticket_or_404(db, tid)
        if not ticket_is_unpaid(t):
            raise HTTPException(400, f"Citation {t.ticket_number or t.id} is not unpaid")
        on_active = (await db.execute(
            select(PaymentPlan.id).join(PaymentPlanCitation, PaymentPlanCitation.plan_id == PaymentPlan.id)
            .where(PaymentPlanCitation.ticket_id == t.id, PaymentPlan.status == "active")
        )).first()
        if on_active:
            raise HTTPException(400, f"Citation {t.ticket_number or t.id} is already on an active plan")
        db.add(PaymentPlanCitation(plan_id=plan.id, ticket_id=t.id, added_by=actor))
        await open_pause(db, t, tl.PAUSE_PAYMENT_PLAN, today, actor, plan_id=plan.id)


@router.get("/plans")
async def list_plans(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    q = select(PaymentPlan).order_by(PaymentPlan.created_at.desc())
    if status:
        q = q.where(PaymentPlan.status == status)
    return [await _plan_dict(db, p) for p in (await db.execute(q)).scalars().all()]


@router.post("/plans")
async def create_plan(
    body: PlanCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    plan = PaymentPlan(
        id=uuid.uuid4(), payer_name=body.payer_name.strip(),
        payer_email=(body.payer_email or "").strip().lower() or None,
        notes=(body.notes or "").strip() or None, created_by=user.email, status="active",
    )
    db.add(plan)
    await db.flush()
    await _add_plan_citations(db, plan, body.ticket_ids, user.email)
    for inst in sorted(body.installments, key=lambda i: i.due_date):
        db.add(PaymentPlanInstallment(plan_id=plan.id, due_date=inst.due_date, amount=inst.amount))
    await record_policy_event(
        db, user.email, "payment_plan", plan.id,
        f"Payment plan created for {plan.payer_name}: {len(body.ticket_ids)} citation(s), "
        f"{len(body.installments)} installment(s)",
    )
    await db.flush()
    return await _plan_dict(db, plan)


@router.get("/plans/{plan_id}")
async def get_plan(
    plan_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    plan = await db.get(PaymentPlan, plan_id)
    if not plan:
        raise HTTPException(404, "Plan not found")
    return await _plan_dict(db, plan)


class PlanAddCitations(BaseModel):
    ticket_ids: list[uuid.UUID] = Field(min_length=1)


@router.post("/plans/{plan_id}/citations")
async def add_plan_citations(
    plan_id: uuid.UUID, body: PlanAddCitations,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    plan = await db.get(PaymentPlan, plan_id)
    if not plan or plan.status != "active":
        raise HTTPException(400, "Plan is not active")
    await _add_plan_citations(db, plan, body.ticket_ids, user.email)
    await record_policy_event(db, user.email, "payment_plan", plan.id,
                              f"Added {len(body.ticket_ids)} citation(s) to payment plan for {plan.payer_name}")
    await db.flush()
    return await _plan_dict(db, plan)


@router.post("/plans/{plan_id}/installments/{installment_id}/record")
async def record_installment(
    plan_id: uuid.UUID, installment_id: uuid.UUID, body: StaffPaymentBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    if body.method not in PAYMENT_METHODS:
        raise HTTPException(400, f"Method must be one of {', '.join(PAYMENT_METHODS)}")
    plan = await db.get(PaymentPlan, plan_id)
    inst = await db.get(PaymentPlanInstallment, installment_id)
    if not plan or not inst or inst.plan_id != plan.id:
        raise HTTPException(404, "Installment not found")
    if inst.paid_at:
        raise HTTPException(400, "Installment already recorded")
    ticket_ids = (await db.execute(
        select(PaymentPlanCitation.ticket_id).where(PaymentPlanCitation.plan_id == plan.id)
    )).scalars().all()
    tickets = list((await db.execute(select(Ticket).where(Ticket.id.in_(ticket_ids)))).scalars().all())
    payment, allocations = await policy_pay.record_staff_payment(
        db, tickets=tickets, amount=Decimal(inst.amount), method=body.method, reference=body.reference,
        actor=user.email, payment_type="payment_plan_installment",
        description=f"Payment plan installment — {plan.payer_name}", payer_name=plan.payer_name,
    )
    inst.paid_at = datetime.now(timezone.utc)
    inst.payment_id = payment.id
    inst.method = body.method
    inst.reference = body.reference
    inst.recorded_by = user.email
    await db.flush()
    return {"plan": await _plan_dict(db, plan), "allocations": allocations}


@router.post("/plans/{plan_id}/cancel")
async def cancel_plan(
    plan_id: uuid.UUID, body: ReasonBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    plan = await db.get(PaymentPlan, plan_id)
    if not plan or plan.status != "active":
        raise HTTPException(400, "Plan is not active")
    plan.status = "cancelled"
    plan.closed_at = datetime.now(timezone.utc)
    plan.closed_by = user.email
    ticket_ids = (await db.execute(
        select(PaymentPlanCitation.ticket_id).where(PaymentPlanCitation.plan_id == plan.id)
    )).scalars().all()
    for tid in ticket_ids:
        t = await db.get(Ticket, tid)
        if t:
            await close_pauses(db, t, (tl.PAUSE_PAYMENT_PLAN,), today_local(), user.email,
                               f"plan cancelled: {body.reason}", plan_id=plan.id)
    await record_policy_event(db, user.email, "payment_plan", plan.id,
                              f"Payment plan for {plan.payer_name} cancelled: {body.reason}")
    await db.flush()
    return await _plan_dict(db, plan)


# ── Barnacle (feature flag: 404 unless env + settings toggle are both on) ──

class VehicleBody(BaseModel):
    plate: str = Field(min_length=1)
    plate_state: str = Field(min_length=2, max_length=2)


@router.get("/barnacle/queue")
async def barnacle_queue(
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    cfg = await require_barnacle(db)
    rows = (await db.execute(
        select(Ticket.plate, Ticket.plate_state).where(
            Ticket.stage.in_((tl.STAGE_DELINQUENT, tl.STAGE_FINAL)),
            Ticket.plate_state.isnot(None),
            Ticket.fine_amount > 0,
            Ticket.status.notin_(tl.UNPAID_EXCLUDED_STATUSES),
        ).distinct()
    )).all()
    out = []
    for plate, state in {(norm_plate(p), norm_state(s)) for p, s in rows}:
        v = await veh.vehicle_eligibility(db, plate, state, cfg)
        elig = v["eligibility"]
        if len(elig.qualifying_ticket_ids) == 0 and not v["warnings"]:
            continue
        dep = await veh.active_deployment(db, plate, state)
        out.append({
            "plate": plate, "plate_state": state, "balance": str(v["balance"]),
            "eligibility": veh.eligibility_dict(elig),
            "active_deployment": veh.deployment_dict(dep) if dep else None,
        })
    out.sort(key=lambda r: (not r["eligibility"]["eligible"], r["eligibility"]["earliest_date"] or "9999"))
    return out


@router.post("/barnacle/checklist")
async def barnacle_checklist(
    body: VehicleBody,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    cfg = await require_barnacle(db)
    return await veh.checklist(db, body.plate, body.plate_state, cfg)


class DeploymentBody(VehicleBody):
    location_text: str = Field(min_length=1)
    location_lat: float | None = None
    location_lng: float | None = None
    vehicle_description: str | None = None
    authorized_property_confirmed: bool = False


@router.post("/barnacle/deployments")
async def create_deployment(
    body: DeploymentBody,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    cfg = await require_barnacle(db)
    d = await veh.record_deployment(
        db, plate=body.plate, plate_state=body.plate_state, cfg=cfg, officer_email=user.email,
        officer_name=user.display_name, location_text=body.location_text,
        location_lat=body.location_lat, location_lng=body.location_lng,
        vehicle_description=body.vehicle_description,
        authorized_property_confirmed=body.authorized_property_confirmed,
    )
    return veh.deployment_dict(d)


@router.get("/barnacle/deployments")
async def list_deployments(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    # Visible to admins even with the flag off, so vehicles booted before a shutdown can be released.
    q = select(BarnacleDeployment).order_by(BarnacleDeployment.deployed_at.desc()).limit(500)
    if status:
        q = q.where(BarnacleDeployment.status == status)
    rows = (await db.execute(q)).scalars().all()
    if not rows:
        await require_barnacle(db)
    out = []
    for d in rows:
        item = veh.deployment_dict(d)
        item["person_balance"] = str(await person_balance(db, d.plate)) if d.status != "removed" else "0.00"
        out.append(item)
    return out


@router.post("/barnacle/deployments/{deployment_id}/override")
async def deployment_override(
    deployment_id: uuid.UUID, body: ReasonBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_admin()),
):
    d = await db.get(BarnacleDeployment, deployment_id)
    if not d:
        raise HTTPException(404, "Not found")
    await veh.record_override(db, d, user.email, body.reason)
    return veh.deployment_dict(d)


class RemovalBody(BaseModel):
    notes: str | None = None


@router.post("/barnacle/deployments/{deployment_id}/remove")
async def deployment_remove(
    deployment_id: uuid.UUID, body: RemovalBody,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    d = await db.get(BarnacleDeployment, deployment_id)
    if not d:
        raise HTTPException(404, "Not found")
    await veh.record_removal(db, d, user.email, body.notes)
    return veh.deployment_dict(d)


@public_router.get("/public/barnacle")
async def public_barnacle_status(
    plate: str = Query(min_length=1),
    state: str = Query(min_length=2, max_length=2),
    db: AsyncSession = Depends(get_db),
):
    cfg = await require_barnacle(db)
    d = await veh.active_deployment(db, plate, state)
    if not d:
        return {"deployed": False}
    balance = await person_balance(db, d.plate)
    return {
        "deployed": True,
        "status": d.status,
        "balance": str(balance),
        "can_request_removal": balance <= 0 or bool(d.override_at),
        "removal_phone_daytime": cfg.removal_phone_daytime,
        "removal_phone_after_hours": cfg.removal_phone_after_hours,
    }


class PublicRemovalBody(BaseModel):
    plate: str = Field(min_length=1)
    plate_state: str = Field(min_length=2, max_length=2)
    contact: str = Field(min_length=3, max_length=256)


@public_router.post("/public/barnacle/request-removal")
async def public_request_removal(body: PublicRemovalBody, db: AsyncSession = Depends(get_db)):
    cfg = await require_barnacle(db)
    d = await veh.active_deployment(db, body.plate, body.plate_state)
    if not d:
        raise HTTPException(404, "No active Barnacle on this vehicle")
    result = await veh.request_removal(db, d, body.contact, f"public:{body.contact[:64]}")
    if not result["ok"]:
        raise HTTPException(409, f"Outstanding balance ${result['balance']} must be paid before removal")
    return {
        "ok": True,
        "removal_phone_daytime": cfg.removal_phone_daytime,
        "removal_phone_after_hours": cfg.removal_phone_after_hours,
    }


# ── MUPD review ───────────────────────────────────────────────────────────

def _review_dict(r: MupdReview, t: Ticket | None) -> dict:
    return {
        "id": str(r.id), "ticket_id": str(r.ticket_id), "plate": r.plate, "plate_state": r.plate_state,
        "status": r.status, "incident_documentation": r.incident_documentation,
        "signage_restrictions": r.signage_restrictions, "registered_owner": r.registered_owner,
        "responsible_person_evidence": r.responsible_person_evidence,
        "exception_claimed": r.exception_claimed, "exception_details": r.exception_details,
        "filing_deadline": _d(r.filing_deadline), "court_case_number": r.court_case_number,
        "court_outcome": r.court_outcome,
        "court_fine_amount": str(r.court_fine_amount) if r.court_fine_amount is not None else None,
        "notes": r.notes, "created_by": r.created_by, "created_at": _d(r.created_at),
        "updated_by": r.updated_by, "updated_at": _d(r.updated_at),
        "ticket": {
            "ticket_number": t.ticket_number, "issued_at": _d(t.issued_at), "lot": t.lot,
            "violation_type": t.violation_type, "fine_amount": str(t.fine_amount), "status": t.status,
            "owner_name": t.owner_name, "owner_address": t.owner_address,
        } if t else None,
    }


@router.get("/mupd")
async def list_mupd(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    q = select(MupdReview, Ticket).join(Ticket, Ticket.id == MupdReview.ticket_id).order_by(MupdReview.created_at.desc())
    if status:
        q = q.where(MupdReview.status == status)
    return [_review_dict(r, t) for r, t in (await db.execute(q)).all()]


class MupdUpdate(BaseModel):
    status: str | None = None
    incident_documentation: str | None = None
    signage_restrictions: str | None = None
    registered_owner: str | None = None
    responsible_person_evidence: str | None = None
    exception_claimed: str | None = None
    exception_details: str | None = None
    filing_deadline: date | None = None
    court_case_number: str | None = None
    court_outcome: str | None = None
    court_fine_amount: Decimal | None = None
    notes: str | None = None


MUPD_STATUSES = ("open", "referred", "closed_no_action", "closed_paid")
MUPD_EXCEPTIONS = ("none", "emergency", "disablement", "other")


@router.post("/mupd/{review_id}")
async def update_mupd(
    review_id: uuid.UUID, body: MupdUpdate,
    db: AsyncSession = Depends(get_db), user: OktaUser = Depends(require_office()),
):
    r = await db.get(MupdReview, review_id)
    if not r:
        raise HTTPException(404, "Review not found")
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in MUPD_STATUSES:
        raise HTTPException(400, f"Status must be one of {', '.join(MUPD_STATUSES)}")
    if changes.get("exception_claimed") and changes["exception_claimed"] not in MUPD_EXCEPTIONS:
        raise HTTPException(400, f"Exception must be one of {', '.join(MUPD_EXCEPTIONS)}")
    if changes.get("status") == "referred" and not (changes.get("responsible_person_evidence") or r.responsible_person_evidence):
        raise HTTPException(400, "Evidence identifying the responsible person is required before referral "
                                 "(registered owner alone is not sufficient)")
    for k, v in changes.items():
        setattr(r, k, v.strip() if isinstance(v, str) else v)
    r.updated_by = user.email
    await record_policy_event(
        db, user.email, "mupd_review", r.id, f"MUPD review for {r.plate} updated: {', '.join(sorted(changes))}",
        {k: str(v) for k, v in changes.items()},
    )
    await db.flush()
    t = await db.get(Ticket, r.ticket_id)
    return _review_dict(r, t)
