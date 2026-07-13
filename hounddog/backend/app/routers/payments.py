import csv
import io
import logging
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

logger = logging.getLogger("quarry.payments")

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
from ..services.permit_numbering import next_permit_number
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
    StripeOverview,
    StripeTransaction,
    StripeTransactionsResponse,
    TicketLookup,
    TicketLookupList,
)
from ..websocket import manager

router = APIRouter()

PERMIT_PAYMENT_TYPES = {"permit_purchase", "lottery_permit", "standalone_permit_purchase"}


def _build_gl_string(fund: str, org: str, account: str, activity: str) -> str:
    sep = settings.gl_segment_separator
    return sep.join([fund, org, account, activity, settings.gl_segment5, settings.gl_segment6])


def _revenue_gl(is_permit: bool) -> str:
    acct = settings.gl_account_permits if is_permit else settings.gl_account_citations
    activity = settings.gl_activity_permits if is_permit else settings.gl_activity_citations
    return _build_gl_string(settings.gl_fund, settings.gl_org, acct, activity)


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

    ticket_ref = ticket.ticket_number or str(ticket.id)[:8].upper()

    session = stripe.checkout.Session.create(
        customer_email=payer_email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"Parking Citation {ticket_ref}",
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
                "gl_string": _build_gl_string(
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_citations, settings.gl_activity_citations,
                ),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_citations,
                "gl_activity": settings.gl_activity_citations,
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
    if permit_type.requires_lottery:
        raise HTTPException(400, "Lottery permits cannot be purchased directly")

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
                "gl_string": _build_gl_string(
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_activity_permits,
                ),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_activity": settings.gl_activity_permits,
                "permit_type_code": permit_type.code,
                "permit_type_label": permit_type.label,
                "permit_price": str(permit_type.price),
                "permit_valid_days": str(permit_type.valid_days),
                "ticket_id": str(ticket.id),
                "ticket_ref": ticket.ticket_number or str(ticket.id)[:8].upper(),
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
                "gl_string": _build_gl_string(
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_activity_permits,
                ),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_activity": settings.gl_activity_permits,
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
            "plate_state": data.plate_state.upper().strip(),
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

    event_type = event["type"]
    obj = event["data"]["object"].to_dict()

    if event_type == "checkout.session.completed":
        metadata = obj.get("metadata") or {}
        payment_type = metadata.get("type", "")

        handled = False
        if payment_type == "ticket_payment":
            handled = await _handle_ticket_payment(obj, metadata, db)
        elif payment_type == "permit_purchase":
            handled = await _handle_permit_purchase(obj, metadata, db)
        elif payment_type == "lottery_permit":
            handled = await _handle_lottery_permit(obj, metadata, db)
        elif payment_type == "standalone_permit_purchase":
            handled = await _handle_standalone_permit_purchase(obj, metadata, db)

        if not handled:
            await _handle_generic_payment(obj, metadata, db)

    elif event_type in ("payment_intent.succeeded", "charge.succeeded"):
        await _handle_raw_stripe_event(obj, event_type, db)

    elif event_type == "charge.refunded":
        payment_intent_id = obj.get("payment_intent")
        if payment_intent_id:
            result = await db.execute(
                select(Payment).where(Payment.stripe_payment_id == payment_intent_id)
            )
            payment = result.scalar_one_or_none()
            if payment:
                payment.description = f"[REFUNDED] {payment.description or ''}"
                if payment.ticket_id:
                    ticket = await db.get(Ticket, payment.ticket_id)
                    if ticket and ticket.status == "paid":
                        ticket.status = "pending_payment"
                await db.flush()
                logger.info("Processed refund for payment %s", payment.id)

    elif event_type == "checkout.session.expired":
        metadata = obj.get("metadata") or {}
        ticket_id = metadata.get("ticket_id")
        if ticket_id:
            ticket = await db.get(Ticket, uuid.UUID(ticket_id))
            if ticket and ticket.status == "pending_payment":
                ticket.status = "issued"
                await db.flush()
                logger.info("Expired checkout for ticket %s, reset to issued", ticket_id)

    elif event_type == "charge.dispute.created":
        charge_id = obj.get("charge")
        logger.warning(
            "Stripe dispute created for charge %s, amount %s, reason: %s",
            charge_id,
            obj.get("amount"),
            obj.get("reason"),
        )

    return {"status": "ok"}


async def _handle_ticket_payment(session: dict, metadata: dict, db: AsyncSession) -> bool:
    ticket_id = metadata.get("ticket_id")
    if not ticket_id:
        return False

    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return True

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return False

    ticket_ref = ticket.ticket_number or str(ticket.id)[:8].upper()
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

    try:
        if ticket.plate:
            from ..services.escalation import check_and_resolve_on_payment
            await check_and_resolve_on_payment(db, ticket.plate)
    except Exception as e:
        logger.warning("Escalation resolve on payment failed (non-fatal): %s", e)

    return True


async def _handle_generic_payment(session: dict, metadata: dict, db: AsyncSession):
    """Fallback: record any Stripe checkout payment that wasn't handled by a specific handler."""
    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return

    amount_total = session.get("amount_total", 0)
    if not amount_total:
        return

    payer_email = session.get("customer_email") or session.get("customer_details", {}).get("email") or ""
    payer_name = session.get("customer_details", {}).get("name") or metadata.get("payer_name") or ""
    payment_type = metadata.get("type") or "unknown"
    plate = metadata.get("plate") or ""

    payment = Payment(
        amount=Decimal(amount_total) / 100,
        method="online_card",
        stripe_payment_id=stripe_pi or None,
        payment_type=payment_type,
        payer_name=payer_name or None,
        payer_email=payer_email or None,
        plate=plate or None,
        description=metadata.get("description") or (f"Stripe payment {stripe_pi[:12]}..." if stripe_pi else "Stripe payment"),
    )
    db.add(payment)
    await db.flush()


async def _handle_raw_stripe_event(obj: dict, event_type: str, db: AsyncSession):
    """Handle payment_intent.succeeded or charge.succeeded events directly."""
    if event_type == "payment_intent.succeeded":
        stripe_id = obj.get("id", "")
        amount = obj.get("amount", 0)
        email = obj.get("receipt_email") or ""
        metadata = obj.get("metadata") or {}
        description = obj.get("description") or ""
    else:
        stripe_id = obj.get("payment_intent") or obj.get("id", "")
        amount = obj.get("amount", 0)
        email = obj.get("receipt_email") or obj.get("billing_details", {}).get("email") or ""
        metadata = obj.get("metadata") or {}
        description = obj.get("description") or ""

    if stripe_id:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_id)
        )
        if existing.scalar():
            return

    if not amount:
        return

    payer_name = metadata.get("payer_name") or obj.get("billing_details", {}).get("name") or ""

    payment = Payment(
        amount=Decimal(amount) / 100,
        method="online_card",
        stripe_payment_id=stripe_id or None,
        payment_type=metadata.get("type") or "unknown",
        payer_name=payer_name or None,
        payer_email=email or None,
        plate=metadata.get("plate") or None,
        description=description or (f"Stripe {event_type.split('.')[0]} {stripe_id[:12]}..." if stripe_id else "Stripe payment"),
    )
    db.add(payment)
    await db.flush()


