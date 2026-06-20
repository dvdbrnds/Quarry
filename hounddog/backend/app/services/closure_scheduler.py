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
                sent = await send_lot_closure_notification(
                    lot_name=lot.name,
                    reason=closure.reason,
                    recipients=recipients,
                    closes_at=closure.closes_at.strftime("%b %d, %Y %I:%M %p %Z"),
                    reopens_at=reopens_str,
                )
                closure.notification_sent = sent
                logger.info(
                    "Closure activated: lot=%s, recipients=%d, sent=%s",
                    lot.name, len(recipients), sent,
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


async def _run_loop():
    logger.info("Closure scheduler started (60s interval)")
    while True:
        try:
            await _process_closures()
        except Exception as e:
            logger.error("Scheduler tick failed: %s", e, exc_info=True)
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
