import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.ticket import Ticket
from ..schemas.payment import (
    AvailablePermitsResponse,
    AvailablePermitType,
    BursarImportPayload,
    BursarImportResult,
    CheckoutRequest,
    CheckoutResponse,
    DisputeRequest,
    DisputeResponse,
    PaymentRead,
    PermitPurchaseRequest,
    PermitPurchaseResponse,
    RevenueReport,
    TicketLookup,
    TicketLookupList,
)
from ..websocket import manager

router = APIRouter()


# --- Public Endpoints (no auth, student-facing) ---


@router.get("/lookup", response_model=TicketLookupList)
async def lookup_by_plate(
    plate: str,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for the pay portal — search unpaid tickets by plate."""
    normalized = plate.upper().strip()
    if not normalized:
        return TicketLookupList(tickets=[])

    result = await db.execute(
        select(Ticket)
        .where(
            Ticket.plate.ilike(f"%{normalized}%"),
            Ticket.status.notin_(["paid", "voided", "resolved_permit"]),
        )
        .order_by(Ticket.issued_at.desc())
        .limit(20)
    )
    return TicketLookupList(tickets=result.scalars().all())


@router.get("/lookup/{ticket_id}", response_model=TicketLookup)
async def lookup_by_id(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for QR code deep links — fetch a single ticket for payment."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(data: CheckoutRequest, db: AsyncSession = Depends(get_db)):
    ticket = await db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided", "resolved_permit"):
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
        metadata={"ticket_id": str(ticket.id), "type": "ticket_payment"},
    )

    ticket.status = "pending_payment"
    await db.flush()

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


@router.post("/dispute/{ticket_id}", response_model=DisputeResponse)
async def dispute_ticket(
    ticket_id: uuid.UUID,
    data: DisputeRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — student disputes a ticket from the payment portal."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided", "resolved_permit"):
        raise HTTPException(400, f"Cannot dispute a {ticket.status} ticket")
    if ticket.status == "appealed" and ticket.appeal_decision == "pending":
        raise HTTPException(400, "A dispute has already been submitted for this ticket")

    ticket.status = "appealed"
    ticket.appeal_note = data.explanation
    ticket.appeal_decision = "pending"
    ticket.dispute_name = data.name
    ticket.dispute_email = data.email
    ticket.dispute_phone = data.phone
    await db.flush()

    await manager.broadcast("ticket_disputed", {
        "id": str(ticket.id),
        "plate": ticket.plate,
        "status": "appealed",
        "dispute_name": data.name,
    })

    return DisputeResponse(
        status="received",
        ticket_id=ticket.id,
        message="Your dispute has been submitted and will be reviewed within 5 business days. "
                "You will be contacted at the email or phone number provided.",
    )


@router.get("/permits/available", response_model=AvailablePermitsResponse)
async def available_permits(
    ticket_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — check which permit types are available for purchase."""
    # Get enforcement settings for fine reduction amount
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    fine_reduction = es.permit_fine_reduction if es else Decimal("0.00")

    # Get purchasable permit types (exclude lottery types — those go through /student/permits)
    result = await db.execute(
        select(PermitType).where(
            PermitType.is_active.is_(True),
            PermitType.is_purchasable_online.is_(True),
            PermitType.requires_lottery.is_(False),
        ).order_by(PermitType.sort_order)
    )
    permit_types = result.scalars().all()

    available = []
    for pt in permit_types:
        active_count_result = await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )
        active_count = active_count_result.scalar() or 0
        remaining = max(0, pt.max_capacity - active_count)

        if remaining > 0:
            available.append(AvailablePermitType(
                id=pt.id,
                code=pt.code,
                label=pt.label,
                price=pt.price,
                remaining=remaining,
                lot_assignments=pt.lot_assignments,
                valid_days=pt.valid_days,
            ))

    return AvailablePermitsResponse(
        permit_types=available,
        ticket_fine_after_purchase=fine_reduction,
    )


@router.post("/purchase-permit", response_model=PermitPurchaseResponse)
async def purchase_permit(
    data: PermitPurchaseRequest, db: AsyncSession = Depends(get_db)
):
    """Public endpoint — purchase a permit to resolve a ticket via Stripe."""
    ticket = await db.get(Ticket, data.ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided", "resolved_permit"):
        raise HTTPException(400, f"Ticket is already {ticket.status}")

    permit_type = await db.get(PermitType, data.permit_type_id)
    if not permit_type:
        raise HTTPException(404, "Permit type not found")
    if not permit_type.is_purchasable_online:
        raise HTTPException(400, "This permit type is not available for online purchase")

    # Check capacity
    active_count_result = await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.permit_type == permit_type.code,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    active_count = active_count_result.scalar() or 0
    if active_count >= permit_type.max_capacity:
        raise HTTPException(409, "No permits of this type are currently available")

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
                    "name": f"{permit_type.label} Parking Permit",
                    "description": f"Plate: {data.plate} | Valid for {permit_type.valid_days} days",
                },
                "unit_amount": int(permit_type.price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        success_url=f"{base_url}{data.success_url}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}{data.cancel_url}",
        metadata={
            "type": "permit_purchase",
            "ticket_id": str(ticket.id),
            "permit_type_id": str(permit_type.id),
            "permit_type_code": permit_type.code,
            "student_name": data.student_name,
            "plate": data.plate.upper(),
            "email": data.email,
            "valid_days": str(permit_type.valid_days),
        },
    )

    return PermitPurchaseResponse(checkout_url=session.url, session_id=session.id)


@router.get("/verify-session")
async def verify_stripe_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — verify a Stripe checkout session's payment status for the PaySuccess page."""
    if not settings.stripe_secret_key:
        return {"status": "unknown", "payment_status": "unknown"}

    import stripe
    stripe.api_key = settings.stripe_secret_key

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        payment_status = session.get("payment_status", "unknown")
        metadata = session.get("metadata", {})
        ticket_id = metadata.get("ticket_id")
        payment_type = metadata.get("type", "ticket_payment")

        ticket_plate = None
        if ticket_id:
            ticket = await db.get(Ticket, uuid.UUID(ticket_id))
            if ticket:
                ticket_plate = ticket.plate

        return {
            "status": "ok",
            "payment_status": payment_status,
            "payment_type": payment_type,
            "ticket_id": ticket_id,
            "ticket_plate": ticket_plate,
        }
    except Exception as e:
        return {"status": "error", "payment_status": "unknown", "detail": str(e)}


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
        metadata = session.get("metadata", {})
        payment_type = metadata.get("type", "ticket_payment")

        if payment_type == "ticket_payment":
            await _handle_ticket_payment(session, metadata, db)
        elif payment_type == "permit_purchase":
            await _handle_permit_purchase(session, metadata, db)
        elif payment_type == "lottery_permit":
            await _handle_lottery_permit(session, metadata, db)

    return {"status": "ok"}


async def _handle_ticket_payment(session: dict, metadata: dict, db: AsyncSession):
    ticket_id = metadata.get("ticket_id")
    if not ticket_id:
        return

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return

    payment = Payment(
        ticket_id=ticket.id,
        amount=Decimal(session["amount_total"]) / 100,
        method="online_card",
        stripe_payment_id=session["payment_intent"],
    )
    db.add(payment)
    ticket.status = "paid"
    await db.flush()


async def _handle_permit_purchase(session: dict, metadata: dict, db: AsyncSession):
    ticket_id = metadata.get("ticket_id")
    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    valid_days = int(metadata.get("valid_days", "365"))

    if not ticket_id:
        return

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return

    # Create the permit
    lot_assignment = ""
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

    new_permit = Permit(
        name=student_name,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    # Record the payment
    payment = Payment(
        ticket_id=ticket.id,
        amount=Decimal(session["amount_total"]) / 100,
        method="online_permit_purchase",
        stripe_payment_id=session["payment_intent"],
    )
    db.add(payment)

    # Reduce ticket fine and mark resolved
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    ticket.fine_amount = es.permit_fine_reduction if es else Decimal("0.00")
    ticket.status = "resolved_permit"
    await db.flush()


async def _handle_lottery_permit(session: dict, metadata: dict, db: AsyncSession):
    """Handle payment for a lottery-won permit application."""
    from ..models.permit_application import PermitApplication
    from ..models.permit_type import PermitType as PT

    app_id = metadata.get("application_id")
    if not app_id:
        return

    app = await db.get(PermitApplication, uuid.UUID(app_id))
    if not app or app.status != "selected":
        return

    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    valid_days = int(metadata.get("valid_days", "365"))
    email = metadata.get("email", "")

    lot_assignment = ""
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        pt = await db.get(PT, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

    new_permit = Permit(
        name=student_name,
        email=email,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    app.status = "accepted"
    await db.flush()


# --- Authenticated Endpoints (admin/staff) ---


@router.post("/bursar-import", response_model=BursarImportResult)
async def bursar_import(
    payload: BursarImportPayload,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
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
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
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
async def revenue_report(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
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
async def payments_for_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user),
):
    result = await db.execute(
        select(Payment).where(Payment.ticket_id == ticket_id).order_by(Payment.paid_at)
    )
    return result.scalars().all()


@router.get("/export/csv")
async def export_payments(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
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
