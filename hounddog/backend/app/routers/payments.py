import csv
import io
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from sqlalchemy import case, select, func
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
    PaymentListItem,
    PaymentListResponse,
    PaymentRead,
    PermitPurchaseRequest,
    PermitPurchaseResponse,
    RevenueReport,
    RevenueTimeSeries,
    RevenueTimeSeriesPoint,
    StandalonePermitPurchaseRequest,
    StandalonePermitPurchaseResponse,
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

    payer_email = None
    if ticket.permit_id:
        permit_result = await db.execute(
            select(Permit).where(Permit.id == ticket.permit_id)
        )
        linked_permit = permit_result.scalar()
        if linked_permit and linked_permit.email:
            payer_email = linked_permit.email

    ticket_ref = str(ticket.id)[:8].upper()

    session = stripe.checkout.Session.create(
        customer_email=payer_email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Parking Citation #{ticket_ref}",
                    "description": f"Plate: {ticket.plate} | Violation: {ticket.violation_type}",
                },
                "unit_amount": int(ticket.fine_amount * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": f"CITE {ticket_ref}"[:22],
            "metadata": {
                "type": "ticket_payment",
                "revenue_category": "parking_citations",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_citations, settings.gl_program,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_citations,
                "gl_program": settings.gl_program,
                "ticket_id": str(ticket.id),
                "ticket_ref": ticket_ref,
                "violation_code": ticket.violation_type,
                "violation_category": ticket.ticket_category,
                "offense_number": str(ticket.offense_number),
                "fine_amount": str(ticket.fine_amount),
                "plate": ticket.plate,
                "lot": ticket.lot or "",
                "zone": ticket.zone or "",
                "issued_at": ticket.issued_at.isoformat() if ticket.issued_at else "",
                "officer_id": ticket.officer_id or "",
                "payer_name": ticket.owner_name or ticket.driver_name or "",
                "institution": settings.school_name or "moravian",
            },
        },
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
        customer_email=data.email,
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
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "permit_purchase",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_program,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_program": settings.gl_program,
                "permit_type_code": permit_type.code,
                "permit_type_label": permit_type.label,
                "permit_price": str(permit_type.price),
                "permit_valid_days": str(permit_type.valid_days),
                "ticket_id": str(ticket.id),
                "ticket_ref": str(ticket.id)[:8].upper(),
                "plate": data.plate.upper(),
                "student_name": data.student_name,
                "student_email": data.email,
                "lot_assignments": ",".join(permit_type.lot_assignments) if permit_type.lot_assignments else "",
                "institution": settings.school_name or "moravian",
            },
        },
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


@router.post("/standalone-purchase", response_model=StandalonePermitPurchaseResponse)
async def standalone_permit_purchase(
    data: StandalonePermitPurchaseRequest, db: AsyncSession = Depends(get_db)
):
    """Public endpoint — purchase a permit directly (no ticket context). Used by /permits/buy."""
    permit_type = await db.get(PermitType, data.permit_type_id)
    if not permit_type:
        raise HTTPException(404, "Permit type not found")
    if not permit_type.is_purchasable_online:
        raise HTTPException(400, "This permit type is not available for online purchase")
    if permit_type.requires_lottery:
        raise HTTPException(400, "This permit type requires a lottery application")

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
        customer_email=data.email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{permit_type.label} Parking Permit",
                    "description": f"Plate: {data.plate.upper()} | Valid for {permit_type.valid_days} days",
                },
                "unit_amount": int(permit_type.price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "standalone_permit_purchase",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_program,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_program": settings.gl_program,
                "permit_type_code": permit_type.code,
                "permit_type_label": permit_type.label,
                "permit_price": str(permit_type.price),
                "permit_valid_days": str(permit_type.valid_days),
                "plate": data.plate.upper().strip(),
                "student_name": data.student_name,
                "student_email": data.email,
                "student_phone": data.phone or "",
                "class_year": str(data.class_year) if data.class_year else "",
                "lot_assignments": ",".join(permit_type.lot_assignments) if permit_type.lot_assignments else "",
                "institution": settings.school_name or "moravian",
            },
        },
        success_url=f"{base_url}{data.success_url}?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}{data.cancel_url}",
        metadata={
            "type": "standalone_permit_purchase",
            "permit_type_id": str(permit_type.id),
            "permit_type_code": permit_type.code,
            "student_name": data.student_name,
            "plate": data.plate.upper().strip(),
            "email": data.email,
            "phone": data.phone or "",
            "class_year": str(data.class_year) if data.class_year else "",
            "valid_days": str(permit_type.valid_days),
        },
    )

    return StandalonePermitPurchaseResponse(checkout_url=session.url, session_id=session.id)


