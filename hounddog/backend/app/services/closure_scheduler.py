"""Background loop that processes scheduled lot closures and sends notifications."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from ..database import async_session
from ..models.lot import ParkingLot
from ..models.lot_closure import LotClosure
from ..models.permit import Permit
from ..config import settings
from .email import send_lot_closure_notification, send_lot_reopen_notification
from .sms import send_bulk_sms

logger = logging.getLogger("quarry.scheduler")

_task: asyncio.Task | None = None


async def _get_recipients_for_lot(lot_name: str, db) -> list[str]:
    recipients: set[str] = set()
    if settings.lot_closure_mailing_list:
        recipients.update(
            e.strip()
            for e in settings.lot_closure_mailing_list.split(",")
            if e.strip()
        )
    result = await db.execute(
        select(Permit.email).where(
            Permit.lot_assignment == lot_name,
            Permit.email.isnot(None),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    for (email,) in result.all():
        if email:
            recipients.add(email)
    return list(recipients)


async def _get_sms_recipients_for_lot(
    lot_name: str, is_emergency: bool, db
) -> list[str]:
    """Get phone numbers for SMS. Emergency = all with phone, else only opted-in."""
    q = select(Permit.phone, Permit.sms_opt_in).where(
        Permit.lot_assignment == lot_name,
        Permit.phone.isnot(None),
        Permit.status == "active",
        Permit.deleted_at.is_(None),
    )
    if not is_emergency:
        q = q.where(Permit.sms_opt_in.is_(True))

    result = await db.execute(q)
    return [row.phone for row in result.all() if row.phone]


async def _get_sms_body_for_closure(lot_name: str, reason: str, closes_at: str, reopens_at: str | None) -> str | None:
    """Try to find a matching SMS template for the closure reason."""
    from ..models.message_template import MessageTemplate
    async with async_session() as db:
        result = await db.execute(
            select(MessageTemplate).where(
                MessageTemplate.is_active.is_(True),
            )
        )
        templates = result.scalars().all()

    school = settings.school_name or "Campus"
    reason_lower = reason.lower()

    for tmpl in templates:
        if tmpl.reason_code.lower() in reason_lower or reason_lower in tmpl.reason_label.lower():
            body = tmpl.sms_body
            for k, v in {"lot_name": lot_name, "reason": reason, "closes_at": closes_at, "reopens_at": reopens_at or "TBD", "school": school}.items():
                body = body.replace(f"{{{k}}}", v or "")
            return body

    return f"{school} Parking: {lot_name} closed {closes_at}. Reason: {reason}."


async def _process_closures():
    now = datetime.now(timezone.utc)
    async with async_session() as db:
        scheduled = (
            await db.execute(
                select(LotClosure).where(
                    LotClosure.status == "scheduled",
                    LotClosure.closes_at <= now,
                )
            )
        ).scalars().all()

        for closure in scheduled:
            lot = await db.get(ParkingLot, closure.lot_id)
            if not lot:
                closure.status = "cancelled"
                continue

            lot.is_closed = True
            closure.status = "active"

            if not closure.notification_sent:
                recipients = await _get_recipients_for_lot(lot.name, db)
                reopens_str = (
                    closure.reopens_at.strftime("%b %d, %Y %I:%M %p")
                    if closure.reopens_at
                    else None
                )
                closes_str = closure.closes_at.strftime("%b %d, %Y %I:%M %p %Z")
                sent = await send_lot_closure_notification(
                    lot_name=lot.name,
                    reason=closure.reason,
                    recipients=recipients,
                    closes_at=closes_str,
                    reopens_at=reopens_str,
                )
                closure.notification_sent = sent
                logger.info(
                    "Closure activated: lot=%s, email_recipients=%d, sent=%s",
                    lot.name, len(recipients), sent,
                )

                is_emergency = "emergency" in (closure.reason or "").lower() or "snow" in (closure.reason or "").lower()
                sms_phones = await _get_sms_recipients_for_lot(lot.name, is_emergency, db)
                if sms_phones:
                    sms_body = await _get_sms_body_for_closure(
                        lot.name, closure.reason or "", closes_str, reopens_str
                    )
                    if sms_body:
                        sms_count = send_bulk_sms(sms_phones, sms_body)
                        logger.info(
                            "SMS sent for closure: lot=%s, sent=%d/%d, emergency=%s",
                            lot.name, sms_count, len(sms_phones), is_emergency,
                        )

        active_with_reopen = (
            await db.execute(
                select(LotClosure).where(
                    LotClosure.status == "active",
                    LotClosure.reopens_at.isnot(None),
                    LotClosure.reopens_at <= now,
                )
            )
        ).scalars().all()

        for closure in active_with_reopen:
            lot = await db.get(ParkingLot, closure.lot_id)
            if not lot:
                closure.status = "completed"
                continue

            other_active = (
                await db.execute(
                    select(LotClosure.id).where(
                        LotClosure.lot_id == closure.lot_id,
                        LotClosure.status == "active",
                        LotClosure.id != closure.id,
                    )
                )
            ).scalars().all()

            closure.status = "completed"

            if not other_active:
                lot.is_closed = False
                if not closure.reopen_notification_sent:
                    recipients = await _get_recipients_for_lot(lot.name, db)
                    sent = await send_lot_reopen_notification(lot.name, recipients)
                    closure.reopen_notification_sent = sent
                    logger.info(
                        "Lot reopened: lot=%s, recipients=%d, sent=%s",
                        lot.name, len(recipients), sent,
                    )

        await db.commit()


async def _expire_lottery_offers():
    """Expire overdue lottery offers and advance waitlisted applicants."""
    from datetime import timedelta
    from ..models.permit_application import PermitApplication
    from ..models.permit_type import PermitType

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        expired_result = await db.execute(
            select(PermitApplication).where(
                PermitApplication.status == "selected",
                PermitApplication.offer_expires_at.isnot(None),
                PermitApplication.offer_expires_at < now,
            )
        )
        expired = expired_result.scalars().all()
        if not expired:
            return

        type_ids_affected: set = set()
        for app in expired:
            app.status = "expired"
            type_ids_affected.add(app.permit_type_id)

        for pt_id in type_ids_affected:
            pt = await db.get(PermitType, pt_id)
            if not pt:
                continue

            next_app = (await db.execute(
                select(PermitApplication)
                .where(
                    PermitApplication.permit_type_id == pt_id,
                    PermitApplication.status == "waitlisted",
                )
                .order_by(PermitApplication.waitlist_position.asc())
                .limit(1)
            )).scalar()

            if next_app:
                next_app.status = "selected"
                next_app.offer_expires_at = now + timedelta(days=pt.offer_window_days)

                from .email import send_email
                await send_email(
                    to=[next_app.student_email],
                    subject=f"Parking Permit Offer — {pt.label}",
                    body_html=(
                        f"<p>A spot has opened up for <strong>{pt.label}</strong>.</p>"
                        f"<p>Log in to the student portal to accept your offer before "
                        f"<strong>{next_app.offer_expires_at.strftime('%b %d, %Y')}</strong>.</p>"
                    ),
                )
                logger.info(
                    "Lottery waitlist advanced: type=%s, promoted=%s",
                    pt.code, next_app.student_email,
                )

        await db.commit()
        logger.info("Expired %d lottery offers", len(expired))


async def _run_loop():
    logger.info("Closure scheduler started (60s interval)")
    while True:
        try:
            await _process_closures()
        except Exception as e:
            logger.error("Scheduler tick (closures) failed: %s", e, exc_info=True)

        try:
            from .permit_lifecycle import auto_escalate_tickets
            async with async_session() as db:
                async with db.begin():
                    await auto_escalate_tickets(db)
        except Exception as e:
            logger.error("Scheduler tick (escalation) failed: %s", e, exc_info=True)

        try:
            await _expire_lottery_offers()
        except Exception as e:
            logger.error("Scheduler tick (lottery offers) failed: %s", e, exc_info=True)

        await asyncio.sleep(60)


def start_scheduler():
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run_loop())
        logger.info("Closure scheduler task created")


def stop_scheduler():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None