async def _handle_permit_purchase(session: dict, metadata: dict, db: AsyncSession) -> bool:
    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return True

    ticket_id = metadata.get("ticket_id")
    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    email = metadata.get("email", "")
    valid_days = int(metadata.get("valid_days", "365"))

    if not ticket_id:
        return False

    ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    if not ticket:
        return False

    lot_assignment = ""
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ",".join(pt.lot_assignments)

    new_permit = Permit(
        permit_number=await next_permit_number(db),
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
    return True


async def _handle_lottery_permit(session: dict, metadata: dict, db: AsyncSession) -> bool:
    """Handle payment for a lottery-won permit application."""
    from ..models.permit_application import PermitApplication
    from ..models.permit_type import PermitType as PT

    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return True

    app_id = metadata.get("application_id")
    if not app_id:
        return False

    app = await db.get(PermitApplication, uuid.UUID(app_id))
    if not app or app.status != "selected":
        return False

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
        permit_number=await next_permit_number(db),
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
    return True


async def _handle_standalone_permit_purchase(session: dict, metadata: dict, db: AsyncSession) -> bool:
    """Handle payment for a standalone permit purchase (no ticket context)."""
    stripe_pi = session.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return True

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
        permit_number=await next_permit_number(db),
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
    return True


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
    return await bursar_import(payload, db, user)


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


@router.post("/stripe-backfill-emails")
async def stripe_backfill_emails(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Backfill receipt_email on Stripe PaymentIntents using local data sources."""
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    updated = 0
    skipped = 0
    already_set = 0
    errors: list[str] = []
    details: list[dict] = []

    starting_after = None
    while True:
        params: dict = {"limit": 100}
        if starting_after:
            params["starting_after"] = starting_after

        try:
            page = stripe.PaymentIntent.list(**params)
        except Exception as e:
            errors.append(f"PaymentIntent.list failed: {e}")
            break

        if not page.data:
            break

        for pi in page.data:
            pi_id = pi.id
            existing_email = getattr(pi, "receipt_email", None)
            if existing_email:
                already_set += 1
                continue

            email = None
            source = None
            md = pi.metadata.to_dict() if getattr(pi, "metadata", None) else {}

            if md.get("student_email"):
                email = md["student_email"]
                source = "metadata.student_email"
            elif md.get("email"):
                email = md["email"]
                source = "metadata.email"

            if not email:
                result = await db.execute(
                    select(Payment.payer_email).where(
                        Payment.stripe_payment_id == pi_id,
                        Payment.payer_email.isnot(None),
                        Payment.payer_email != "",
                    )
                )
                db_email = result.scalar()
                if db_email:
                    email = db_email
                    source = "payments.payer_email"

            if not email and md.get("ticket_id"):
                try:
                    ticket = await db.get(Ticket, uuid.UUID(md["ticket_id"]))
                    if ticket:
                        if ticket.permit_id:
                            permit_result = await db.execute(
                                select(Permit.email).where(
                                    Permit.id == ticket.permit_id,
                                    Permit.email.isnot(None),
                                    Permit.email != "",
                                )
                            )
                            permit_email = permit_result.scalar()
                            if permit_email:
                                email = permit_email
                                source = "permit.email"
                        if not email and ticket.dispute_email:
                            email = ticket.dispute_email
                            source = "ticket.dispute_email"
                except Exception:
                    pass

            if not email:
                skipped += 1
                continue

            try:
                stripe.PaymentIntent.modify(pi_id, receipt_email=email)
                updated += 1
                details.append({"id": pi_id, "email": email, "source": source})
            except Exception as e:
                errors.append(f"{pi_id}: {e}")

        if not page.has_more:
            break
        starting_after = page.data[-1].id

    return {
        "updated": updated,
        "already_set": already_set,
        "skipped_no_email": skipped,
        "errors": errors,
        "details": details,
    }


@router.post("/stripe-backfill-payments")
async def stripe_backfill_payments(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Backfill the payments table from Stripe PaymentIntents.

    Iterates all succeeded PaymentIntents and creates a local Payment
    record for any that don't already exist.
    """
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    created = 0
    skipped = 0
    errors: list[str] = []

    starting_after = None
    while True:
        params: dict = {"limit": 100, "expand": ["data.latest_charge"]}
        if starting_after:
            params["starting_after"] = starting_after

        try:
            page = stripe.PaymentIntent.list(**params)
        except Exception as e:
            errors.append(f"PaymentIntent.list failed: {e}")
            break

        if not page.data:
            break

        for pi in page.data:
            if pi.status != "succeeded":
                continue

            existing = await db.execute(
                select(Payment).where(Payment.stripe_payment_id == pi.id)
            )
            if existing.scalar():
                skipped += 1
                continue

            md = pi.metadata.to_dict() if getattr(pi, "metadata", None) else {}
            ptype = md.get("type", "unknown")
            amount_cents = pi.amount or 0
            email = pi.receipt_email or md.get("student_email") or md.get("email") or ""
            payer_name = md.get("payer_name") or md.get("student_name") or ""
            plate = md.get("plate") or ""
            description = pi.description or md.get("description") or ""

            is_permit = ptype in PERMIT_PAYMENT_TYPES
            method = "online_permit_purchase" if is_permit else "online_card"

            ticket_id = None
            if md.get("ticket_id"):
                try:
                    ticket_id = uuid.UUID(md["ticket_id"])
                except ValueError:
                    pass

            if not description:
                if is_permit:
                    label = md.get("permit_type_label", "permit")
                    description = f"Parking permit — {label}"
                elif ticket_id:
                    ref = md.get("ticket_ref", str(ticket_id)[:8].upper())
                    description = f"Citation #{ref} — {plate}"
                else:
                    description = f"Stripe payment {pi.id[:16]}"

            paid_at = None
            if hasattr(pi, "created") and pi.created:
                paid_at = datetime.fromtimestamp(pi.created, tz=timezone.utc)

            payment = Payment(
                ticket_id=ticket_id,
                amount=Decimal(amount_cents) / 100,
                method=method,
                stripe_payment_id=pi.id,
                payment_type=ptype,
                payer_name=payer_name or None,
                payer_email=email or None,
                plate=plate or None,
                description=description or None,
            )
            if paid_at:
                payment.paid_at = paid_at

            db.add(payment)
            created += 1

            if ticket_id and ptype == "ticket_payment":
                ticket = await db.get(Ticket, ticket_id)
                if ticket and ticket.status != "paid":
                    ticket.status = "paid"

        if not page.has_more:
            break
        starting_after = page.data[-1].id

    await db.commit()

    return {
        "created": created,
        "skipped_existing": skipped,
        "errors": errors,
    }


@router.get("/stripe-debug")
async def stripe_debug(user: OktaUser = Depends(require_admin())):
    """Diagnostic: show what Stripe sees with the configured key."""
    if not settings.stripe_secret_key:
        return {"error": "QUARRY_STRIPE_SECRET_KEY is empty", "key_prefix": ""}

    import stripe
    stripe.api_key = settings.stripe_secret_key

    result: dict = {
        "key_prefix": settings.stripe_secret_key[:12] + "...",
        "key_mode": "live" if settings.stripe_secret_key.startswith("sk_live") else "test" if settings.stripe_secret_key.startswith("sk_test") else "unknown",
    }

    try:
        acct = stripe.Account.retrieve()
        result["account_id"] = acct.id
        result["account_name"] = getattr(acct, "business_profile", {}).get("name") if getattr(acct, "business_profile", None) else None
        result["account_email"] = getattr(acct, "email", None)
    except Exception as e:
        result["account_error"] = str(e)

    for label, fn in [
        ("charges", lambda: stripe.Charge.list(limit=3)),
        ("payment_intents", lambda: stripe.PaymentIntent.list(limit=3)),
        ("checkout_sessions", lambda: stripe.checkout.Session.list(limit=3)),
        ("customers", lambda: stripe.Customer.list(limit=1)),
    ]:
        try:
            data = fn()
            items = list(data.data)
            result[label] = {
                "count": len(items),
                "has_more": data.has_more,
                "sample_ids": [item.id for item in items],
            }
        except Exception as e:
            result[label] = {"error": str(e)}

    return result


def _charge_to_txn(ch) -> StripeTransaction:
    """Convert a Stripe Charge object to our StripeTransaction schema."""
    fee = Decimal("0")
    net = Decimal("0")
    bt = getattr(ch, "balance_transaction", None)
    if bt and hasattr(bt, "fee"):
        fee = Decimal(str(bt.fee)) / 100
        net = Decimal(str(bt.net)) / 100

    amount = Decimal(str(ch.amount)) / 100
    refunded = Decimal(str(getattr(ch, "amount_refunded", 0))) / 100

    pm_type = None
    pm_last4 = None
    pm_brand = None
    pmd = getattr(ch, "payment_method_details", None)
    if pmd:
        pm_type = getattr(pmd, "type", None)
        card = getattr(pmd, "card", None)
        if card:
            pm_last4 = getattr(card, "last4", None)
            pm_brand = getattr(card, "brand", None)

    billing = getattr(ch, "billing_details", None)
    email = getattr(ch, "receipt_email", None) or (getattr(billing, "email", None) if billing else None)
    name = getattr(billing, "name", None) if billing else None

    return StripeTransaction(
        id=ch.id,
        source="charge",
        amount=amount,
        amount_refunded=refunded,
        net=net,
        fee=fee,
        currency=getattr(ch, "currency", "usd"),
        status=getattr(ch, "status", "unknown"),
        description=getattr(ch, "description", None),
        customer_email=email,
        customer_name=name,
        receipt_url=getattr(ch, "receipt_url", None),
        payment_method_type=pm_type,
        payment_method_last4=pm_last4,
        payment_method_brand=pm_brand,
        metadata=ch.metadata.to_dict() if getattr(ch, "metadata", None) else {},
        created=datetime.fromtimestamp(ch.created, tz=timezone.utc),
        livemode=getattr(ch, "livemode", False),
    )


def _pi_to_txn(pi) -> StripeTransaction:
    """Convert a Stripe PaymentIntent to our StripeTransaction schema."""
    amount = Decimal(str(pi.amount)) / 100
    refunded = Decimal("0")

    pm_type = None
    pm_last4 = None
    pm_brand = None

    charges = getattr(pi, "charges", None)
    latest_charge = getattr(pi, "latest_charge", None)
    receipt_url = None
    fee = Decimal("0")
    net = Decimal("0")

    if charges and charges.data:
        ch = charges.data[0]
        refunded = Decimal(str(getattr(ch, "amount_refunded", 0))) / 100
        receipt_url = getattr(ch, "receipt_url", None)
        pmd = getattr(ch, "payment_method_details", None)
        if pmd:
            pm_type = getattr(pmd, "type", None)
            card = getattr(pmd, "card", None)
            if card:
                pm_last4 = getattr(card, "last4", None)
                pm_brand = getattr(card, "brand", None)
        bt = getattr(ch, "balance_transaction", None)
        if bt and hasattr(bt, "fee"):
            fee = Decimal(str(bt.fee)) / 100
            net = Decimal(str(bt.net)) / 100

    status_map = {
        "succeeded": "succeeded", "requires_payment_method": "failed",
        "canceled": "canceled", "processing": "pending",
        "requires_action": "pending", "requires_confirmation": "pending",
        "requires_capture": "pending",
    }

    customer_email = None
    customer_name = None
    if getattr(pi, "receipt_email", None):
        customer_email = pi.receipt_email
    elif charges and charges.data:
        billing = getattr(charges.data[0], "billing_details", None)
        if billing:
            customer_email = getattr(billing, "email", None)
            customer_name = getattr(billing, "name", None)

    return StripeTransaction(
        id=pi.id,
        source="payment_intent",
        amount=amount,
        amount_refunded=refunded,
        net=net,
        fee=fee,
        currency=getattr(pi, "currency", "usd"),
        status=status_map.get(getattr(pi, "status", ""), getattr(pi, "status", "unknown")),
        description=getattr(pi, "description", None),
        customer_email=customer_email,
        customer_name=customer_name,
        receipt_url=receipt_url,
        payment_method_type=pm_type,
        payment_method_last4=pm_last4,
        payment_method_brand=pm_brand,
        metadata=pi.metadata.to_dict() if getattr(pi, "metadata", None) else {},
        created=datetime.fromtimestamp(pi.created, tz=timezone.utc),
        livemode=getattr(pi, "livemode", False),
    )


def _session_to_txn(sess) -> StripeTransaction:
    """Convert a Stripe Checkout Session to our StripeTransaction schema."""
    amount = Decimal(str(getattr(sess, "amount_total", 0) or 0)) / 100
    status_map = {"complete": "succeeded", "open": "pending", "expired": "canceled"}
    customer_details = getattr(sess, "customer_details", None)

    return StripeTransaction(
        id=sess.id,
        source="checkout_session",
        amount=amount,
        amount_refunded=Decimal("0"),
        net=Decimal("0"),
        fee=Decimal("0"),
        currency=getattr(sess, "currency", "usd") or "usd",
        status=status_map.get(getattr(sess, "status", ""), getattr(sess, "status", "unknown")),
        description=f"Checkout Session",
        customer_email=getattr(sess, "customer_email", None) or (getattr(customer_details, "email", None) if customer_details else None),
        customer_name=getattr(customer_details, "name", None) if customer_details else None,
        receipt_url=None,
        payment_method_type=None,
        payment_method_last4=None,
        payment_method_brand=None,
        metadata=sess.metadata.to_dict() if getattr(sess, "metadata", None) else {},
        created=datetime.fromtimestamp(sess.created, tz=timezone.utc),
        livemode=getattr(sess, "livemode", False),
    )


@router.get("/stripe-transactions")
async def stripe_transactions(
    limit: int = Query(50, ge=1, le=100),
    user: OktaUser = Depends(require_admin()),
):
    """Pull transactions from all Stripe APIs — Charges, PaymentIntents, and Checkout Sessions."""
    import traceback

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured — QUARRY_STRIPE_SECRET_KEY is empty")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    seen_ids: set[str] = set()
    transactions: list[dict] = []
    overview = {
        "total_volume": Decimal("0"), "total_fees": Decimal("0"),
        "total_net": Decimal("0"), "total_refunded": Decimal("0"),
        "successful_count": 0, "refunded_count": 0, "failed_count": 0,
    }
    has_more = False
    errors: list[str] = []

    def add_txn(txn: StripeTransaction):
        if txn.id in seen_ids:
            return
        seen_ids.add(txn.id)
        d = txn.model_dump()
        d["created"] = d["created"].isoformat()
        d["amount"] = str(d["amount"])
        d["amount_refunded"] = str(d["amount_refunded"])
        d["net"] = str(d["net"])
        d["fee"] = str(d["fee"])
        transactions.append(d)
        if txn.status == "succeeded":
            overview["successful_count"] += 1
            overview["total_volume"] += txn.amount
            overview["total_fees"] += txn.fee
            overview["total_net"] += txn.net
        if txn.amount_refunded > 0:
            overview["refunded_count"] += 1
            overview["total_refunded"] += txn.amount_refunded
        if txn.status == "failed":
            overview["failed_count"] += 1

    # --- Charges ---
    try:
        charges = stripe.Charge.list(limit=limit)
        has_more = has_more or charges.has_more
        for i, ch in enumerate(charges.data):
            try:
                add_txn(_charge_to_txn(ch))
            except Exception as e:
                errors.append(f"charge[{i}] {ch.id}: {e}\n{traceback.format_exc()}")
    except Exception as e:
        errors.append(f"Charge.list failed: {e}\n{traceback.format_exc()}")

    # --- PaymentIntents ---
    try:
        pis = stripe.PaymentIntent.list(limit=limit)
        has_more = has_more or pis.has_more
        for i, pi in enumerate(pis.data):
            try:
                add_txn(_pi_to_txn(pi))
            except Exception as e:
                errors.append(f"pi[{i}] {pi.id}: {e}\n{traceback.format_exc()}")
    except Exception as e:
        errors.append(f"PaymentIntent.list failed: {e}\n{traceback.format_exc()}")

    # --- Checkout Sessions ---
    try:
        sessions = stripe.checkout.Session.list(limit=limit)
        has_more = has_more or sessions.has_more
        for i, sess in enumerate(sessions.data):
            try:
                add_txn(_session_to_txn(sess))
            except Exception as e:
                errors.append(f"session[{i}] {sess.id}: {e}\n{traceback.format_exc()}")
    except Exception as e:
        errors.append(f"Session.list failed: {e}\n{traceback.format_exc()}")

    transactions.sort(key=lambda t: t["created"], reverse=True)

    return {
        "overview": {
            "total_volume": str(overview["total_volume"]),
            "total_fees": str(overview["total_fees"]),
            "total_net": str(overview["total_net"]),
            "total_refunded": str(overview["total_refunded"]),
            "successful_count": overview["successful_count"],
            "refunded_count": overview["refunded_count"],
            "failed_count": overview["failed_count"],
        },
        "transactions": transactions,
        "has_more": has_more,
        "errors": errors,
    }


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
        "id", "ticket_id", "amount", "method", "payment_type",
        "stripe_payment_id", "bursar_reference",
        "payer_name", "payer_email", "plate",
        "description", "gl_revenue_account",
        "paid_at", "created_at",
    ])
    for p in payments:
        ptype = p.payment_type or ""
        is_permit = ptype in PERMIT_PAYMENT_TYPES

        writer.writerow([
            str(p.id),
            str(p.ticket_id) if p.ticket_id else "",
            str(p.amount),
            p.method or "",
            ptype,
            p.stripe_payment_id or "",
            p.bursar_reference or "",
            p.payer_name or "",
            p.payer_email or "",
            p.plate or "",
            p.description or "",
            _revenue_gl(is_permit),
            p.paid_at.isoformat() if p.paid_at else "",
            p.created_at.isoformat() if p.created_at else "",
        ])

    output.seek(0)
    from fastapi.responses import StreamingResponse
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