@router.get("/verify-session")
async def verify_stripe_session(session_id: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — verify a Stripe checkout session's payment status for the PaySuccess page."""
    if not settings.stripe_secret_key:
        return {"status": "unknown", "payment_status": "unknown"}

    import stripe
    stripe.api_key = settings.stripe_secret_key

    try:
        session = stripe.checkout.Session.retrieve(session_id)
        data = session.to_dict()
        payment_status = data.get("payment_status", "unknown")
        metadata = data.get("metadata") or {}
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
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(400, "Invalid webhook signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"].to_dict()
        metadata = session.get("metadata") or {}
        payment_type = metadata.get("type", "ticket_payment")

        if payment_type == "ticket_payment":
            await _handle_ticket_payment(session, metadata, db)
        elif payment_type == "permit_purchase":
            await _handle_permit_purchase(session, metadata, db)
        elif payment_type == "lottery_permit":
            await _handle_lottery_permit(session, metadata, db)
        elif payment_type == "standalone_permit_purchase":
            await _handle_standalone_permit_purchase(session, metadata, db)

    return {"status": "ok"}


async def _handle_ticket_payment(session: dict, metadata: dict, db: AsyncSession):
    ticket_id = metadata.get("ticket_id")
    if not ticket_id:
        return

    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return

    ticket_ref = str(ticket.id)[:8].upper()
    payer_name = metadata.get("payer_name", "") or ticket.owner_name or ticket.driver_name or ""
    payer_email = session.get("customer_email", "") or ""

    payment = Payment(
        ticket_id=ticket.id,
        amount=Decimal(session["amount_total"]) / 100,
        method="online_card",
        stripe_payment_id=stripe_pi,
        payment_type="ticket_payment",
        payer_name=payer_name or None,
        payer_email=payer_email or None,
        plate=ticket.plate,
        description=f"Citation #{ticket_ref} — {ticket.plate}",
    )
    db.add(payment)
    ticket.status = "paid"
    await db.flush()


async def _handle_permit_purchase(session: dict, metadata: dict, db: AsyncSession):
    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return

    ticket_id = metadata.get("ticket_id")
    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    email = metadata.get("email", "")
    valid_days = int(metadata.get("valid_days", "365"))

    if not ticket_id:
        return

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return

    lot_assignment = ""
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

    new_permit = Permit(
        name=student_name,
        email=email or None,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    payment = Payment(
        ticket_id=ticket.id,
        amount=Decimal(session["amount_total"]) / 100,
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi,
        payment_type="permit_purchase",
        payer_name=student_name or None,
        payer_email=email or None,
        plate=plate or None,
        description=f"Permit ({permit_type_code}) — {plate}" if plate else f"Permit ({permit_type_code})",
    )
    db.add(payment)

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

    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return

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
        email=email or None,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    payment = Payment(
        amount=Decimal(session["amount_total"]) / 100,
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi,
        payment_type="lottery_permit",
        payer_name=student_name or None,
        payer_email=email or None,
        plate=plate or None,
        description=f"Lottery Permit ({permit_type_code}) — {plate}" if plate else f"Lottery Permit ({permit_type_code})",
    )
    db.add(payment)

    app.status = "accepted"
    await db.flush()


async def _handle_standalone_permit_purchase(session: dict, metadata: dict, db: AsyncSession):
    """Handle payment for a standalone permit purchase (no ticket context)."""
    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return

    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    email = metadata.get("email", "")
    phone = metadata.get("phone", "") or None
    valid_days = int(metadata.get("valid_days", "365"))

    lot_assignment = ""
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

    new_permit = Permit(
        name=student_name,
        email=email or None,
        phone=phone,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    payment = Payment(
        amount=Decimal(session["amount_total"]) / 100,
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi,
        payment_type="standalone_permit_purchase",
        payer_name=student_name or None,
        payer_email=email or None,
        plate=plate or None,
        description=f"Standalone Permit ({permit_type_code}) — {plate}" if plate else f"Standalone Permit ({permit_type_code})",
    )
    db.add(payment)
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

    ptype_result = await db.execute(
        select(Payment.payment_type, func.sum(Payment.amount)).group_by(Payment.payment_type)
    )
    by_payment_type = {(row[0] or "unknown"): row[1] for row in ptype_result.all()}

    return RevenueReport(
        total_fines_issued=total_fines,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        collection_rate=rate,
        by_method=by_method,
        by_status=by_status,
        by_payment_type=by_payment_type,
    )


@router.get("/list", response_model=PaymentListResponse)
async def list_payments(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    payment_type: str | None = None,
    method: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Paginated list of payments with optional filters."""
    query = select(Payment)

    if payment_type:
        query = query.where(Payment.payment_type == payment_type)
    if method:
        query = query.where(Payment.method == method)
    if date_from:
        query = query.where(func.date(Payment.paid_at) >= date_from)
    if date_to:
        query = query.where(func.date(Payment.paid_at) <= date_to)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0
    pages = max(1, math.ceil(total / page_size))

    rows = await db.execute(
        query.order_by(Payment.paid_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = [PaymentListItem.model_validate(p) for p in rows.scalars().all()]

    return PaymentListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        pages=pages,
    )


@router.get("/revenue/timeseries", response_model=RevenueTimeSeries)
async def revenue_timeseries(
    period: str = Query("daily", pattern="^(daily|weekly|monthly)$"),
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Revenue time series grouped by citations vs permits."""
    query = select(Payment)
    if date_from:
        query = query.where(func.date(Payment.paid_at) >= date_from)
    if date_to:
        query = query.where(func.date(Payment.paid_at) <= date_to)

    if period == "monthly":
        date_trunc = func.date_trunc("month", Payment.paid_at)
    elif period == "weekly":
        date_trunc = func.date_trunc("week", Payment.paid_at)
    else:
        date_trunc = func.date_trunc("day", Payment.paid_at)

    is_citation = Payment.payment_type.in_(["ticket_payment", None])

    ts_query = (
        select(
            date_trunc.label("bucket"),
            func.sum(case((is_citation, Payment.amount), else_=Decimal("0"))).label("citations"),
            func.sum(case((~is_citation, Payment.amount), else_=Decimal("0"))).label("permits"),
            func.sum(Payment.amount).label("total"),
        )
        .group_by("bucket")
        .order_by("bucket")
    )

    if date_from:
        ts_query = ts_query.where(func.date(Payment.paid_at) >= date_from)
    if date_to:
        ts_query = ts_query.where(func.date(Payment.paid_at) <= date_to)

    result = await db.execute(ts_query)
    data = []
    for row in result.all():
        bucket_dt = row.bucket
        if period == "monthly":
            label = bucket_dt.strftime("%Y-%m")
        elif period == "weekly":
            label = bucket_dt.strftime("%Y-W%V")
        else:
            label = bucket_dt.strftime("%Y-%m-%d")
        data.append(RevenueTimeSeriesPoint(
            date=label,
            citations_amount=row.citations or Decimal("0"),
            permits_amount=row.permits or Decimal("0"),
            total=row.total or Decimal("0"),
        ))

    return RevenueTimeSeries(period=period, data=data)


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
        "bursar_reference", "payment_type", "payer_name", "payer_email",
        "description", "plate", "paid_at",
    ])
    for p in payments:
        writer.writerow([
            str(p.id), str(p.ticket_id), str(p.amount), p.method,
            p.stripe_payment_id or "", p.bursar_reference or "",
            p.payment_type or "", p.payer_name or "", p.payer_email or "",
            p.description or "", p.plate or "",
            p.paid_at.isoformat() if p.paid_at else "",
        ])

    output.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


@router.get("/export/oracle-gl")
async def export_oracle_gl(
    since: date | None = None,
    until: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Export payments as Oracle Cloud Financials FBDI journal import format.

    Produces a two-line entry per payment:
      - Debit line: Cash account (bank/merchant deposit)
      - Credit line: Revenue account (citations or permits)
    """
    from fastapi.responses import StreamingResponse

    query = select(Payment).where(Payment.amount > 0)
    if since:
        query = query.where(Payment.paid_at >= datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc))
    if until:
        query = query.where(Payment.paid_at < datetime.combine(until + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))
    query = query.order_by(Payment.paid_at)

    result = await db.execute(query)
    payments = result.scalars().all()

    sep = settings.gl_segment_separator
    cash_string = sep.join([settings.gl_fund, settings.gl_org, settings.gl_cash_account, settings.gl_program])
    citation_string = sep.join([settings.gl_fund, settings.gl_org, settings.gl_account_citations, settings.gl_program])
    permit_string = sep.join([settings.gl_fund, settings.gl_org, settings.gl_account_permits, settings.gl_program])

    batch_date = date.today().isoformat()
    batch_name = f"QUARRY-{batch_date}"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "LedgerName", "AccountingDate", "UserJeSource", "UserJeCategory",
        "CurrencyCode", "JeBatchName", "JeHeaderName", "JeLineName",
        "Segment1", "Segment2", "Segment3", "Segment4",
        "AccountCombination", "EnteredDrAmount", "EnteredCrAmount",
        "LineDescription", "Reference1", "Reference2", "Reference3",
        "Reference4", "Reference5",
    ])

    for p in payments:
        acct_date = p.paid_at.strftime("%Y-%m-%d") if p.paid_at else batch_date

        is_permit = p.method in ("online_permit_purchase",)
        revenue_string = permit_string if is_permit else citation_string
        revenue_account = settings.gl_account_permits if is_permit else settings.gl_account_citations
        category = "Permit Revenue" if is_permit else "Citation Revenue"

        ticket_ref = str(p.ticket_id)[:8].upper() if p.ticket_id else ""
        ref_id = p.stripe_payment_id or p.bursar_reference or str(p.id)[:8]

        header_name = f"{settings.gl_source}-{acct_date}"
        amount_str = f"{p.amount:.2f}"

        # Debit: Cash/Bank
        writer.writerow([
            settings.gl_ledger, acct_date, settings.gl_source,
            settings.gl_category_revenue, "USD", batch_name, header_name,
            f"DR-{ref_id[:12]}",
            settings.gl_fund, settings.gl_org, settings.gl_cash_account, settings.gl_program,
            cash_string, amount_str, "",
            f"Parking {category} - {p.method}",
            ref_id, ticket_ref, p.method,
            str(p.id), str(p.ticket_id) if p.ticket_id else "",
        ])

        # Credit: Revenue
        writer.writerow([
            settings.gl_ledger, acct_date, settings.gl_source,
            settings.gl_category_revenue, "USD", batch_name, header_name,
            f"CR-{ref_id[:12]}",
            settings.gl_fund, settings.gl_org, revenue_account, settings.gl_program,
            revenue_string, "", amount_str,
            f"Parking {category} - {p.method}",
            ref_id, ticket_ref, p.method,
            str(p.id), str(p.ticket_id) if p.ticket_id else "",
        ])

    output.seek(0)
    filename = f"quarry_gl_journal_{batch_date}.csv"
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
