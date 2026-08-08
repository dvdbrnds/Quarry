"""Background loop that processes scheduled lot closures and sends notifications."""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from ..database import async_session
from ..models.lot import ParkingLot
from ..models.lot_closure import LotClosure
from ..models.permit import Permit
from ..config import settings
from .email import send_lot_closure_notification, send_lot_reopen_notification
from .sms import send_bulk_sms_async
from .timeutils import today_local
from .lot_assignment import permit_lot_matches

logger = logging.getLogger("quarry.scheduler")

_task: asyncio.Task | None = None
_last_renewal_check_date: date | None = None
_reconciler_tick_count: int = 0


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
            permit_lot_matches(lot_name),
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
        permit_lot_matches(lot_name),
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
                extra = list(closure.extra_recipients or []) if hasattr(closure, "extra_recipients") and closure.extra_recipients else []
                recipients = await _get_recipients_for_lot(lot.name, db)
                for e in extra:
                    if e and e not in recipients:
                        recipients.append(e)
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
                        sms_count = await send_bulk_sms_async(sms_phones, sms_body)
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


async def _auto_send_renewal_emails():
    """Automatically send renewal emails to faculty/staff with permits expiring on June 30.

    Runs daily as part of the scheduler loop. Sends emails starting ~60 days before
    June 30 to any faculty/staff permit holders who haven't already received one.
    """
    global _last_renewal_check_date

    today = today_local()
    if _last_renewal_check_date == today:
        return
    _last_renewal_check_date = today

    import secrets
    from ..models.renewal_token import RenewalToken
    june_30 = date(today.year, 6, 30)

    # Only send between May 1 and June 30
    may_1 = date(today.year, 5, 1)
    if today < may_1 or today > june_30:
        return

    async with async_session() as db:
        permits_result = await db.execute(
            select(Permit).where(
                Permit.status == "active",
                Permit.deleted_at.is_(None),
                Permit.permit_type == "faculty_staff",
                Permit.email.isnot(None),
                Permit.email != "",
                Permit.end_date.isnot(None),
                Permit.end_date <= june_30,
            )
        )
        permits = permits_result.scalars().all()

        sent = 0
        for permit in permits:
            existing = (await db.execute(
                select(RenewalToken).where(
                    RenewalToken.permit_id == permit.id,
                    RenewalToken.expires_at > datetime.now(timezone.utc),
                )
            )).scalar()

            if existing:
                continue

            token = secrets.token_urlsafe(48)
            renewal = RenewalToken(
                token=token,
                permit_id=permit.id,
                email=permit.email,
                expires_at=datetime.now(timezone.utc) + timedelta(days=45),
            )
            db.add(renewal)

            base_url = settings.student_facing_url.rstrip("/")
            renew_url = f"{base_url}/api/renewals/{token}/quick-renew"
            decline_url = f"{base_url}/api/renewals/{token}/decline"

            from .email import send_renewal_email
            try:
                await send_renewal_email(
                    recipient_email=permit.email,
                    name=permit.name,
                    permit_type=permit.permit_type,
                    lot_assignment=permit.lot_assignment,
                    end_date=permit.end_date.isoformat() if permit.end_date else "June 30",
                    renew_url=renew_url,
                    decline_url=decline_url,
                )
                sent += 1
            except Exception as e:
                logger.error("Auto-renewal email failed for %s: %s", permit.email, e)

        if sent:
            await db.commit()
            logger.info("Auto-sent %d renewal emails to faculty/staff", sent)


