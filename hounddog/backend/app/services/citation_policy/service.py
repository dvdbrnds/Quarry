"""Database layer for citation policy v2: config, flag, audit, pauses, appeals, fees, balances."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

import structlog
from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models.audit_log import AuditLog
from ...models.citation_policy import (
    CitationClockPause, CitationFee, CitationFeeTicket, PaymentAllocation,
)
from ...models.enforcement_settings import EnforcementSettings
from ...models.ticket import Ticket
from ..timeutils import to_local, today_local
from . import timeline as tl

logger = structlog.get_logger("quarry.citation_policy")

DISMISSED_STATUSES = ("voided", "resolved_permit")


# ── Config / flag ──────────────────────────────────────────────────────────

async def load_config(db: AsyncSession) -> tl.PolicyConfig:
    es = (await db.execute(select(EnforcementSettings).where(EnforcementSettings.id == 1))).scalar()
    return tl.PolicyConfig.from_settings(es, settings.barnacle_enabled)


async def barnacle_is_enabled(db: AsyncSession) -> bool:
    """Two keys: BARNACLE_ENABLED env var AND the Enforcement Settings toggle."""
    if not settings.barnacle_enabled:
        return False
    es = (await db.execute(select(EnforcementSettings.barnacle_enabled).where(EnforcementSettings.id == 1))).scalar()
    return bool(es)


async def require_barnacle(db: AsyncSession) -> tl.PolicyConfig:
    cfg = await load_config(db)
    if not cfg.barnacle_enabled:
        raise HTTPException(404, "Not found")
    return cfg


# ── Helpers ────────────────────────────────────────────────────────────────

def local_date(dt: datetime | None) -> date | None:
    return to_local(dt).date() if dt else None


def norm_plate(plate: str | None) -> str:
    return (plate or "").upper().replace(" ", "").replace("-", "")


def norm_state(state: str | None) -> str | None:
    s = (state or "").strip().upper()
    return s or None


def ticket_is_unpaid(t: Ticket) -> bool:
    return t.status not in tl.UNPAID_EXCLUDED_STATUSES and (t.fine_amount or 0) > 0


def ticket_policy(t: Ticket, cfg: tl.PolicyConfig) -> tuple[str | None, date | None]:
    """Stored policy fields, or what they will be once the daily job stamps the ticket."""
    if t.policy_version:
        start = t.timeline_start_date
        if t.policy_version == tl.LEGACY and start is None:
            start = cfg.legacy_deadline
        return t.policy_version, start
    if t.ticket_category not in (None, "parking"):
        return None, None
    return tl.policy_assignment(local_date(t.issued_at) or today_local(), cfg)


async def record_policy_event(
    db: AsyncSession,
    actor: str,
    resource_type: str,
    resource_id: str | uuid.UUID | None,
    summary: str,
    changes: dict | None = None,
) -> None:
    db.add(AuditLog(
        user_email=actor or "system",
        action="POLICY",
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        endpoint="citation-policy",
        summary=summary[:1024],
        changes=changes,
        response_status=200,
    ))


# ── Pauses ─────────────────────────────────────────────────────────────────

async def load_pauses(db: AsyncSession, ticket_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[tl.Pause]]:
    ids = list(ticket_ids)
    out: dict[uuid.UUID, list[tl.Pause]] = defaultdict(list)
    if not ids:
        return out
    rows = (await db.execute(
        select(CitationClockPause).where(CitationClockPause.ticket_id.in_(ids))
    )).scalars().all()
    for p in rows:
        out[p.ticket_id].append(tl.Pause(p.start_date, p.end_date, p.floor_elapsed, p.reason))
    return out


async def open_pause(
    db: AsyncSession, ticket: Ticket, reason: str, start: date, actor: str,
    *, end: date | None = None, floor_elapsed: int | None = None, plan_id: uuid.UUID | None = None,
) -> CitationClockPause:
    pause = CitationClockPause(
        ticket_id=ticket.id, reason=reason, start_date=start, end_date=end,
        floor_elapsed=floor_elapsed, plan_id=plan_id, created_by=actor,
    )
    db.add(pause)
    await record_policy_event(
        db, actor, "citation_pause", ticket.id,
        f"Clock paused ({reason}) on {ticket.ticket_number or ticket.id} from {start}"
        + (f" until {end}" if end else ""),
        {"reason": reason, "start": start.isoformat(), "end": end.isoformat() if end else None},
    )
    return pause


async def close_pauses(
    db: AsyncSession, ticket: Ticket, reasons: tuple[str, ...], end: date, actor: str, close_reason: str,
    *, plan_id: uuid.UUID | None = None,
) -> int:
    q = select(CitationClockPause).where(
        CitationClockPause.ticket_id == ticket.id,
        CitationClockPause.reason.in_(reasons),
        CitationClockPause.end_date.is_(None),
    )
    if plan_id is not None:
        q = q.where(CitationClockPause.plan_id == plan_id)
    rows = (await db.execute(q)).scalars().all()
    for p in rows:
        p.end_date = max(end, p.start_date)
        p.closed_by = actor
        p.close_reason = close_reason[:256]
        await record_policy_event(
            db, actor, "citation_pause", ticket.id,
            f"Clock resumed ({p.reason}) on {ticket.ticket_number or ticket.id}: {close_reason}",
            {"reason": p.reason, "end": p.end_date.isoformat()},
        )
    return len(rows)


# ── Appeals ────────────────────────────────────────────────────────────────

# email_sent_at is only tracked from here on; earlier tickets have it NULL.
EMAIL_TRACKING_START = datetime(2026, 9, 18, tzinfo=timezone.utc)
LATE_EMAIL_GRACE = timedelta(hours=1)


def appeal_window_start(ticket: Ticket) -> datetime:
    """When the appeal clock starts: issuance, unless the citation email went out late (or not
    at all), in which case the student gets a full window from when they were actually told."""
    issued = ticket.issued_at if ticket.issued_at.tzinfo else ticket.issued_at.replace(tzinfo=timezone.utc)
    emailed = bool(ticket.notification_email and "@" in ticket.notification_email)
    if not emailed or issued < EMAIL_TRACKING_START:
        return issued
    if ticket.email_sent_at is None:
        return max(issued, datetime.now(timezone.utc))
    sent = ticket.email_sent_at if ticket.email_sent_at.tzinfo else ticket.email_sent_at.replace(tzinfo=timezone.utc)
    return sent if sent > issued + LATE_EMAIL_GRACE else issued


def appeal_deadline(ticket: Ticket, cfg: tl.PolicyConfig, legacy_window_days: int) -> tuple[datetime | None, int]:
    """(deadline as an aware datetime, window days). v2 citations: end of day 10, campus time.
    Everything else keeps the old window. Both count from appeal_window_start."""
    version, _ = ticket_policy(ticket, cfg)
    if not ticket.issued_at:
        return None, cfg.due_day if version == tl.V2 else legacy_window_days
    start = appeal_window_start(ticket)
    if version == tl.V2:
        last_day = tl.appeal_deadline(local_date(start), cfg)
        tz = to_local(start).tzinfo
        end_local = datetime.combine(last_day + timedelta(days=1), datetime.min.time(), tzinfo=tz)
        return end_local - timedelta(microseconds=1), cfg.due_day
    return start + timedelta(days=legacy_window_days), legacy_window_days


async def appeal_deadline_for(db: AsyncSession, ticket: Ticket) -> tuple[datetime | None, int]:
    cfg = await load_config(db)
    es = (await db.execute(select(EnforcementSettings.appeal_window_days).where(EnforcementSettings.id == 1))).scalar()
    return appeal_deadline(ticket, cfg, es if es is not None else 5)


async def on_appeal_submitted(db: AsyncSession, ticket: Ticket, actor: str) -> None:
    ticket.appeal_submitted_at = datetime.now(timezone.utc)
    cfg = await load_config(db)
    version, _ = ticket_policy(ticket, cfg)
    if version:
        await open_pause(db, ticket, tl.PAUSE_APPEAL, today_local(), actor)


async def record_appeal_decision(
    db: AsyncSession, ticket: Ticket, decision: str, actor: str, reason: str | None = None,
) -> None:
    """The one place an appeal is decided. decision: 'approved' (dismissed) or 'denied'."""
    if decision not in ("approved", "denied"):
        raise ValueError(decision)
    now = datetime.now(timezone.utc)
    today = today_local()
    ticket.appeal_decision = decision
    ticket.appeal_decided_by = actor
    ticket.appeal_decided_at = now
    if reason:
        ticket.appeal_decision_reason = reason.strip()[:1024]

    await close_pauses(db, ticket, (tl.PAUSE_APPEAL,), today, actor, f"appeal {decision}")

    if decision == "approved":
        ticket.status = "voided"
        await void_fees_for_dismissed(db, ticket, actor, "Citation dismissed on appeal")
    else:
        ticket.status = "pending_payment"
        cfg = await load_config(db)
        version, _ = ticket_policy(ticket, cfg)
        if version:
            # Pay by end of decision + grace days; delinquent the day after if still unpaid.
            await open_pause(
                db, ticket, tl.PAUSE_APPEAL_GRACE, today, actor,
                end=today + timedelta(days=cfg.denied_grace_days + 1),
                floor_elapsed=cfg.late_fee_1_day,
            )
    await record_policy_event(
        db, actor, "ticket", ticket.id,
        f"Appeal {decision} on {ticket.ticket_number or ticket.id}" + (f": {reason}" if reason else ""),
        {"decision": decision},
    )


# ── Fees ───────────────────────────────────────────────────────────────────

async def create_fee(
    db: AsyncSession,
    *,
    fee_type: str,
    amount: Decimal,
    plate: str,
    plate_state: str | None,
    ticket_ids: list[uuid.UUID],
    actor: str,
    idempotency_key: str | None = None,
    reason: str | None = None,
    documentation: str | None = None,
    attachment: tuple[str, str, bytes] | None = None,
    deployment_id: uuid.UUID | None = None,
    owner_notification_id: uuid.UUID | None = None,
) -> CitationFee | None:
    """Insert a fee. With an idempotency key, a duplicate insert is a no-op and returns None."""
    if fee_type not in tl.FEE_TYPES:
        raise ValueError(f"Unknown fee type {fee_type}")
    if amount <= 0:
        return None
    values = dict(
        id=uuid.uuid4(), fee_type=fee_type, amount=amount, status="open",
        plate=norm_plate(plate), plate_state=norm_state(plate_state),
        reason=reason, documentation=documentation,
        attachment_name=attachment[0] if attachment else None,
        attachment_mime=attachment[1] if attachment else None,
        attachment_data=attachment[2] if attachment else None,
        idempotency_key=idempotency_key, deployment_id=deployment_id,
        owner_notification_id=owner_notification_id, created_by=actor,
    )
    stmt = pg_insert(CitationFee).values(**values)
    if idempotency_key:
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    fee_id = (await db.execute(stmt.returning(CitationFee.id))).scalar()
    if fee_id is None:
        return None
    for tid in dict.fromkeys(ticket_ids):
        db.add(CitationFeeTicket(fee_id=fee_id, ticket_id=tid))
    await db.flush()
    fee = await db.get(CitationFee, fee_id)
    await record_policy_event(
        db, actor, "citation_fee", fee_id,
        f"{fee_type} ${amount:.2f} added to {fee.plate}" + (f": {reason}" if reason else ""),
        {"fee_type": fee_type, "amount": str(amount), "ticket_ids": [str(t) for t in ticket_ids]},
    )
    return fee


async def resolve_fee(db: AsyncSession, fee: CitationFee, status: str, actor: str, reason: str) -> None:
    if status not in ("waived", "voided", "paid"):
        raise ValueError(status)
    if fee.status != "open":
        raise HTTPException(400, f"Fee is already {fee.status}")
    if status in ("waived", "voided") and not (reason or "").strip():
        raise HTTPException(400, "A reason is required")
    fee.status = status
    fee.resolved_by = actor
    fee.resolved_at = datetime.now(timezone.utc)
    fee.resolve_reason = (reason or "").strip() or None
    await record_policy_event(
        db, actor, "citation_fee", fee.id,
        f"{fee.fee_type} ${fee.amount:.2f} on {fee.plate} {status}" + (f": {reason}" if reason else ""),
        {"status": status},
    )


async def fee_ticket_ids(db: AsyncSession, fee_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, list[uuid.UUID]]:
    ids = list(fee_ids)
    out: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    if not ids:
        return out
    rows = (await db.execute(
        select(CitationFeeTicket.fee_id, CitationFeeTicket.ticket_id).where(CitationFeeTicket.fee_id.in_(ids))
    )).all()
    for fid, tid in rows:
        out[fid].append(tid)
    return out


async def fees_for_tickets(
    db: AsyncSession, ticket_ids: Iterable[uuid.UUID], *, open_only: bool = False,
) -> list[CitationFee]:
    ids = list(ticket_ids)
    if not ids:
        return []
    q = (
        select(CitationFee)
        .join(CitationFeeTicket, CitationFeeTicket.fee_id == CitationFee.id)
        .where(CitationFeeTicket.ticket_id.in_(ids))
        .distinct()
        .order_by(CitationFee.created_at)
    )
    if open_only:
        q = q.where(CitationFee.status == "open")
    return list((await db.execute(q)).scalars().all())


async def void_fees_for_dismissed(db: AsyncSession, ticket: Ticket, actor: str, reason: str) -> int:
    """Void open fees on a dismissed citation. A fee shared with other citations is voided only
    once every one of its citations is dismissed."""
    fees = await fees_for_tickets(db, [ticket.id], open_only=True)
    links = await fee_ticket_ids(db, [f.id for f in fees])
    voided = 0
    for fee in fees:
        others = [t for t in links.get(fee.id, []) if t != ticket.id]
        if others:
            statuses = (await db.execute(select(Ticket.status).where(Ticket.id.in_(others)))).scalars().all()
            if any(s not in DISMISSED_STATUSES for s in statuses):
                continue
        await resolve_fee(db, fee, "voided", actor, reason)
        voided += 1
    return voided


# ── Balances ───────────────────────────────────────────────────────────────

async def allocated_totals(
    db: AsyncSession, *, ticket_ids: Iterable[uuid.UUID] = (), fee_ids: Iterable[uuid.UUID] = (),
) -> tuple[dict[uuid.UUID, Decimal], dict[uuid.UUID, Decimal]]:
    """Partial payments already applied (payment plans): citation fines by ticket, fees by fee."""
    t_ids, f_ids = list(ticket_ids), list(fee_ids)
    by_ticket: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    by_fee: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    if t_ids:
        for tid, amt in (await db.execute(
            select(PaymentAllocation.ticket_id, func.sum(PaymentAllocation.amount))
            .where(PaymentAllocation.ticket_id.in_(t_ids), PaymentAllocation.fee_type == "CITATION")
            .group_by(PaymentAllocation.ticket_id)
        )).all():
            by_ticket[tid] = Decimal(amt)
    if f_ids:
        for fid, amt in (await db.execute(
            select(PaymentAllocation.fee_id, func.sum(PaymentAllocation.amount))
            .where(PaymentAllocation.fee_id.in_(f_ids))
            .group_by(PaymentAllocation.fee_id)
        )).all():
            by_fee[fid] = Decimal(amt)
    return by_ticket, by_fee


async def outstanding_items(db: AsyncSession, tickets: list[Ticket]) -> list[dict]:
    """Every unpaid fine and open fee for these tickets, oldest first, net of partial payments."""
    unpaid = [t for t in tickets if ticket_is_unpaid(t)]
    fees = await fees_for_tickets(db, [t.id for t in tickets], open_only=True)
    by_ticket, by_fee = await allocated_totals(
        db, ticket_ids=[t.id for t in unpaid], fee_ids=[f.id for f in fees],
    )
    items = []
    for t in sorted(unpaid, key=lambda t: t.issued_at or datetime.min.replace(tzinfo=timezone.utc)):
        owed = Decimal(t.fine_amount) - by_ticket.get(t.id, Decimal(0))
        if owed > 0:
            items.append({"kind": "CITATION", "ticket": t, "fee": None, "amount": owed,
                          "at": t.issued_at})
    for f in fees:
        owed = Decimal(f.amount) - by_fee.get(f.id, Decimal(0))
        if owed > 0:
            items.append({"kind": f.fee_type, "ticket": None, "fee": f, "amount": owed, "at": f.created_at})
    items.sort(key=lambda i: i["at"] or datetime.min.replace(tzinfo=timezone.utc))
    return items


async def tickets_for_plates(db: AsyncSession, plates: Iterable[str], plate_state: str | None = None) -> list[Ticket]:
    ps = sorted({norm_plate(p) for p in plates if p})
    if not ps:
        return []
    q = select(Ticket).where(func.upper(func.replace(Ticket.plate, " ", "")).in_(ps))
    if plate_state:
        q = q.where(func.upper(Ticket.plate_state) == plate_state.upper())
    return list((await db.execute(q)).scalars().all())


async def balance_for_tickets(db: AsyncSession, tickets: list[Ticket]) -> Decimal:
    return sum((i["amount"] for i in await outstanding_items(db, tickets)), Decimal("0.00"))


async def person_plates(db: AsyncSession, plate: str) -> set[str]:
    """Every plate on any permit belonging to the same person as this plate (by email or Okta id)."""
    from ..escalation import tag_sid_sql, tag_tied_sql

    p = norm_plate(plate)
    rows = (await db.execute(text(f"""
        WITH owners AS (
            SELECT LOWER(ow.email) AS email,
                   NULLIF(ow.moravian_id, '') AS mid,
                   CASE WHEN ow.is_tag_only THEN {tag_sid_sql("ow")} ELSE ow.student_id END AS sid
            FROM permits ow
            WHERE ow.deleted_at IS NULL AND :p = ANY(SELECT UPPER(REPLACE(x, ' ', '')) FROM unnest(ow.plates) x)
              AND (ow.is_tag_only = false OR {tag_tied_sql("ow")})
        )
        SELECT DISTINCT UPPER(REPLACE(x, ' ', ''))
        FROM permits pm, unnest(pm.plates) x
        WHERE pm.deleted_at IS NULL AND (pm.is_tag_only = false OR {tag_tied_sql("pm")}) AND EXISTS (
            SELECT 1 FROM owners o
            WHERE (o.email IS NOT NULL AND o.email LIKE '%@%' AND LOWER(pm.email) = o.email)
               OR (o.mid ~ '^[0-9]+$' AND pm.moravian_id = o.mid)
               OR (o.sid IS NOT NULL AND o.sid <> '' AND o.sid !~ '^[a-z_]+:'
                   AND o.sid = CASE WHEN pm.is_tag_only THEN {tag_sid_sql("pm")} ELSE pm.student_id END)
        )
    """), {"p": p})).scalars().all()
    return {p} | set(rows)


async def person_balance(db: AsyncSession, plate: str) -> Decimal:
    plates = await person_plates(db, plate)
    return await balance_for_tickets(db, await tickets_for_plates(db, plates))


async def is_affiliated(db: AsyncSession, plate: str) -> bool:
    """A non-visitor, non-tag permit on the plate, or a vehicle tag tied to a student."""
    from ..escalation import tag_tied_sql

    row = (await db.execute(text(f"""
        SELECT 1 FROM permits
        WHERE deleted_at IS NULL
          AND :p = ANY(SELECT UPPER(REPLACE(x, ' ', '')) FROM unnest(plates) x)
          AND (
                (is_tag_only = false AND permit_type NOT LIKE 'visitor%'
                 AND permit_type NOT IN ('guest', 'contracted_staff')
                 AND COALESCE(student_id, '') !~ '^[a-z_]+:')
             OR (permits.is_tag_only = true AND {tag_tied_sql("permits")})
          )
        LIMIT 1
    """), {"p": norm_plate(plate)})).first()
    return row is not None


async def active_exempt_plates(db: AsyncSession) -> set[str]:
    rows = (await db.execute(text(
        "SELECT plate FROM hold_exemptions WHERE plate IS NOT NULL AND expires_at > now()"
    ))).scalars().all()
    return {norm_plate(p) for p in rows}
