"""Daily citation-policy job.

Runs once per local day after the configured hour. Phase 1 (one transaction, advisory lock)
stamps policy fields, handles payment-plan defaults, and inserts fees, notices and MUPD reviews
keyed on unique idempotency keys. Phase 2 delivers queued email notices. Rerunning on the same
day (or concurrently) cannot double-charge or double-send: the run marker short-circuits, and
even without it every insert is ON CONFLICT DO NOTHING.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models.citation_policy import (
    CitationFee, CitationFeeTicket, MupdReview, PaymentPlan, PaymentPlanCitation,
    PaymentPlanInstallment,
)
from ...models.ticket import Ticket
from ..timeutils import now_local, today_local
from . import timeline as tl
from .notices import FEE_LABELS, NoticeContext, create_notice, deliver_pending_emails, recipient_for
from .service import (
    active_exempt_plates, balance_for_tickets, close_pauses, fees_for_tickets, is_affiliated,
    load_config, load_pauses, local_date, norm_plate, norm_state, outstanding_items,
    record_policy_event, ticket_is_unpaid,
)
from .vehicle import citation_state, vehicle_eligibility

logger = structlog.get_logger("quarry.citation_policy.job")

JOB_LOCK_ID = 4848
LAST_RUN_KEY = "citation_policy_last_run"
ACTOR = "system"


def _tz() -> str:
    return settings.app_timezone or "America/New_York"


async def stamp_policy_fields(db: AsyncSession, cfg: tl.PolicyConfig) -> dict:
    if not cfg.active:
        return {}
    params = {"tz": _tz(), "eff": cfg.effective_date, "deadline": cfg.legacy_deadline}
    v2 = await db.execute(text("""
        UPDATE tickets SET policy_version = 'v2',
               timeline_start_date = (issued_at AT TIME ZONE :tz)::date,
               stage = COALESCE(stage, 'current')
        WHERE policy_version IS NULL AND COALESCE(ticket_category, 'parking') = 'parking'
          AND (issued_at AT TIME ZONE :tz)::date >= :eff
    """), params)
    legacy = await db.execute(text("""
        UPDATE tickets SET policy_version = 'legacy', timeline_start_date = :deadline
        WHERE policy_version IS NULL AND COALESCE(ticket_category, 'parking') = 'parking'
          AND (issued_at AT TIME ZONE :tz)::date < :eff
    """), params)
    # A legacy deadline set or moved later applies to legacy citations that haven't entered yet.
    moved = await db.execute(text("""
        UPDATE tickets SET timeline_start_date = :deadline
        WHERE policy_version = 'legacy' AND stage IS NULL
          AND timeline_start_date IS DISTINCT FROM :deadline
    """), params)
    return {"v2": v2.rowcount, "legacy": legacy.rowcount, "legacy_moved": moved.rowcount}


async def process_payment_plans(db: AsyncSession, today: date) -> dict:
    defaulted = completed = 0
    plans = (await db.execute(select(PaymentPlan).where(PaymentPlan.status == "active"))).scalars().all()
    for plan in plans:
        ticket_ids = (await db.execute(
            select(PaymentPlanCitation.ticket_id).where(PaymentPlanCitation.plan_id == plan.id)
        )).scalars().all()
        tickets = (await db.execute(select(Ticket).where(Ticket.id.in_(ticket_ids)))).scalars().all() if ticket_ids else []

        if tickets and await balance_for_tickets(db, list(tickets)) <= 0:
            plan.status = "completed"
            plan.closed_at = datetime.now(timezone.utc)
            plan.closed_by = ACTOR
            for t in tickets:
                await close_pauses(db, t, (tl.PAUSE_PAYMENT_PLAN,), today, ACTOR, "plan completed", plan_id=plan.id)
            await record_policy_event(db, ACTOR, "payment_plan", plan.id, f"Payment plan completed for {plan.payer_name}")
            completed += 1
            continue

        missed = (await db.execute(
            select(func.count()).select_from(PaymentPlanInstallment).where(
                PaymentPlanInstallment.plan_id == plan.id,
                PaymentPlanInstallment.paid_at.is_(None),
                PaymentPlanInstallment.due_date < today,
            )
        )).scalar() or 0
        if missed:
            plan.status = "defaulted"
            plan.defaulted_at = datetime.now(timezone.utc)
            for t in tickets:
                await close_pauses(db, t, (tl.PAUSE_PAYMENT_PLAN,), today, ACTOR, "plan defaulted", plan_id=plan.id)
            await record_policy_event(
                db, ACTOR, "payment_plan", plan.id,
                f"Payment plan defaulted for {plan.payer_name} ({missed} missed installment(s)); clocks resume",
            )
            defaulted += 1
    return {"plans_defaulted": defaulted, "plans_completed": completed}


async def _context(db: AsyncSession, tickets: list[Ticket], cfg: tl.PolicyConfig, **extra) -> NoticeContext:
    items = await outstanding_items(db, tickets)
    first = tickets[0]
    return NoticeContext(
        plate=norm_plate(first.plate),
        plate_state=norm_state(first.plate_state),
        citations=[{
            "number": t.ticket_number or str(t.id)[:8].upper(),
            "issued_on": local_date(t.issued_at),
            "fine": Decimal(t.fine_amount),
        } for t in tickets],
        fees=[{"label": FEE_LABELS.get(i["kind"], i["kind"]), "amount": i["amount"]}
              for i in items if i["fee"] is not None],
        balance=sum((i["amount"] for i in items), Decimal("0.00")),
        pay_url=f"{settings.student_facing_url}/pay?ticket={first.id}",
        barnacle_enabled=cfg.barnacle_enabled,
        barnacle_fee=cfg.barnacle_fee,
        barnacle_rule=(cfg.barnacle_min_citations, cfg.barnacle_delinquent_days),
        schedule=(cfg.reminder_day, cfg.late_fee_1_day, cfg.late_fee_2_day),
        legacy_deadline=cfg.legacy_deadline,
        **extra,
    )


async def _existing_late_fees(db: AsyncSession, ticket_id: uuid.UUID) -> Decimal:
    total = (await db.execute(
        select(func.coalesce(func.sum(CitationFee.amount), 0))
        .join(CitationFeeTicket, CitationFeeTicket.fee_id == CitationFee.id)
        .where(
            CitationFeeTicket.ticket_id == ticket_id,
            CitationFee.fee_type.in_(tl.LATE_FEE_TYPES),
            CitationFee.status != "voided",
        )
    )).scalar()
    return Decimal(total or 0)


async def process_citations(db: AsyncSession, cfg: tl.PolicyConfig, today: date) -> dict:
    from .service import create_fee

    counts = defaultdict(int)
    exempt = await active_exempt_plates(db)
    tickets = (await db.execute(
        select(Ticket).where(
            Ticket.policy_version.in_((tl.V2, tl.LEGACY)),
            Ticket.timeline_start_date.isnot(None),
            Ticket.timeline_start_date <= today,
            func.coalesce(Ticket.ticket_category, "parking") == "parking",
            Ticket.fine_amount > 0,
            Ticket.status.notin_(tl.UNPAID_EXCLUDED_STATUSES),
        )
    )).scalars().all()
    pauses = await load_pauses(db, [t.id for t in tickets])
    vehicles: dict[tuple[str, str], list[Ticket]] = defaultdict(list)

    for t in tickets:
        cs, _ = citation_state(t, pauses.get(t.id, []), cfg, today)
        if cs.paused_reason:
            counts["paused"] += 1
            continue
        t.stage = tl.stage_for(cs.elapsed, cfg)
        dd = tl.delinquent_days(cs.elapsed, cfg)
        if dd is not None and t.delinquent_since is None:
            t.delinquent_since = today if dd == 0 else date.fromordinal(today.toordinal() - dd)
        if norm_plate(t.plate) in exempt:
            counts["exempt"] += 1
            continue
        if t.plate_state:
            vehicles[(norm_plate(t.plate), norm_state(t.plate_state))].append(t)

        for fee_type in tl.fees_due(cs.elapsed, cfg):
            amount = tl.late_fee_amount(fee_type, await _existing_late_fees(db, t.id), cfg)
            if amount <= 0:
                continue
            fee = await create_fee(
                db, fee_type=fee_type, amount=amount, plate=t.plate, plate_state=t.plate_state,
                ticket_ids=[t.id], actor=ACTOR, idempotency_key=f"{fee_type}:{t.id}",
            )
            if fee:
                counts[fee_type] += 1

        notice_type = tl.notice_due(cs.elapsed, cfg)
        if notice_type:
            extra = {"next_step": tl.next_escalation(cs.elapsed, today, cfg)}
            if notice_type == tl.NOTICE_REMINDER and t.issued_at:
                extra["appeal_deadline"] = tl.appeal_deadline(local_date(t.issued_at), cfg) if t.policy_version == tl.V2 else None
            if notice_type == tl.NOTICE_FINAL and cfg.barnacle_enabled and t.plate_state:
                v = await vehicle_eligibility(db, t.plate, t.plate_state, cfg, today)
                extra["earliest_date"] = v["eligibility"].earliest_date
            channel, recipient = await recipient_for(db, t)
            ctx = await _context(db, [t], cfg, **extra)
            if await create_notice(
                db, key=f"NOTICE:{notice_type}:{t.id}", notice_type=notice_type,
                channel=channel, recipient=recipient, ctx=ctx, ticket_ids=[t.id],
            ):
                counts[f"notice_{notice_type}"] += 1

        if dd is not None and not await is_affiliated(db, t.plate):
            inserted = (await db.execute(
                pg_insert(MupdReview).values(
                    id=uuid.uuid4(), ticket_id=t.id, plate=norm_plate(t.plate),
                    plate_state=norm_state(t.plate_state), status="open",
                    incident_documentation=_incident_text(t), created_by=ACTOR,
                ).on_conflict_do_nothing(index_elements=["ticket_id"]).returning(MupdReview.id)
            )).scalar()
            if inserted:
                await record_policy_event(
                    db, ACTOR, "mupd_review", inserted,
                    f"Non-affiliated delinquent citation {t.ticket_number or t.id} flagged for MUPD review",
                )
                counts["mupd_flagged"] += 1

    if cfg.barnacle_enabled:
        for (plate, state), _ in vehicles.items():
            v = await vehicle_eligibility(db, plate, state, cfg, today)
            elig: tl.Eligibility = v["eligibility"]
            if not elig.should_issue_warning:
                continue
            warn_tickets = [t for t in v["vehicle_tickets"] if str(t.id) in set(elig.warning_candidates)]
            if not warn_tickets:
                continue
            channel, recipient = await recipient_for(db, warn_tickets[0])
            ctx = await _context(db, warn_tickets, cfg, earliest_date=elig.earliest_date)
            if await create_notice(
                db, key=f"NOTICE:{tl.NOTICE_BARNACLE_WARNING}:{plate}:{state}:{today.isoformat()}",
                notice_type=tl.NOTICE_BARNACLE_WARNING, channel=channel, recipient=recipient,
                ctx=ctx, ticket_ids=[t.id for t in warn_tickets],
            ):
                counts["barnacle_warnings"] += 1

    counts["processed"] = len(tickets)
    return dict(counts)


def _incident_text(t: Ticket) -> str:
    parts = [
        f"Citation {t.ticket_number or t.id}",
        f"Issued {t.issued_at.isoformat() if t.issued_at else ''}",
        f"Lot: {t.lot or ''} {t.zone or ''}".strip(),
        f"Violation: {t.violation_type}",
        f"Officer: {t.officer_name or t.officer_email or t.officer_id}",
    ]
    if t.location_text:
        parts.append(f"Location: {t.location_text}")
    if t.officer_notes:
        parts.append(f"Officer notes: {t.officer_notes}")
    return "\n".join(parts)


async def send_rollout_notices(db: AsyncSession, cfg: tl.PolicyConfig, today: date) -> int:
    """One notice per recipient with unpaid legacy citations, once the legacy deadline is set."""
    if not cfg.legacy_deadline or today >= cfg.legacy_deadline:
        return 0
    tickets = (await db.execute(
        select(Ticket).where(
            Ticket.policy_version == tl.LEGACY,
            Ticket.fine_amount > 0,
            Ticket.status.notin_(tl.UNPAID_EXCLUDED_STATUSES),
        ).order_by(Ticket.issued_at)
    )).scalars().all()
    groups: dict[tuple[str, str], list[Ticket]] = defaultdict(list)
    for t in tickets:
        channel, recipient = await recipient_for(db, t)
        key = recipient if channel == "email" else f"plate:{norm_plate(t.plate)}"
        groups[(channel, key)].append(t)
    sent = 0
    for (channel, key), group in groups.items():
        recipient = key if channel == "email" else (await recipient_for(db, group[0]))[1]
        ctx = await _context(db, group, cfg)
        if await create_notice(
            db, key=f"NOTICE:{tl.NOTICE_ROLLOUT}:{key}", notice_type=tl.NOTICE_ROLLOUT,
            channel=channel, recipient=recipient, ctx=ctx, ticket_ids=[t.id for t in group],
        ):
            sent += 1
    return sent


async def run_phase_one(db: AsyncSession, today: date, *, force: bool = False) -> dict | None:
    """Everything except email delivery. Caller owns the transaction."""
    cfg = await load_config(db)
    if not cfg.active:
        return None
    if not force and now_local().hour < cfg.job_hour:
        return None
    got = (await db.execute(text("SELECT pg_try_advisory_xact_lock(:k)"), {"k": JOB_LOCK_ID})).scalar()
    if not got:
        return None
    last = (await db.execute(text("SELECT value FROM system_settings WHERE key = :k"), {"k": LAST_RUN_KEY})).scalar()
    if last == today.isoformat() and not force:
        return None

    result = {"stamped": await stamp_policy_fields(db, cfg)}
    result.update(await process_payment_plans(db, today))
    result.update(await process_citations(db, cfg, today))
    result["rollout_notices"] = await send_rollout_notices(db, cfg, today)

    await db.execute(text("""
        INSERT INTO system_settings (key, value, updated_by) VALUES (:k, :v, 'citation-policy-job')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
    """), {"k": LAST_RUN_KEY, "v": today.isoformat()})
    await record_policy_event(db, ACTOR, "citation_policy_job", today.isoformat(),
                              f"Daily citation policy job ran for {today.isoformat()}", result)
    return result


async def run_daily_job(session_factory, *, force: bool = False, today: date | None = None) -> dict | None:
    today = today or today_local()
    async with session_factory() as db:
        async with db.begin():
            result = await run_phase_one(db, today, force=force)
    delivery = await deliver_pending_emails(session_factory)
    if result is None:
        return None if not (delivery["sent"] or delivery["failed"]) else {"delivery": delivery}
    result["delivery"] = delivery
    logger.info("citation_policy_job", **{k: v for k, v in result.items() if not isinstance(v, dict)})
    return result
