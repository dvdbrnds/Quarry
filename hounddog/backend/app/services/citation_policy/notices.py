"""Citation notices: rendering, recipient selection, idempotent creation, and delivery.

A notice row is inserted (keyed on idempotency_key) before anything is sent. Email delivery
then claims each pending row with FOR UPDATE SKIP LOCKED in its own transaction, so a rerun or
a second worker can never send the same notice twice. Mail notices count as sent only when
staff mark them mailed.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from app import error_reporting
import structlog
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models.citation_policy import CitationNotice
from ...models.permit import Permit
from ...models.ticket import Ticket
from . import timeline as tl
from .service import norm_plate, record_policy_event

logger = structlog.get_logger("quarry.citation_policy.notices")

MAX_ATTEMPTS = 3


def fmt_date(d: date | None) -> str:
    return d.strftime("%B %-d, %Y") if d else ""


@dataclass
class NoticeContext:
    plate: str
    plate_state: str | None
    citations: list[dict]  # {number, issued_on: date, fine: Decimal}
    fees: list[dict] = field(default_factory=list)  # {label, amount}
    balance: Decimal = Decimal("0.00")
    pay_url: str = ""
    appeal_deadline: date | None = None
    next_step: tuple[str, date] | None = None
    barnacle_enabled: bool = False
    earliest_date: date | None = None
    barnacle_fee: Decimal = Decimal("100.00")
    barnacle_rule: tuple[int, int] = (3, 30)  # min delinquent citations, oldest delinquent days
    legacy_deadline: date | None = None
    schedule: tuple[int, int, int] = (7, 11, 31)  # reminder, late fee 1, late fee 2 days
    office_contact: str = ""


FEE_LABELS = {
    tl.LATE_FEE_1: "Late fee (day 11)",
    tl.LATE_FEE_2: "Late fee (day 31)",
    tl.BARNACLE_DEPLOYMENT: "Barnacle deployment fee",
    tl.BARNACLE_DAMAGE: "Barnacle damage",
    tl.OWNER_NOTIFICATION: "Registered-owner notification",
    tl.COLLECTION_COST: "Collection cost",
}


def _vehicle(ctx: NoticeContext) -> str:
    return f"{ctx.plate} ({ctx.plate_state})" if ctx.plate_state else ctx.plate


def render(notice_type: str, ctx: NoticeContext) -> tuple[str, str, list[str]]:
    """Return (subject, plain-text body, paragraphs) for a notice. Pure; used for snapshots."""
    vehicle = _vehicle(ctx)
    lines = [f"Vehicle: {vehicle}", "Citations:"]
    for c in ctx.citations:
        lines.append(f"  - {c['number']} issued {fmt_date(c['issued_on'])}: ${c['fine']:.2f}")
    for f in ctx.fees:
        lines.append(f"  - {f['label']}: ${f['amount']:.2f}")
    lines.append(f"Outstanding balance: ${ctx.balance:.2f}")
    summary = "\n".join(lines)

    pay = f"Pay online at {ctx.pay_url}" if ctx.pay_url else "Pay online through the parking payment portal"
    pay += ", or contact the parking office to pay in person or ask about a payment plan."
    nxt = ""
    if ctx.next_step:
        label, when = ctx.next_step
        nxt = {
            "delinquent": f"If unpaid, the citation becomes delinquent on {fmt_date(when)} and a late fee is added.",
            "final": f"If unpaid, an additional late fee is added on {fmt_date(when)}.",
        }.get(label, "")

    paras: list[str]
    if notice_type == tl.NOTICE_REMINDER:
        subject = f"Reminder: parking citation due — {vehicle}"
        paras = [
            "This is a reminder that you have an unpaid parking citation.",
            summary, pay,
            f"You may appeal through {fmt_date(ctx.appeal_deadline)}." if ctx.appeal_deadline else "",
            nxt,
        ]
    elif notice_type == tl.NOTICE_DELINQUENCY_1:
        subject = f"Delinquent parking citation — {vehicle}"
        paras = [
            "Your parking citation was not paid or appealed by its due date and is now delinquent. "
            "A late fee has been added.",
            summary, pay, nxt,
        ]
    elif notice_type == tl.NOTICE_FINAL:
        subject = f"Final notice: delinquent parking citation — {vehicle}"
        paras = [
            "Final notice. Your parking citation remains unpaid and an additional late fee has been added.",
            summary, pay,
        ]
        if ctx.barnacle_enabled:
            paras.append(
                f"Vehicles with {ctx.barnacle_rule[0]} or more delinquent citations, the oldest delinquent "
                f"at least {ctx.barnacle_rule[1]} days, "
                "may be immobilized with a Barnacle after a separate final warning. "
                f"Deployment adds a ${ctx.barnacle_fee:.0f} fee."
            )
            if ctx.earliest_date:
                paras.append(f"Based on your current citations, the earliest possible deployment date is {fmt_date(ctx.earliest_date)}.")
    elif notice_type == tl.NOTICE_BARNACLE_WARNING:
        subject = f"Barnacle final warning — {vehicle}"
        paras = [
            "Final warning before vehicle immobilization.",
            summary,
            f"If your vehicle is immobilized, a ${ctx.barnacle_fee:.0f} deployment fee is added to your balance.",
            pay,
            "If you cannot pay in full, contact the parking office before the date below to arrange a payment plan.",
            tl.BARNACLE_WARNING_SENTENCE.format(date=fmt_date(ctx.earliest_date)),
        ]
    elif notice_type == tl.NOTICE_ROLLOUT:
        subject = f"Changes to parking citation late fees — {vehicle}"
        paras = [
            "Moravian University is updating its parking citation policy. Late fees now apply to citations "
            "that are not paid or appealed on time.",
            summary,
            f"No late fees will be charged on these citations if they are resolved by {fmt_date(ctx.legacy_deadline)}. "
            f"After that date they follow the new schedule as if issued that day: a reminder on day "
            f"{ctx.schedule[0]}, a late fee on day {ctx.schedule[1]}, and a second late fee on day {ctx.schedule[2]}.",
            pay,
        ]
    else:
        raise ValueError(notice_type)

    paras = [p for p in paras if p]
    if ctx.office_contact:
        paras.append(ctx.office_contact)
    body = "\n\n".join(paras)
    return subject, body, paras


async def render_html(paras: list[str]) -> str:
    from ..email import branded_email_shell

    inner = "".join(
        f'<p style="margin:0 0 14px;font-size:14px;line-height:1.5;color:#333;white-space:pre-line;">'
        f"{html.escape(p)}</p>"
        for p in paras
    )
    return await branded_email_shell(settings.school_name or "Campus", inner)


async def recipient_for(db: AsyncSession, ticket: Ticket) -> tuple[str, str]:
    """('email', address) when we have one, else ('mail', name/address for the mail queue)."""
    for candidate in (ticket.notification_email, ticket.dispute_email):
        if candidate and "@" in candidate:
            return "email", candidate.strip().lower()
    permit = (await db.execute(
        select(Permit).where(
            Permit.plates.contains([norm_plate(ticket.plate)]),
            Permit.deleted_at.is_(None),
            Permit.email.isnot(None),
            (Permit.is_tag_only.is_(False)) | (Permit.owner_verified_at.isnot(None)),
        ).order_by(Permit.is_tag_only.asc()).limit(1)
    )).scalar()
    if permit and permit.email and "@" in permit.email:
        return "email", permit.email.strip().lower()
    parts = [p for p in (ticket.owner_name, ticket.owner_address) if p]
    return "mail", "\n".join(parts)


async def create_notice(
    db: AsyncSession,
    *,
    key: str,
    notice_type: str,
    channel: str,
    recipient: str,
    ctx: NoticeContext,
    ticket_ids: list[uuid.UUID],
    actor: str = "system",
) -> CitationNotice | None:
    """Insert a notice snapshot. Returns None if a notice with this key already exists."""
    subject, body_text, paras = render(notice_type, ctx)
    body_html = await render_html(paras)
    notice_id = (await db.execute(
        pg_insert(CitationNotice).values(
            id=uuid.uuid4(), notice_type=notice_type, channel=channel, recipient=recipient,
            plate=norm_plate(ctx.plate), plate_state=ctx.plate_state,
            ticket_ids=[str(t) for t in ticket_ids], subject=subject,
            body_html=body_html, body_text=body_text, balance=ctx.balance,
            earliest_date=ctx.earliest_date, status="pending", attempts=0,
            idempotency_key=key, created_by=actor,
        ).on_conflict_do_nothing(index_elements=["idempotency_key"]).returning(CitationNotice.id)
    )).scalar()
    if notice_id is None:
        return None
    await record_policy_event(
        db, actor, "citation_notice", notice_id,
        f"{notice_type} notice queued ({channel}) for {_vehicle(ctx)}",
        {"key": key, "channel": channel},
    )
    return await db.get(CitationNotice, notice_id)


async def deliver_pending_emails(session_factory, limit: int = 500) -> dict:
    """Send pending email notices one at a time, each claimed and committed on its own."""
    from ..email import send_email

    sent = failed = 0
    for _ in range(limit):
        async with session_factory() as db:
            async with db.begin():
                row = (await db.execute(text("""
                    SELECT id FROM citation_notices
                    WHERE channel = 'email' AND status IN ('pending', 'failed') AND attempts < :max
                    ORDER BY created_at
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED
                """), {"max": MAX_ATTEMPTS})).first()
                if not row:
                    break
                notice = await db.get(CitationNotice, row[0])
                notice.attempts += 1
                try:
                    ok = await send_email(
                        [notice.recipient], notice.subject, notice.body_html, notice.body_text,
                        from_override=settings.citation_from_address or None,
                    )
                except Exception as e:
                    error_reporting.capture_exception(e)
                    ok = False
                    notice.last_error = str(e)[:1000]
                if ok:
                    notice.status = "sent"
                    notice.sent_at = datetime.now(timezone.utc)
                    notice.last_error = None
                    sent += 1
                else:
                    notice.status = "failed"
                    notice.last_error = notice.last_error or "send_email returned False"
                    failed += 1
                    if notice.attempts >= MAX_ATTEMPTS:
                        error_reporting.capture_message(
                            f"Citation notice {notice.id} ({notice.notice_type}) failed {MAX_ATTEMPTS} times",
                            level="error",
                        )
    if sent or failed:
        logger.info("citation_notices_delivered", sent=sent, failed=failed)
    return {"sent": sent, "failed": failed}


async def mark_mailed(db: AsyncSession, notice: CitationNotice, actor: str, address: str | None) -> None:
    if notice.channel != "mail":
        raise ValueError("Only mail notices can be marked mailed")
    if notice.status == "sent":
        return
    if address:
        notice.recipient = address.strip()[:512]
    notice.status = "sent"
    notice.sent_at = datetime.now(timezone.utc)
    notice.mailed_by = actor
    await record_policy_event(
        db, actor, "citation_notice", notice.id,
        f"{notice.notice_type} notice for {notice.plate} marked mailed",
        {"recipient": notice.recipient},
    )
