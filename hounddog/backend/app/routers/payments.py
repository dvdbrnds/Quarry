import csv
import io
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.payment import Payment
from ..models.ticket import Ticket
from ..schemas.payment import (
    BursarImportPayload,
    BursarImportResult,
    CheckoutRequest,
    CheckoutResponse,
    PaymentRead,
    RevenueReport,
)

router = APIRouter()


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(data: CheckoutRequest, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided"):
        raise HTTPException(400, f"Ticket is already {ticket.status}")

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Parking Ticket #{str(ticket.id)[:8]}",
                    "description": f"Plate: {ticket.plate} | Violation: {ticket.violation_type}",
                },
                "unit_amount": int(ticket.fine_amount * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{base_url}{data.success_url}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}{data.cancel_url}",
        metadata={"ticket_id": str(ticket.id)},
    )

    ticket.status = "pending_payment"
    await db.flush()

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    import stripe
    stripe.api_key = settings.stripe_secret_key

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig, settings.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        ticket_id = session.get("metadata", {}).get("ticket_id")
        if ticket_id:
            ticket = await db.get(Ticket, uuid.UUID(ticket_id))
            if ticket:
                payment = Payment(
                    ticket_id=ticket.id,
                    amount=Decimal(session["amount_total"]) / 100,
                    method="online_card",
                    stripe_payment_id=session["payment_intent"],
                )
                db.add(payment)
                ticket.status = "paid"
                await db.flush()

    return {"status": "ok"}


@router.post("/bursar-import", response_model=BursarImportResult)
async def bursar_import(
    payload: BursarImportPayload, db: AsyncSession = Depends(get_db)
):
    matched = 0
    unmatched = 0
    errors: list[str] = []

    for row in payload.payments:
        try:
            ticket_uuid = uuid.UUID(row.ticket_id)
        except ValueError:
            result = await db.execute(
                select(Ticket).where(Ticket.plate == row.ticket_id.upper())
            )
            ticket = result.scalars().first()
            if not ticket:
                unmatched += 1
                errors.append(f"No ticket found for: {row.ticket_id}")
                continue
            ticket_uuid = ticket.id

        ticket = await db.get(Ticket, ticket_uuid)
        if not ticket:
            unmatched += 1
            errors.append(f"Ticket not found: {row.ticket_id}")
            continue

        if ticket.status == "paid":
            errors.append(f"Already paid: {row.ticket_id}")
            continue

        paid_at = datetime.now(timezone.utc)
        if row.paid_date:
            try:
                paid_at = datetime.fromisoformat(row.paid_date).replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        payment = Payment(
            ticket_id=ticket.id,
            amount=row.amount,
            method="bursar",
            bursar_reference=row.reference,
            paid_at=paid_at,
        )
        db.add(payment)
        ticket.status = "paid"
        matched += 1

    await db.flush()
    return BursarImportResult(matched=matched, unmatched=unmatched, errors=errors)


@router.post("/bursar-import-csv", response_model=BursarImportResult)
async def bursar_import_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    rows = []
    for row in reader:
        rows.append({
            "ticket_id": row.get("ticket_id", row.get("plate", "")),
            "amount": Decimal(row.get("amount", "0")),
            "reference": row.get("reference", row.get("bursar_reference", "")),
            "paid_date": row.get("paid_date", ""),
        })

    payload = BursarImportPayload(payments=[
        {"ticket_id": r["ticket_id"], "amount": r["amount"],
         "reference": r["reference"], "paid_date": r["paid_date"]}
        for r in rows
    ])
    return await bursar_import(payload, db)


@router.get("/revenue", response_model=RevenueReport)
async def revenue_report(db: AsyncSession = Depends(get_db)):
    total_fines = (
        await db.execute(select(func.sum(Ticket.fine_amount)))
    ).scalar() or Decimal(0)

    total_collected = (
        await db.execute(select(func.sum(Payment.amount)))
    ).scalar() or Decimal(0)

    total_outstanding = total_fines - total_collected

    rate = float(total_collected / total_fines * 100) if total_fines > 0 else 0.0

    method_result = await db.execute(
        select(Payment.method, func.sum(Payment.amount)).group_by(Payment.method)
    )
    by_method = {row[0]: row[1] for row in method_result.all()}

    status_result = await db.execute(
        select(Ticket.status, func.count()).group_by(Ticket.status)
    )
    by_status = {row[0]: row[1] for row in status_result.all()}

    return RevenueReport(
        total_fines_issued=total_fines,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        collection_rate=rate,
        by_method=by_method,
        by_status=by_status,
    )


@router.get("/ticket/{ticket_id}", response_model=list[PaymentRead])
async def payments_for_ticket(ticket_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Payment).where(Payment.ticket_id == ticket_id).order_by(Payment.paid_at)
    )
    return result.scalars().all()


@router.get("/export/csv")
async def export_payments(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Payment).order_by(Payment.paid_at.desc()))
    payments = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "ticket_id", "amount", "method", "stripe_payment_id",
        "bursar_reference", "paid_at",
    ])
    for p in payments:
        writer.writerow([
            str(p.id), str(p.ticket_id), str(p.amount), p.method,
            p.stripe_payment_id or "", p.bursar_reference or "",
            p.paid_at.isoformat() if p.paid_at else "",
        ])

    output.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )
