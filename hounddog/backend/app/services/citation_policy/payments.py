"""Citation-policy money: Stripe line items and metadata, fulfillment allocations, staff payments."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import sentry_sdk
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ...models.citation_policy import CitationFee, PaymentAllocation
from ...models.payment import Payment
from ...models.ticket import Ticket
from . import timeline as tl
from .notices import FEE_LABELS
from .service import allocated_totals, fee_ticket_ids, outstanding_items, record_policy_event, resolve_fee

CITATION = "CITATION"
PROCESSING_FEE = "PROCESSING_FEE"
AMOUNT_KEYS = {
    CITATION: "amt_citation",
    tl.LATE_FEE_1: "amt_late_fee_1",
    tl.LATE_FEE_2: "amt_late_fee_2",
    tl.BARNACLE_DEPLOYMENT: "amt_barnacle_deployment",
    tl.BARNACLE_DAMAGE: "amt_barnacle_damage",
    tl.OWNER_NOTIFICATION: "amt_owner_notification",
    tl.COLLECTION_COST: "amt_collection_cost",
    PROCESSING_FEE: "amt_processing_fee",
}


def gl_for(fee_type: str) -> tuple[str, str]:
    """(GL account, GL activity) for a fee type."""
    s = settings
    if fee_type in tl.LATE_FEE_TYPES:
        return s.gl_account_late_fees, s.gl_activity_late_fees
    if fee_type in tl.BARNACLE_FEE_TYPES:
        return s.gl_account_barnacle, s.gl_activity_barnacle
    if fee_type == tl.OWNER_NOTIFICATION:
        return s.gl_account_owner_notification, s.gl_activity_owner_notification
    if fee_type == tl.COLLECTION_COST:
        return s.gl_account_collection_cost, s.gl_activity_collection_cost
    if fee_type == PROCESSING_FEE:
        return s.gl_account_processing_fee, s.gl_activity_processing_fee
    return s.gl_account_citations, s.gl_activity_citations


def chunk_ids(ids: list[str], key: str, max_len: int = 500) -> dict[str, str]:
    """Split ids across key, key_1, key_2... so each Stripe metadata value stays under 500 chars."""
    chunks: dict[str, str] = {}
    current: list[str] = []
    length = 0
    idx = 0
    for i in ids:
        add = len(i) + (1 if current else 0)
        if current and length + add > max_len:
            chunks[key if idx == 0 else f"{key}_{idx}"] = ",".join(current)
            current, length, idx = [i], len(i), idx + 1
        else:
            current.append(i)
            length += add
    if current:
        chunks[key if idx == 0 else f"{key}_{idx}"] = ",".join(current)
    return chunks


def read_chunked(metadata: dict, key: str) -> list[str]:
    parts = [metadata.get(key, "")]
    idx = 1
    while f"{key}_{idx}" in metadata:
        parts.append(metadata[f"{key}_{idx}"])
        idx += 1
    return [x.strip() for x in ",".join(p for p in parts if p).split(",") if x.strip()]


async def checkout_items(db: AsyncSession, tickets: list[Ticket]) -> list[dict]:
    """Outstanding fines and open fees for the selected tickets, as checkout items."""
    items = []
    for i in await outstanding_items(db, tickets):
        t: Ticket | None = i["ticket"]
        f: CitationFee | None = i["fee"]
        ref = (t.ticket_number or str(t.id)[:8].upper()) if t else None
        items.append({
            "fee_type": i["kind"],
            "ticket_id": str(t.id) if t else None,
            "fee_id": str(f.id) if f else None,
            "cents": int((i["amount"] * 100).to_integral_value()),
            "name": f"Parking Citation {ref}" if t else FEE_LABELS.get(f.fee_type, f.fee_type),
            "description": (f"Plate: {t.plate} | Violation: {t.violation_type}" if t
                            else f"Plate: {f.plate}" + (f" ({f.plate_state})" if f.plate_state else "")),
        })
    return items


def stripe_line_items(items: list[dict], processing_fee_cents: int) -> list[dict]:
    out = []
    for it in items:
        acct, act = gl_for(it["fee_type"])
        md = {"fee_type": it["fee_type"], "gl_account": acct, "gl_activity": act}
        if it["fee_id"]:
            md["fee_id"] = it["fee_id"]
        else:
            md["ticket_id"] = it["ticket_id"]
        out.append({
            "price_data": {
                "currency": "usd",
                "product_data": {"name": it["name"], "description": it["description"], "metadata": md},
                "unit_amount": it["cents"],
            },
            "quantity": 1,
        })
    if processing_fee_cents > 0:
        acct, act = gl_for(PROCESSING_FEE)
        out.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": "Processing Fee",
                    "description": "Non-refundable online payment processing fee",
                    "metadata": {"fee_type": PROCESSING_FEE, "gl_account": acct, "gl_activity": act},
                },
                "unit_amount": processing_fee_cents,
            },
            "quantity": 1,
        })
    return out


def policy_metadata(items: list[dict], tickets: list[Ticket], processing_fee_cents: int) -> dict[str, str]:
    """Approved payment-intent metadata keys added on top of the existing ones."""
    totals: dict[str, int] = {}
    for it in items:
        totals[it["fee_type"]] = totals.get(it["fee_type"], 0) + it["cents"]
    if processing_fee_cents > 0:
        totals[PROCESSING_FEE] = processing_fee_cents
    versions = {t.policy_version or "none" for t in tickets}
    md = {
        "policy_version": versions.pop() if len(versions) == 1 else "mixed",
        "fee_types": ",".join(k for k in AMOUNT_KEYS if totals.get(k)),
    }
    for k, cents in totals.items():
        if cents:
            md[AMOUNT_KEYS[k]] = f"{cents / 100:.2f}"
    md.update(chunk_ids([it["fee_id"] for it in items if it["fee_id"]], "fee_ids"))
    return md


async def _allocate(db: AsyncSession, payment: Payment, fee_type: str, amount: Decimal,
                    ticket_id: uuid.UUID | None = None, fee_id: uuid.UUID | None = None) -> None:
    if amount <= 0:
        return
    db.add(PaymentAllocation(
        payment_id=payment.id, ticket_id=ticket_id, fee_id=fee_id, fee_type=fee_type, amount=amount,
    ))


async def record_checkout_allocations(
    db: AsyncSession, metadata: dict, payments: list[Payment], amount_total: Decimal, actor: str = "stripe",
) -> None:
    """After ticket Payment rows exist for a Stripe session: mark paid fees, write one allocation per
    item, and make each Payment.amount equal its allocations (so totals match amount_total)."""
    if not payments:
        return
    await db.flush()
    by_ticket = {p.ticket_id: p for p in payments if p.ticket_id}
    fine_alloc, _ = await allocated_totals(db, ticket_ids=list(by_ticket))
    allocated = {p.id: Decimal("0.00") for p in payments}

    for tid, p in by_ticket.items():
        ticket = await db.get(Ticket, tid)
        amt = Decimal(ticket.fine_amount) - fine_alloc.get(tid, Decimal(0))
        await _allocate(db, p, CITATION, amt, ticket_id=tid)
        allocated[p.id] += max(amt, Decimal(0))

    fee_ids = [uuid.UUID(f) for f in read_chunked(metadata, "fee_ids")]
    links = await fee_ticket_ids(db, fee_ids)
    _, fee_alloc = await allocated_totals(db, fee_ids=fee_ids)
    for fid in fee_ids:
        fee = await db.get(CitationFee, fid)
        if not fee:
            continue
        amt = Decimal(fee.amount) - fee_alloc.get(fid, Decimal(0))
        target = next((by_ticket[t] for t in links.get(fid, []) if t in by_ticket), payments[0])
        await _allocate(db, target, fee.fee_type, amt, fee_id=fid)
        allocated[target.id] += max(amt, Decimal(0))
        if fee.status == "open":
            await resolve_fee(db, fee, "paid", actor, "Paid online")

    processing = amount_total - sum(allocated.values())
    if processing > 0:
        await _allocate(db, payments[0], PROCESSING_FEE, processing)
        allocated[payments[0].id] += processing
    for p in payments:
        p.amount = allocated[p.id]
    await db.flush()


async def record_staff_payment(
    db: AsyncSession, *, tickets: list[Ticket], amount: Decimal, method: str, reference: str | None,
    actor: str, payment_type: str, description: str, payer_name: str | None = None,
) -> tuple[Payment, list[dict]]:
    """Apply an in-person payment to the oldest outstanding items first."""
    items = await outstanding_items(db, tickets)
    outstanding = sum((i["amount"] for i in items), Decimal("0.00"))
    if amount <= 0:
        raise HTTPException(400, "Amount must be positive")
    if amount > outstanding:
        raise HTTPException(400, f"Amount exceeds the outstanding balance (${outstanding:.2f})")

    first_ticket = next((i["ticket"] for i in items if i["ticket"] is not None), tickets[0] if tickets else None)
    payment = Payment(
        ticket_id=first_ticket.id if first_ticket else None, amount=amount, method=method,
        bursar_reference=(reference or None), payment_type=payment_type, payer_name=payer_name,
        plate=first_ticket.plate if first_ticket else None, description=description[:512],
        paid_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    await db.flush()

    applied = tl.allocate(amount, [(str(n), i["amount"]) for n, i in enumerate(items)])
    touched = []
    plates = set()
    for key, amt in applied:
        i = items[int(key)]
        t: Ticket | None = i["ticket"]
        f: CitationFee | None = i["fee"]
        await _allocate(db, payment, i["kind"], amt, ticket_id=t.id if t else None, fee_id=f.id if f else None)
        fully = amt >= i["amount"]
        if t is not None and fully:
            t.status = "paid"
            plates.add(t.plate)
        if f is not None and fully and f.status == "open":
            await resolve_fee(db, f, "paid", actor, f"Paid ({method})")
        touched.append({"kind": i["kind"], "ticket_id": str(t.id) if t else None,
                        "fee_id": str(f.id) if f else None, "amount": str(amt), "fully_paid": fully})
    await db.flush()
    await record_policy_event(
        db, actor, "payment", payment.id, f"{payment_type} ${amount:.2f} recorded ({method})",
        {"allocations": touched},
    )
    from ..escalation import check_and_resolve_on_payment
    for plate in plates:
        try:
            await check_and_resolve_on_payment(db, plate)
        except Exception as e:
            sentry_sdk.capture_exception(e)
    return payment, touched


async def allocations_by_payment(db: AsyncSession, payment_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[PaymentAllocation]]:
    out: dict[uuid.UUID, list[PaymentAllocation]] = {}
    if not payment_ids:
        return out
    rows = (await db.execute(
        select(PaymentAllocation).where(PaymentAllocation.payment_id.in_(payment_ids))
    )).scalars().all()
    for a in rows:
        out.setdefault(a.payment_id, []).append(a)
    return out