def _fetch_stripe_fee(payment_intent_id: str) -> tuple[int, int]:
    """Return (fee_cents, net_cents) from Stripe balance_transaction."""
    import stripe
    stripe.api_key = settings.stripe_secret_key
    try:
        pi = stripe.PaymentIntent.retrieve(
            payment_intent_id,
            expand=["latest_charge.balance_transaction"],
        )
        bt = pi.latest_charge.balance_transaction
        return bt.fee, bt.net
    except Exception:
        return 0, 0


@router.get("/export/oracle-gl")
async def export_oracle_gl(
    since: date | None = None,
    until: date | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Export payments as Oracle Cloud Financials FBDI journal import format.

    Produces a balanced 3-line entry per Stripe payment:
      1. Debit: Net cash (gross minus Stripe fee)
      2. Debit: Stripe processing fee
      3. Credit: Revenue (full gross amount)

    Non-Stripe payments (bursar) produce a 2-line entry with no fee line.
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

    net_cash_string = _build_gl_string(
        settings.gl_fund, settings.gl_org_net_cash,
        settings.gl_account_net_cash, settings.gl_activity_zero,
    )
    stripe_fee_string = _build_gl_string(
        settings.gl_fund, settings.gl_org,
        settings.gl_account_stripe_fees, settings.gl_activity_zero,
    )

    batch_date = date.today().isoformat()
    batch_name = f"QUARRY-{batch_date}"

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "LedgerName", "AccountingDate", "UserJeSource", "UserJeCategory",
        "CurrencyCode", "JeBatchName", "JeHeaderName", "JeLineName",
        "Segment1", "Segment2", "Segment3", "Segment4", "Segment5", "Segment6",
        "AccountCombination", "EnteredDrAmount", "EnteredCrAmount",
        "LineDescription", "Reference1", "Reference2", "Reference3",
        "Reference4", "Reference5",
    ])

    def _write_row(
        acct_date: str, header_name: str, line_name: str,
        fund: str, org: str, account: str, activity: str,
        combo: str, dr: str, cr: str,
        desc: str, ref_id: str, ticket_ref: str,
        line_method: str, payment_id: str, ticket_id_str: str,
    ):
        writer.writerow([
            settings.gl_ledger, acct_date, settings.gl_source,
            settings.gl_category_revenue, "USD", batch_name, header_name,
            line_name,
            fund, org, account, activity, settings.gl_segment5, settings.gl_segment6,
            combo, dr, cr,
            desc,
            ref_id, ticket_ref, line_method,
            payment_id, ticket_id_str,
        ])

    for p in payments:
        acct_date = p.paid_at.strftime("%Y-%m-%d") if p.paid_at else batch_date
        ptype = p.payment_type or ""
        is_permit = ptype in PERMIT_PAYMENT_TYPES
        category = "Permit Revenue" if is_permit else "Citation Revenue"

        ticket_ref = str(p.ticket_id)[:8].upper() if p.ticket_id else ""
        ref_id = p.stripe_payment_id or p.bursar_reference or str(p.id)[:8]
        header_name = f"{settings.gl_source}-{acct_date}"
        description = p.description or f"Parking {category}"
        line_method = ptype or p.method or ""
        pid_str = str(p.id)
        tid_str = str(p.ticket_id) if p.ticket_id else ""

        revenue_acct = settings.gl_account_permits if is_permit else settings.gl_account_citations
        revenue_activity = settings.gl_activity_permits if is_permit else settings.gl_activity_citations
        revenue_string = _revenue_gl(is_permit)

        gross = p.amount
        fee_cents = 0
        net_cents = 0

        if p.stripe_payment_id:
            fee_cents, net_cents = _fetch_stripe_fee(p.stripe_payment_id)

        if fee_cents > 0:
            net_amount = Decimal(net_cents) / 100
            fee_amount = Decimal(fee_cents) / 100
        else:
            net_amount = gross
            fee_amount = Decimal(0)

        # Line 1: Debit — Net cash
        _write_row(
            acct_date, header_name, f"DR-CASH-{ref_id[:8]}",
            settings.gl_fund, settings.gl_org_net_cash,
            settings.gl_account_net_cash, settings.gl_activity_zero,
            net_cash_string, f"{net_amount:.2f}", "",
            description, ref_id, ticket_ref, line_method, pid_str, tid_str,
        )

        # Line 2: Debit — Stripe processing fee (only for Stripe payments)
        if fee_amount > 0:
            _write_row(
                acct_date, header_name, f"DR-FEE-{ref_id[:8]}",
                settings.gl_fund, settings.gl_org,
                settings.gl_account_stripe_fees, settings.gl_activity_zero,
                stripe_fee_string, f"{fee_amount:.2f}", "",
                f"Stripe fee - {description}", ref_id, ticket_ref,
                line_method, pid_str, tid_str,
            )

        # Line 3: Credit — Revenue (full gross amount)
        _write_row(
            acct_date, header_name, f"CR-REV-{ref_id[:8]}",
            settings.gl_fund, settings.gl_org,
            revenue_acct, revenue_activity,
            revenue_string, "", f"{gross:.2f}",
            description, ref_id, ticket_ref, line_method, pid_str, tid_str,
        )

    output.seek(0)
    filename = f"quarry_gl_journal_{batch_date}.csv"
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
