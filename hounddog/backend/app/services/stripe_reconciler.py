"""
Stripe payment fulfillment reconciler.

Polls Stripe for completed checkout sessions (permits AND tickets) where
no corresponding fulfilled record exists in our DB. Creates the permit/payment
records for any paid-but-unfulfilled sessions.

Runs automatically in the scheduler loop every 5 minutes, and can also be
triggered manually via the admin API.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import async_session
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..services.lot_assignment import resolve_lot_code
from ..services.permit_numbering import next_permit_number
from .timeutils import today_local

logger = logging.getLogger("quarry.stripe_reconciler")

PERMIT_SESSION_TYPES = {"direct_permit_purchase", "lottery_v2_permit", "standalone_permit_purchase"}
ADMIN_CHARGE_TYPE = "admin_permit_charge"
ALL_RECONCILABLE_TYPES = PERMIT_SESSION_TYPES | {"ticket_payment", ADMIN_CHARGE_TYPE}


async def _permit_exists_for_session(db: AsyncSession, stripe_pi: str) -> bool:
    """Check if we already created a permit for this Stripe payment intent."""
    if not stripe_pi:
        return False
    result = await db.execute(
        select(func.count()).select_from(Payment).where(
            Payment.stripe_payment_id == stripe_pi,
            Payment.payment_type.in_(PERMIT_SESSION_TYPES),
        )
    )
    return (result.scalar() or 0) > 0


async def _fulfill_session(db: AsyncSession, session_data: dict) -> str | None:
    """Create a Permit + Payment from a paid Stripe checkout session.

    Returns the permit_type_code on success, None if skipped.
    """
    metadata = session_data.get("metadata") or {}
    payment_type = metadata.get("type", "")
    if payment_type not in PERMIT_SESSION_TYPES:
        return None

    stripe_pi = session_data.get("payment_intent", "")
    if await _permit_exists_for_session(db, stripe_pi):
        return None

    permit_type_code = metadata.get("permit_type_code", "")
    student_name = metadata.get("student_name", "")
    student_id = metadata.get("student_id", "")
    plate = metadata.get("plate", "")
    email = metadata.get("email") or metadata.get("student_email") or session_data.get("customer_email") or ""
    phone = metadata.get("phone", "") or ""
    sms_opt_in = metadata.get("sms_opt_in") == "true"
    valid_days = int(metadata.get("valid_days", "365"))

    lot_assignment = metadata.get("assigned_lot") or metadata.get("lot_assignment") or ""
    if not lot_assignment:
        permit_type_id = metadata.get("permit_type_id")
        if permit_type_id:
            try:
                pt = await db.get(PermitType, uuid.UUID(permit_type_id))
                if pt and pt.lot_assignments:
                    lot_assignment = resolve_lot_code(None, list(pt.lot_assignments))
            except (ValueError, TypeError):
                pass

    if not lot_assignment:
        lot_from_meta = metadata.get("lot_assignments", "")
        if lot_from_meta:
            lot_assignment = lot_from_meta.split(",")[0].strip() if lot_from_meta else ""

    amount_total = session_data.get("amount_total", 0)

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        student_id=student_id,
        name=student_name,
        email=email or None,
        phone=phone,
        sms_opt_in=sms_opt_in,
        plates=[plate] if plate else [],
        permit_type=permit_type_code,
        lot_assignment=lot_assignment,
        start_date=today_local(),
        end_date=today_local() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    payment = Payment(
        amount=Decimal(amount_total) / 100 if amount_total else Decimal("0.00"),
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi or None,
        payment_type=payment_type,
        payer_name=student_name or None,
        payer_email=email or None,
        plate=plate or None,
        description=f"Permit ({permit_type_code}) — {plate}" if plate else f"Permit ({permit_type_code})",
    )
    db.add(payment)

    if payment_type == "lottery_v2_permit":
        app_id = metadata.get("application_id")
        if app_id:
            try:
                from ..models.lottery_v2 import LotteryV2Application
                app = await db.get(LotteryV2Application, uuid.UUID(app_id))
                if app and app.status == "selected":
                    app.status = "accepted"
            except (ValueError, TypeError):
                pass

    await db.flush()

    # Send confirmation email (best-effort, don't fail fulfillment)
    if email:
        try:
            from .email import send_permit_confirmation_email
            permit_label = metadata.get("permit_type_label", permit_type_code)
            await send_permit_confirmation_email(
                recipient_email=email,
                student_name=student_name,
                permit_type_label=permit_label,
                permit_number=new_permit.permit_number or "",
                plate=plate,
                lot_assignment=lot_assignment,
                start_date=new_permit.start_date.strftime("%B %d, %Y"),
                end_date=new_permit.end_date.strftime("%B %d, %Y"),
            )
        except Exception as e:
            logger.warning("Permit confirmation email failed for %s: %s", email, e)

    return permit_type_code


async def _fulfill_ticket_payment(db: AsyncSession, session_data: dict) -> bool:
    """Mark a ticket as paid from a Stripe checkout session.

    Returns True on success, False if skipped (already fulfilled or invalid).
    """
    metadata = session_data.get("metadata") or {}
    ticket_id = metadata.get("ticket_id")
    if not ticket_id:
        return False

    stripe_pi = session_data.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return False

    from ..models.ticket import Ticket
    try:
        ticket = await db.get(Ticket, uuid.UUID(ticket_id))
    except (ValueError, TypeError):
        return False
    if not ticket:
        return False
    if ticket.status in ("paid", "voided", "resolved_permit"):
        return False

    ticket_ref = ticket.ticket_number or str(ticket.id)[:8].upper()
    payer_name = metadata.get("payer_name", "") or ""
    payer_email = session_data.get("customer_email", "") or ""
    amount_total = session_data.get("amount_total", 0)

    payment = Payment(
        ticket_id=ticket.id,
        amount=Decimal(amount_total) / 100 if amount_total else Decimal("0.00"),
        method="online_card",
        stripe_payment_id=stripe_pi or None,
        payment_type="ticket_payment",
        payer_name=payer_name or None,
        payer_email=payer_email or None,
        plate=ticket.plate,
        description=f"Citation #{ticket_ref} — {ticket.plate}",
    )
    db.add(payment)
    ticket.status = "paid"
    await db.flush()
    return True


async def _fulfill_admin_charge(db: AsyncSession, session_data: dict) -> bool:
    """Activate an admin-issued pending_payment permit after Stripe payment completes.

    Returns True on success, False if skipped.
    """
    metadata = session_data.get("metadata") or {}
    permit_id_str = metadata.get("permit_id")
    if not permit_id_str:
        return False

    stripe_pi = session_data.get("payment_intent", "")
    if stripe_pi:
        existing = await db.execute(
            select(Payment).where(Payment.stripe_payment_id == stripe_pi)
        )
        if existing.scalar():
            return False

    try:
        permit = await db.get(Permit, uuid.UUID(permit_id_str))
    except (ValueError, TypeError):
        return False
    if not permit:
        return False
    if permit.status != "pending_payment":
        return False

    permit.status = "active"

    amount_total = session_data.get("amount_total", 0)
    permit_type_code = metadata.get("permit_type_code", "")
    plate = metadata.get("plate", "")

    payment = Payment(
        amount=Decimal(amount_total) / 100 if amount_total else Decimal("0.00"),
        method="online_permit_purchase",
        stripe_payment_id=stripe_pi or None,
        payment_type="admin_permit_charge",
        payer_name=permit.name or None,
        payer_email=permit.email or None,
        plate=plate or None,
        description=f"Admin permit ({permit_type_code}) — {plate}" if plate else f"Admin permit ({permit_type_code})",
    )
    db.add(payment)
    await db.flush()

    if permit.email:
        try:
            from .email import send_permit_confirmation_email
            permit_label = metadata.get("permit_type_label", permit_type_code)
            await send_permit_confirmation_email(
                recipient_email=permit.email,
                student_name=permit.name,
                permit_type_label=permit_label,
                permit_number=permit.permit_number or "",
                plate=plate,
                lot_assignment=permit.lot_assignment,
                start_date=permit.start_date.strftime("%B %d, %Y"),
                end_date=permit.end_date.strftime("%B %d, %Y") if permit.end_date else "N/A",
            )
        except Exception as e:
            logger.warning("Admin charge confirmation email failed for %s: %s", permit.email, e)

    return True


async def reconcile_stripe_payments(lookback_hours: int = 48) -> dict:
    """Poll Stripe for paid checkout sessions and fulfill any missing permits/tickets.

    Returns a summary dict with counts.
    """
    if not settings.stripe_secret_key:
        return {"error": "Stripe not configured", "fulfilled": 0, "already_fulfilled": 0, "tickets_fulfilled": 0}

    import stripe
    stripe.api_key = settings.stripe_secret_key

    created_after = int((datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).timestamp())
    fulfilled = 0
    tickets_fulfilled = 0
    already_fulfilled = 0
    errors: list[str] = []

    starting_after = None
    pages_checked = 0

    async with async_session() as db:
        while pages_checked < 10:
            params: dict = {
                "limit": 100,
                "status": "complete",
                "created": {"gte": created_after},
            }
            if starting_after:
                params["starting_after"] = starting_after

            try:
                page = stripe.checkout.Session.list(**params)
            except Exception as e:
                errors.append(f"Session.list failed: {e}")
                break

            if not page.data:
                break

            for sess in page.data:
                sess_dict = sess.to_dict() if hasattr(sess, "to_dict") else dict(sess)
                metadata = sess_dict.get("metadata") or {}
                payment_type = metadata.get("type", "")

                if payment_type not in ALL_RECONCILABLE_TYPES:
                    continue

                if sess_dict.get("payment_status") != "paid":
                    continue

                try:
                    if payment_type in PERMIT_SESSION_TYPES:
                        result = await _fulfill_session(db, sess_dict)
                        if result:
                            fulfilled += 1
                            logger.info(
                                "Reconciled permit: %s plate=%s pi=%s",
                                result,
                                metadata.get("plate", "?"),
                                sess_dict.get("payment_intent", "?")[:16],
                            )
                        else:
                            already_fulfilled += 1
                    elif payment_type == "ticket_payment":
                        result = await _fulfill_ticket_payment(db, sess_dict)
                        if result:
                            tickets_fulfilled += 1
                            logger.info(
                                "Reconciled ticket payment: ticket=%s pi=%s",
                                metadata.get("ticket_id", "?"),
                                sess_dict.get("payment_intent", "?")[:16],
                            )
                        else:
                            already_fulfilled += 1
                    elif payment_type == ADMIN_CHARGE_TYPE:
                        result = await _fulfill_admin_charge(db, sess_dict)
                        if result:
                            fulfilled += 1
                            logger.info(
                                "Reconciled admin permit charge: permit=%s pi=%s",
                                metadata.get("permit_id", "?"),
                                sess_dict.get("payment_intent", "?")[:16],
                            )
                        else:
                            already_fulfilled += 1
                except Exception as e:
                    errors.append(f"Fulfill failed for {sess.id}: {e}")
                    logger.error("Reconcile fulfill error for %s: %s", sess.id, e, exc_info=True)

            if not page.has_more:
                break
            starting_after = page.data[-1].id
            pages_checked += 1

        if fulfilled > 0 or tickets_fulfilled > 0:
            await db.commit()
            logger.info("Stripe reconciliation complete: %d permits, %d tickets fulfilled", fulfilled, tickets_fulfilled)
        else:
            await db.rollback()

    return {
        "fulfilled": fulfilled,
        "tickets_fulfilled": tickets_fulfilled,
        "already_fulfilled": already_fulfilled,
        "errors": errors,
    }


# Keep old name as alias for backward compat with scheduler
reconcile_stripe_permits = reconcile_stripe_payments
