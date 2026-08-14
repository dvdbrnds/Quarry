import csv
import io
import logging
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from ..services.timeutils import today_local

logger = logging.getLogger("quarry.payments")

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import case, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.lot import ParkingLot
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.ticket import Ticket
from ..services.permit_numbering import next_permit_number
from ..schemas.payment import (
    AvailablePermitsResponse,
    AvailablePermitType,
    BulkRefundPreviewResponse,
    BulkRefundPreviewRow,
    BulkRefundRequest,
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

router = APIRouter()

PERMIT_PAYMENT_TYPES = {
    "permit_purchase",
    "lottery_permit",
    "lottery_v2_permit",
    "standalone_permit_purchase",
}


def _build_gl_string(fund: str, org: str, account: str, activity: str) -> str:
    sep = settings.gl_segment_separator
    return sep.join([fund, org, account, activity, settings.gl_segment5, settings.gl_segment6])


def _revenue_gl(is_permit: bool) -> str:
    acct = settings.gl_account_permits if is_permit else settings.gl_account_citations
    activity = settings.gl_activity_permits if is_permit else settings.gl_activity_citations
    return _build_gl_string(settings.gl_fund, settings.gl_org, acct, activity)


# --- Public Endpoints (no auth, student-facing) ---


async def _check_commuter_lot(lot_name: str, db: AsyncSession) -> bool:
    """Return True if the lot name corresponds to a commuter lot or street."""
    if not lot_name:
        return False
    lot_result = await db.execute(
        select(ParkingLot).where(func.lower(ParkingLot.name) == lot_name.lower())
    )
    lot = lot_result.scalar()
    if not lot:
        return False
    return lot.designation_code in COMMUTER_DESIGNATION_CODES or lot.lot_type == "street"


async def _ticket_to_lookup(ticket: Ticket, db: AsyncSession) -> dict:
    """Convert a Ticket ORM object to a TicketLookup-compatible dict."""
    data = {
        c.key: getattr(ticket, c.key)
        for c in Ticket.__table__.columns
        if c.key in TicketLookup.model_fields
    }
    data["is_commuter_lot"] = await _check_commuter_lot(ticket.lot, db)
    return data


@router.get("/lookup")
async def lookup_by_plate(plate: str = ""):
    """Disabled — plate substring search removed for privacy. Use /lookup/{ticket_id} instead."""
    raise HTTPException(410, "Plate lookup has been disabled. Use the QR code on your ticket or the direct link from your email.")


@router.get("/lookup/{ticket_id}", response_model=TicketLookup)
async def lookup_by_id(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint for QR code deep links — fetch a single ticket for payment."""
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return await _ticket_to_lookup(ticket, db)


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

    return DisputeResponse(
        status="received",
        ticket_id=ticket.id,
        message="Your dispute has been submitted and will be reviewed within 5 business days. "
                "You will be contacted at the email or phone number provided.",
    )


COMMUTER_DESIGNATION_CODES = {"C", "PC", "FSC"}


@router.get("/permits/available", response_model=AvailablePermitsResponse)
async def available_permits(
    ticket_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — check which permit types are available for purchase.

    Only returns commuter permits, and only when the ticket was issued in a
    commuter-eligible lot (designation C, PC, FSC) or on a street.
    """
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    fine_reduction = es.permit_fine_reduction if es else Decimal("0.00")

    if ticket_id:
        ticket = await db.get(Ticket, ticket_id)
        if ticket and ticket.lot:
            lot_result = await db.execute(
                select(ParkingLot).where(
                    func.lower(ParkingLot.name) == ticket.lot.lower()
                )
            )
            lot = lot_result.scalar()
            if lot:
                is_commuter_lot = (
                    lot.designation_code in COMMUTER_DESIGNATION_CODES
                    or lot.lot_type == "street"
                )
                if not is_commuter_lot:
                    return AvailablePermitsResponse(
                        permit_types=[],
                        ticket_fine_after_purchase=fine_reduction,
                    )

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
    # Advisory lock to prevent duplicate checkout sessions from rapid clicks
    lock_key = hash(f"standalone:{data.email}:{data.permit_type_id}") % (2**31)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})

    permit_type = await db.get(PermitType, data.permit_type_id)
    if not permit_type:
        raise HTTPException(404, "Permit type not found")
    if not permit_type.is_purchasable_online:
        raise HTTPException(400, "This permit type is not available for online purchase")
    if permit_type.requires_lottery:
        raise HTTPException(400, "This permit type requires a lottery application")

    from ..models.lottery_v2 import LotteryV2Application
    active_count_result = await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.permit_type == permit_type.code,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    active_count = active_count_result.scalar() or 0
    lottery_reserved = (await db.execute(
        select(func.count()).select_from(LotteryV2Application).where(
            LotteryV2Application.assigned_permit_type_id == permit_type.id,
            LotteryV2Application.status == "selected",
        )
    )).scalar() or 0
    if (active_count + lottery_reserved) >= permit_type.max_capacity:
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
    """Public endpoint — verify a Stripe checkout session's payment status.

    Also triggers permit fulfillment if the session is paid but no permit exists yet.
    """
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

        # Trigger permit fulfillment for paid permit sessions
        permit_fulfilled = False
        ticket_fulfilled = False
        if payment_status == "paid" and payment_type in ("direct_permit_purchase", "lottery_v2_permit", "standalone_permit_purchase"):
            try:
                from ..services.stripe_reconciler import _fulfill_session, _permit_exists_for_session
                stripe_pi = data.get("payment_intent", "")
                if not await _permit_exists_for_session(db, stripe_pi):
                    result = await _fulfill_session(db, data)
                    if result:
                        await db.commit()
                        permit_fulfilled = True
            except Exception as e:
                logger.warning("verify-session fulfillment failed (reconciler will retry): %s", e)

        # Trigger admin permit charge fulfillment
        if payment_status == "paid" and payment_type == "admin_permit_charge":
            try:
                from ..services.stripe_reconciler import _fulfill_admin_charge
                result = await _fulfill_admin_charge(db, data)
                if result:
                    await db.commit()
                    permit_fulfilled = True
            except Exception as e:
                logger.warning("verify-session admin charge fulfillment failed (reconciler will retry): %s", e)

        # Trigger ticket fulfillment for paid ticket sessions
        if payment_status == "paid" and payment_type == "ticket_payment" and ticket_id:
            try:
                stripe_pi = data.get("payment_intent", "")
                already_paid = False
                if stripe_pi:
                    existing = await db.execute(
                        select(Payment).where(Payment.stripe_payment_id == stripe_pi)
                    )
                    already_paid = existing.scalar() is not None
                if not already_paid:
                    success = await _handle_ticket_payment(data, metadata, db)
                    if success:
                        await db.commit()
                        ticket_fulfilled = True
            except Exception as e:
                logger.warning("verify-session ticket fulfillment failed (reconciler will retry): %s", e)

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
            "permit_fulfilled": permit_fulfilled,
            "ticket_fulfilled": ticket_fulfilled,
        }
    except Exception as e:
        return {"status": "error", "payment_status": "unknown", "detail": str(e)}


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Webhook endpoint is disabled. Returns 200 so Stripe stops retrying."""
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

    lot_assignment = metadata.get("lot_assignment") or ""
    permit_type_id = metadata.get("permit_type_id")
    if not lot_assignment and permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ", ".join(pt.lot_assignments)

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=student_name,
        email=email or None,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=valid_days),
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

    lot_assignment = metadata.get("lot_assignment") or ""
    permit_type_id = metadata.get("permit_type_id")
    if not lot_assignment and permit_type_id:
        pt = await db.get(PT, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ", ".join(pt.lot_assignments)

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=student_name,
        email=email or None,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=valid_days),
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


async def _handle_lottery_v2_permit(session: dict, metadata: dict, db: AsyncSession) -> bool:
    """Handle payment for a Lottery V2 (waterfall) winning application."""
    from ..models.lottery_v2 import LotteryV2Application
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

    app = await db.get(LotteryV2Application, uuid.UUID(app_id))
    if not app or app.status != "selected":
        return False

    # Upgrade path: revoke old permit, issue new, advance old tier waitlist
    if metadata.get("is_upgrade") == "true" or app.is_upgrade:
        from ..services.lottery_v2_runner import complete_upgrade
        from ..models.permit_type import PermitType as PT

        pt = await db.get(PT, app.assigned_permit_type_id)
        if not pt:
            return False

        stripe_pi = session.get("payment_intent", "")
        await complete_upgrade(db, app, pt)

        payment = Payment(
            amount=Decimal(session["amount_total"]) / 100,
            method="online_permit_purchase",
            stripe_payment_id=stripe_pi,
            payment_type="lottery_v2_permit",
            payer_name=app.student_name or None,
            payer_email=app.student_email or None,
            plate=app.plate or None,
            description=f"Upgrade to {pt.label} — {app.plate}",
        )
        db.add(payment)
        await db.flush()
        return True

    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    plate = metadata.get("plate", "")
    valid_days = int(metadata.get("valid_days", "365"))
    email = metadata.get("email", "") or metadata.get("student_email", "")

    lot_assignment = metadata.get("lot_assignment") or ""
    if not lot_assignment:
        permit_type_id = metadata.get("permit_type_id")
        if permit_type_id:
            pt = await db.get(PT, uuid.UUID(permit_type_id))
            if pt and pt.lot_assignments:
                lot_assignment = ", ".join(pt.lot_assignments)
        elif app.assigned_permit_type_id:
            pt = await db.get(PT, app.assigned_permit_type_id)
            if pt:
                permit_type_code = permit_type_code or pt.code
                if pt.lot_assignments:
                    lot_assignment = ", ".join(pt.lot_assignments)

    # Final capacity guard for lottery permits
    guard_pt = None
    permit_type_id = metadata.get("permit_type_id")
    if permit_type_id:
        guard_pt = await db.get(PT, uuid.UUID(permit_type_id))
    elif app.assigned_permit_type_id:
        guard_pt = await db.get(PT, app.assigned_permit_type_id)
    if guard_pt and guard_pt.max_capacity:
        active_count = (await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == guard_pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )).scalar() or 0
        if active_count >= guard_pt.max_capacity:
            logger.error(
                "CAPACITY BREACH BLOCKED (lottery): %s at %d/%d active permits. "
                "Student %s payment succeeded but permit not issued — refund required.",
                guard_pt.code, active_count, guard_pt.max_capacity,
                app.student_email,
            )
            return False

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=student_name or app.student_name,
        email=email or app.student_email or None,
        phone=app.phone or metadata.get("phone", "") or "",
        sms_opt_in=bool(app.sms_opt_in) or metadata.get("sms_opt_in") == "true",
        plates=[plate or app.plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    payment = Payment(
        amount=Decimal(session["amount_total"]) / 100,
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi,
        payment_type="lottery_v2_permit",
        payer_name=(student_name or app.student_name) or None,
        payer_email=(email or app.student_email) or None,
        plate=(plate or app.plate) or None,
        description=(
            f"Lottery Permit ({permit_type_code}) — {plate or app.plate}"
            if (plate or app.plate)
            else f"Lottery Permit ({permit_type_code})"
        ),
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
    sms_opt_in = metadata.get("sms_opt_in") == "true"
    valid_days = int(metadata.get("valid_days", "365"))

    lot_assignment = metadata.get("assigned_lot") or metadata.get("lot_assignment") or ""
    permit_type_id = metadata.get("permit_type_id")
    pt = None
    if not lot_assignment and permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))
        if pt and pt.lot_assignments:
            lot_assignment = ", ".join(pt.lot_assignments)
    elif permit_type_id:
        pt = await db.get(PermitType, uuid.UUID(permit_type_id))

    # Final capacity guard — prevent over-issue even if the purchase was valid when initiated
    if pt and pt.max_capacity:
        from ..models.lottery_v2 import LotteryV2Application
        active_count = (await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )).scalar() or 0
        if active_count >= pt.max_capacity:
            logger.error(
                "CAPACITY BREACH BLOCKED: %s at %d/%d active permits. "
                "Student %s payment succeeded but permit not issued — refund required.",
                pt.code, active_count, pt.max_capacity, email,
            )
            return False

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=student_name,
        email=email or None,
        phone=phone or "",
        sms_opt_in=sms_opt_in,
        plates=[plate],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=valid_days),
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


@router.post("/reconcile-permits")
async def reconcile_permits(
    lookback_hours: int = Query(48, ge=1, le=168),
    user: OktaUser = Depends(require_admin()),
):
    """Manually trigger Stripe permit reconciliation.

    Polls Stripe for paid checkout sessions in the last N hours and creates
    permits for any that were paid but never fulfilled (e.g. student closed tab).
    """
    from ..services.stripe_reconciler import reconcile_stripe_permits
    result = await reconcile_stripe_permits(lookback_hours=lookback_hours)
    return result


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
        return {"error": "STRIPE_SECRET_KEY is empty", "key_prefix": ""}

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

    # Prefer latest_charge (expanded via API), fall back to charges.data[0]
    ch = None
    if latest_charge and hasattr(latest_charge, "id"):
        ch = latest_charge
    elif charges and charges.data:
        ch = charges.data[0]

    if ch:
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
    elif ch:
        billing = getattr(ch, "billing_details", None)
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
    refresh: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """
    Serve Stripe transactions from a local cache. On each call, fetch only
    new records from Stripe (created after the newest cached record) and
    merge them into the cache. Pass ?refresh=true to force a full re-sync.
    """
    import traceback
    from ..models.stripe_cache import StripeTransactionCache

    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured — STRIPE_SECRET_KEY is empty")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    errors: list[str] = []

    # Determine the cutoff: fetch only records newer than our latest cached entry
    latest_q = await db.execute(
        select(func.max(StripeTransactionCache.created_at))
    )
    latest_cached = latest_q.scalar()

    # If refresh requested or cache is empty, do a full sync
    if refresh or latest_cached is None:
        created_after = None
    else:
        import calendar
        created_after = int(calendar.timegm(latest_cached.timetuple()))

    # Fetch new records from Stripe and upsert into cache
    new_count = 0
    seen_pi_ids: set[str] = set()

    def _cache_txn(txn: StripeTransaction):
        nonlocal new_count
        return StripeTransactionCache(
            id=txn.id,
            source=txn.source,
            amount=txn.amount,
            amount_refunded=txn.amount_refunded,
            net=txn.net,
            fee=txn.fee,
            currency=txn.currency,
            status=txn.status,
            description=txn.description,
            customer_email=txn.customer_email,
            customer_name=txn.customer_name,
            receipt_url=txn.receipt_url,
            payment_method_type=txn.payment_method_type,
            payment_method_last4=txn.payment_method_last4,
            payment_method_brand=txn.payment_method_brand,
            metadata_json=txn.metadata,
            created_at=txn.created,
            livemode=txn.livemode,
        )

    try:
        params: dict = {"limit": 100, "expand": ["data.balance_transaction"]}
        if created_after:
            params["created"] = {"gt": created_after}
        charges_iter = stripe.Charge.list(**params).auto_paging_iter()
        for ch in charges_iter:
            try:
                txn = _charge_to_txn(ch)
                pi_id = getattr(ch, "payment_intent", None)
                if pi_id:
                    seen_pi_ids.add(pi_id)
                existing = await db.get(StripeTransactionCache, txn.id)
                if not existing:
                    db.add(_cache_txn(txn))
                    new_count += 1
                else:
                    existing.status = txn.status
                    existing.amount_refunded = txn.amount_refunded
                    existing.net = txn.net
                    existing.fee = txn.fee
            except Exception as e:
                errors.append(f"charge {ch.id}: {e}")
    except Exception as e:
        errors.append(f"Charge.list failed: {e}\n{traceback.format_exc()}")

    try:
        pi_params: dict = {"limit": 100, "expand": ["data.latest_charge.balance_transaction"]}
        if created_after:
            pi_params["created"] = {"gt": created_after}
        pis_iter = stripe.PaymentIntent.list(**pi_params).auto_paging_iter()
        for pi in pis_iter:
            try:
                if pi.id in seen_pi_ids:
                    continue
                seen_pi_ids.add(pi.id)
                txn = _pi_to_txn(pi)
                existing = await db.get(StripeTransactionCache, txn.id)
                if not existing:
                    db.add(_cache_txn(txn))
                    new_count += 1
                else:
                    existing.status = txn.status
                    existing.amount_refunded = txn.amount_refunded
                    existing.net = txn.net
                    existing.fee = txn.fee
            except Exception as e:
                errors.append(f"pi {pi.id}: {e}")
    except Exception as e:
        errors.append(f"PaymentIntent.list failed: {e}\n{traceback.format_exc()}")

    try:
        sess_params: dict = {"limit": 100}
        if created_after:
            sess_params["created"] = {"gt": created_after}
        sessions_iter = stripe.checkout.Session.list(**sess_params).auto_paging_iter()
        for sess in sessions_iter:
            try:
                sess_pi = getattr(sess, "payment_intent", None)
                if sess_pi and sess_pi in seen_pi_ids:
                    continue
                txn = _session_to_txn(sess)
                existing = await db.get(StripeTransactionCache, txn.id)
                if not existing:
                    db.add(_cache_txn(txn))
                    new_count += 1
            except Exception as e:
                errors.append(f"session {sess.id}: {e}")
    except Exception as e:
        errors.append(f"Session.list failed: {e}\n{traceback.format_exc()}")

    await db.flush()

    # Now serve from cache
    all_q = await db.execute(
        select(StripeTransactionCache).order_by(StripeTransactionCache.created_at.desc())
    )
    all_cached = all_q.scalars().all()

    overview = {
        "total_volume": Decimal("0"), "total_fees": Decimal("0"),
        "total_net": Decimal("0"), "total_refunded": Decimal("0"),
        "successful_count": 0, "refunded_count": 0, "failed_count": 0,
    }
    transactions: list[dict] = []
    for row in all_cached:
        if row.status == "succeeded":
            overview["successful_count"] += 1
            overview["total_volume"] += row.amount
            overview["total_fees"] += row.fee
            overview["total_net"] += row.net
        if row.amount_refunded > 0:
            overview["refunded_count"] += 1
            overview["total_refunded"] += row.amount_refunded
        if row.status == "failed":
            overview["failed_count"] += 1

        transactions.append({
            "id": row.id,
            "source": row.source,
            "amount": str(row.amount),
            "amount_refunded": str(row.amount_refunded),
            "net": str(row.net),
            "fee": str(row.fee),
            "currency": row.currency,
            "status": row.status,
            "description": row.description,
            "customer_email": row.customer_email,
            "customer_name": row.customer_name,
            "receipt_url": row.receipt_url,
            "payment_method_type": row.payment_method_type,
            "payment_method_last4": row.payment_method_last4,
            "payment_method_brand": row.payment_method_brand,
            "metadata": row.metadata_json or {},
            "created": row.created_at.isoformat(),
            "livemode": row.livemode,
        })

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
        "has_more": False,
        "errors": errors,
        "new_synced": new_count,
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


class RefundRequest(BaseModel):
    charge_id: str
    reason: str = "requested_by_customer"
    note: str | None = None


def _refund_target_kwargs(stripe_mod, txn_id: str) -> dict:
    """Map a cached Stripe id (ch_/py_/pi_/cs_) to Refund.create kwargs."""
    if txn_id.startswith(("ch_", "py_")):
        return {"charge": txn_id}
    if txn_id.startswith("pi_"):
        return {"payment_intent": txn_id}
    if txn_id.startswith("cs_"):
        sess = stripe_mod.checkout.Session.retrieve(txn_id)
        pi = getattr(sess, "payment_intent", None)
        if not pi:
            raise ValueError("Checkout session has no payment_intent")
        return {"payment_intent": pi if isinstance(pi, str) else pi.id}
    raise ValueError(f"Unsupported Stripe id prefix: {txn_id}")


def _live_refundable(stripe_mod, txn_id: str) -> tuple[Decimal, dict]:
    """Current refundable balance from Stripe, plus kwargs for Refund.create."""
    kwargs = _refund_target_kwargs(stripe_mod, txn_id)
    ch = None
    if "charge" in kwargs:
        ch = stripe_mod.Charge.retrieve(kwargs["charge"])
    else:
        pi = stripe_mod.PaymentIntent.retrieve(
            kwargs["payment_intent"], expand=["latest_charge"],
        )
        ch = getattr(pi, "latest_charge", None)
        if isinstance(ch, str):
            ch = stripe_mod.Charge.retrieve(ch)
    if not ch:
        raise ValueError("No charge found for this transaction")
    amount = Decimal(str(ch.amount)) / 100
    refunded = Decimal(str(getattr(ch, "amount_refunded", 0) or 0)) / 100
    return amount - refunded, kwargs


def _stripe_error_message(exc: Exception) -> str:
    code = getattr(exc, "code", None) or ""
    user_msg = getattr(exc, "user_message", None) or str(exc)
    if code == "balance_insufficient":
        return "Insufficient Stripe available balance to issue this refund"
    if code in ("charge_already_refunded", "amount_too_large"):
        return user_msg
    return user_msg


@router.post("/refund")
async def refund_stripe_charge(
    data: RefundRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Admin: full refund of a Stripe charge (e.g. fee-exempt student charged in error)."""
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe

    stripe.api_key = settings.stripe_secret_key
    try:
        kwargs = _refund_target_kwargs(stripe, data.charge_id)
        refund = stripe.Refund.create(
            **kwargs,
            reason=data.reason if data.reason in ("duplicate", "fraudulent", "requested_by_customer") else "requested_by_customer",
            metadata={
                "refunded_by": admin.email or admin.sub,
                "note": (data.note or "")[:500],
            },
        )
    except Exception as e:
        raise HTTPException(400, f"Stripe refund failed: {e}") from e

    logger.info(
        "Admin %s refunded charge %s → refund %s",
        admin.email, data.charge_id, getattr(refund, "id", None),
    )
    return {
        "status": getattr(refund, "status", "unknown"),
        "refund_id": getattr(refund, "id", None),
        "charge_id": data.charge_id,
        "amount": (getattr(refund, "amount", 0) or 0) / 100,
    }