async def _auto_draw_deadline():
    """Run the waterfall draw if an open cycle's auto_draw_at deadline has passed."""
    from ..models.lottery_v2 import LotteryV2Cycle
    from .lottery_v2_runner import run_waterfall_draw

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        result = await db.execute(
            select(LotteryV2Cycle).where(
                LotteryV2Cycle.status == "open",
                LotteryV2Cycle.auto_draw_at.isnot(None),
                LotteryV2Cycle.auto_draw_at <= now,
            )
        )
        cycles = result.scalars().all()
        for cycle in cycles:
            logger.info(
                "Auto-draw deadline reached for cycle %s (deadline %s)",
                cycle.id, cycle.auto_draw_at,
            )
            try:
                await run_waterfall_draw(db, cycle.id, run_by="auto_draw_deadline")
                await db.commit()
            except Exception as e:
                logger.error("Auto-draw deadline failed for cycle %s: %s", cycle.id, e)
                await db.rollback()


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

            if not pt.auto_advance_waitlist:
                logger.info(
                    "Skipping auto-advance for %s — auto_advance_waitlist disabled",
                    pt.code,
                )
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

                from .email import send_lottery_selection_email
                from ..config import settings
                await send_lottery_selection_email(
                    recipient_email=next_app.student_email,
                    student_name=next_app.student_name,
                    permit_type_label=pt.label,
                    price=str(pt.price),
                    deadline=next_app.offer_expires_at.strftime("%B %d, %Y"),
                    portal_url=f"{settings.student_facing_url.rstrip('/')}/parking",
                    assigned_lot=next_app.assigned_lot,
                    lot_assignments=list(pt.lot_assignments or []),
                )
                logger.info(
                    "Lottery waitlist advanced: type=%s, promoted=%s",
                    pt.code, next_app.student_email,
                )

        await db.commit()
        logger.info("Expired %d lottery offers", len(expired))


async def _run_loop():
    logger.info("Closure scheduler started (60s interval)")

    # One-time startup: prune backup history to last 7 entries
    try:
        from .backup_scheduler import (
            _cleanup_old_backups_disk, _cleanup_old_backups_db,
            MAX_KEEP_COUNT, _check_backup_dir_size,
        )
        _cleanup_old_backups_disk(MAX_KEEP_COUNT)
        await _cleanup_old_backups_db(MAX_KEEP_COUNT)
        _check_backup_dir_size()
        logger.info("Startup backup cleanup completed (kept last %d)", MAX_KEEP_COUNT)
    except Exception as e:
        logger.error("Startup backup cleanup failed: %s", e, exc_info=True)

    while True:
        try:
            await _process_closures()
        except Exception as e:
            logger.error("Scheduler tick (closures) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            from .permit_lifecycle import auto_escalate_tickets
            async with async_session() as db:
                async with db.begin():
                    await auto_escalate_tickets(db)
        except Exception as e:
            logger.error("Scheduler tick (escalation) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            await _expire_lottery_offers()
        except Exception as e:
            logger.error("Scheduler tick (lottery offers) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            await _auto_draw_deadline()
        except Exception as e:
            logger.error("Scheduler tick (lottery auto-draw) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            await _auto_send_renewal_emails()
        except Exception as e:
            logger.error("Scheduler tick (renewal emails) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            from .alert_scheduler import process_scheduled_alerts
            await process_scheduled_alerts()
        except Exception as e:
            logger.error("Scheduler tick (scheduled alerts) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        try:
            from .backup_scheduler import process_scheduled_backups
            await process_scheduled_backups()
        except Exception as e:
            logger.error("Scheduler tick (scheduled backups) failed: %s", e, exc_info=True)
            try:
                import sentry_sdk; sentry_sdk.capture_exception(e)
            except Exception:
                pass

        # Stripe permit reconciliation — every 5 minutes (every 5th tick)
        global _reconciler_tick_count
        _reconciler_tick_count += 1
        if _reconciler_tick_count >= 5:
            _reconciler_tick_count = 0
            try:
                from .stripe_reconciler import reconcile_stripe_permits
                result = await reconcile_stripe_permits(lookback_hours=24)
                if result.get("fulfilled", 0) > 0:
                    logger.info("Stripe reconciler: %s", result)
            except Exception as e:
                logger.error("Scheduler tick (stripe reconciler) failed: %s", e, exc_info=True)
                try:
                    import sentry_sdk; sentry_sdk.capture_exception(e)
                except Exception:
                    pass

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