MAX_BULK_REFUND = 500
BULK_REFUND_DELAY_S = 0.12


def _dedupe_ids(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in ids:
        tid = (raw or "").strip()
        if not tid or tid in seen:
            continue
        seen.add(tid)
        out.append(tid)
    return out


@router.post("/bulk-refund/preview", response_model=BulkRefundPreviewResponse)
async def bulk_refund_preview(
    data: BulkRefundRequest,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Classify selected Stripe transactions as eligible or skipped for a partial refund."""
    from ..models.stripe_cache import StripeTransactionCache
    from ..services.bulk_refund import evaluate_transaction, parse_money

    ids = _dedupe_ids(data.transaction_ids)
    if not ids:
        raise HTTPException(400, "No transactions selected")
    if len(ids) > MAX_BULK_REFUND:
        raise HTTPException(400, f"Maximum {MAX_BULK_REFUND} transactions per bulk refund")

    mode = (data.mode or "flat").lower()
    if mode not in ("flat", "percent"):
        raise HTTPException(400, "mode must be 'flat' or 'percent'")
    try:
        amount = parse_money(data.amount)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    rows_q = await db.execute(
        select(StripeTransactionCache).where(StripeTransactionCache.id.in_(ids))
    )
    by_id = {row.id: row for row in rows_q.scalars().all()}

    eligible: list[BulkRefundPreviewRow] = []
    skipped: list[BulkRefundPreviewRow] = []
    total = Decimal("0.00")

    for txn_id in ids:
        row = by_id.get(txn_id)
        if not row:
            classified = evaluate_transaction(
                txn_id=txn_id,
                status="missing",
                original=Decimal("0"),
                already_refunded=Decimal("0"),
                mode=mode,
                amount=amount,
            )
            classified["skip_reason"] = "not found in Stripe cache — run Full Sync"
            classified["eligible"] = False
        else:
            classified = evaluate_transaction(
                txn_id=row.id,
                status=row.status,
                original=row.amount or Decimal("0"),
                already_refunded=row.amount_refunded or Decimal("0"),
                mode=mode,
                amount=amount,
                customer_name=row.customer_name,
                customer_email=row.customer_email,
                description=row.description,
            )
        item = BulkRefundPreviewRow(**classified)
        if item.eligible:
            eligible.append(item)
            total += Decimal(item.proposed or "0")
        else:
            skipped.append(item)

    return BulkRefundPreviewResponse(
        eligible=eligible,
        skipped=skipped,
        eligible_count=len(eligible),
        skipped_count=len(skipped),
        total_refund=str(total),
    )


@router.post("/bulk-refund")
async def bulk_refund_execute(
    data: BulkRefundRequest,
    admin: OktaUser = Depends(require_admin()),
):
    """Issue partial Stripe refunds for the given transactions. Streams NDJSON progress."""
    import asyncio
    import json as _json
    import stripe
    from fastapi.responses import StreamingResponse

    from ..database import async_session as session_factory
    from ..models.audit_log import AuditLog
    from ..models.stripe_cache import StripeTransactionCache
    from ..services.bulk_refund import (
        evaluate_transaction,
        parse_money,
        refund_idempotency_key,
    )

    if not data.confirm:
        raise HTTPException(400, "confirm must be true to process refunds")
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    ids = _dedupe_ids(data.transaction_ids)
    if not ids:
        raise HTTPException(400, "No transactions selected")
    if len(ids) > MAX_BULK_REFUND:
        raise HTTPException(400, f"Maximum {MAX_BULK_REFUND} transactions per bulk refund")

    mode = (data.mode or "flat").lower()
    if mode not in ("flat", "percent"):
        raise HTTPException(400, "mode must be 'flat' or 'percent'")
    try:
        amount = parse_money(data.amount)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e

    stripe.api_key = settings.stripe_secret_key
    admin_email = admin.email or admin.sub

    async def _generate():
        succeeded = 0
        failed = 0
        skipped = 0
        yield _json.dumps({"event": "start", "total": len(ids)}) + "\n"

        async with session_factory() as db:
            rows_q = await db.execute(
                select(StripeTransactionCache).where(StripeTransactionCache.id.in_(ids))
            )
            by_id = {row.id: row for row in rows_q.scalars().all()}

            for index, txn_id in enumerate(ids, start=1):
                payload = {
                    "event": "item",
                    "index": index,
                    "total": len(ids),
                    "id": txn_id,
                }
                cache_row = by_id.get(txn_id)
                original = cache_row.amount if cache_row else Decimal("0")
                already = cache_row.amount_refunded if cache_row else Decimal("0")
                status = cache_row.status if cache_row else "missing"

                classified = evaluate_transaction(
                    txn_id=txn_id,
                    status=status,
                    original=original,
                    already_refunded=already,
                    mode=mode,
                    amount=amount,
                    customer_name=cache_row.customer_name if cache_row else None,
                    customer_email=cache_row.customer_email if cache_row else None,
                )
                if not classified["eligible"]:
                    skipped += 1
                    payload.update({
                        "status": "skipped",
                        "reason": classified["skip_reason"],
                        "customer_email": classified.get("customer_email"),
                    })
                    yield _json.dumps(payload) + "\n"
                    continue

                proposed = Decimal(classified["proposed"])
                cents = int((proposed * 100).quantize(Decimal("1")))

                try:
                    live_refundable, kwargs = _live_refundable(stripe, txn_id)
                    if proposed > live_refundable:
                        skipped += 1
                        payload.update({
                            "status": "skipped",
                            "reason": (
                                f"refund ${proposed} exceeds live refundable "
                                f"balance ${live_refundable.quantize(Decimal('0.01'))}"
                            ),
                            "customer_email": classified.get("customer_email"),
                        })
                        yield _json.dumps(payload) + "\n"
                        continue

                    refund = stripe.Refund.create(
                        **kwargs,
                        amount=cents,
                        reason="requested_by_customer",
                        metadata={
                            "type": "bulk_partial_refund",
                            "refunded_by": admin_email,
                            "mode": mode,
                            "requested_amount": str(amount),
                            "transaction_id": txn_id,
                        },
                        idempotency_key=refund_idempotency_key(txn_id, cents),
                    )
                    refund_id = getattr(refund, "id", None)
                    refund_status = getattr(refund, "status", "unknown")
                    refunded_now = Decimal(str(getattr(refund, "amount", cents) or cents)) / 100

                    if cache_row:
                        try:
                            live_left, _ = _live_refundable(stripe, txn_id)
                            cache_row.amount_refunded = max(
                                Decimal("0.00"),
                                (cache_row.amount or Decimal("0")) - live_left,
                            )
                        except Exception:
                            cache_row.amount_refunded = (
                                (cache_row.amount_refunded or Decimal("0")) + refunded_now
                            )
                    db.add(AuditLog(
                        user_email=admin_email,
                        user_sub=admin.sub or "",
                        action="POST",
                        resource_type="payment",
                        resource_id=txn_id[:64],
                        endpoint="/api/payments/bulk-refund",
                        summary=f"Bulk refund ${refunded_now:.2f} on {txn_id} → {refund_id}",
                        response_status=200,
                        changes={
                            "refund_id": refund_id,
                            "amount": str(refunded_now),
                            "stripe_status": refund_status,
                            "mode": mode,
                        },
                    ))
                    await db.commit()
                    succeeded += 1
                    payload.update({
                        "status": "succeeded",
                        "refund_id": refund_id,
                        "refund_status": refund_status,
                        "amount": str(refunded_now),
                        "customer_email": classified.get("customer_email"),
                        "customer_name": classified.get("customer_name"),
                    })
                except Exception as e:
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                    failed += 1
                    payload.update({
                        "status": "failed",
                        "reason": _stripe_error_message(e),
                        "customer_email": classified.get("customer_email"),
                        "customer_name": classified.get("customer_name"),
                    })
                    logger.warning(
                        "Bulk refund failed for %s: %s", txn_id, e, exc_info=True,
                    )

                yield _json.dumps(payload) + "\n"
                await asyncio.sleep(BULK_REFUND_DELAY_S)

            db.add(AuditLog(
                user_email=admin_email,
                user_sub=admin.sub or "",
                action="POST",
                resource_type="payment",
                resource_id=None,
                endpoint="/api/payments/bulk-refund",
                summary=(
                    f"Bulk refund batch complete: {succeeded} succeeded, "
                    f"{failed} failed, {skipped} skipped "
                    f"({mode} {amount})"
                ),
                response_status=200,
                changes={
                    "succeeded": succeeded,
                    "failed": failed,
                    "skipped": skipped,
                    "mode": mode,
                    "amount": str(amount),
                    "count": len(ids),
                },
            ))
            await db.commit()

        yield _json.dumps({
            "event": "done",
            "succeeded": succeeded,
            "failed": failed,
            "skipped": skipped,
            "total": len(ids),
        }) + "\n"

    return StreamingResponse(_generate(), media_type="application/x-ndjson")


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

    batch_date = today_local().isoformat()
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
