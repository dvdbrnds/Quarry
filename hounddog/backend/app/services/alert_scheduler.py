"""
Scheduled / recurring alert processor.

Runs inside the existing closure_scheduler loop every 60s.
- Finds alerts with scheduled_for <= now() and status='scheduled', dispatches them.
- For recurring alerts, re-creates the next occurrence based on recurrence_rule.
"""

import logging
from datetime import datetime, timedelta, timezone

from dateutil.relativedelta import relativedelta
from sqlalchemy import select, update

from ..database import async_session
from ..models.alert_log import AlertLog
from .alert_dispatcher import dispatch_alert

logger = logging.getLogger("quarry.alert_scheduler")

RECURRENCE_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "biweekly": timedelta(weeks=2),
    "monthly": relativedelta(months=1),
    "quarterly": relativedelta(months=3),
    "yearly": relativedelta(years=1),
}


async def process_scheduled_alerts():
    """Find and dispatch all due scheduled alerts."""
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                select(AlertLog).where(
                    AlertLog.scheduled_for <= now,
                    AlertLog.status == "scheduled",
                )
            )
            due_alerts = result.scalars().all()

            for alert in due_alerts:
                try:
                    alert.status = "active"
                    await db.flush()

                    group_ids = None
                    if alert.target_group_ids:
                        import uuid as _uuid
                        group_ids = [_uuid.UUID(g) for g in alert.target_group_ids]

                    await dispatch_alert(alert.id, db, group_ids=group_ids)
                    logger.info("Dispatched scheduled alert %s: %s", alert.id, alert.subject)

                    if alert.recurrence_rule and alert.recurrence_rule in RECURRENCE_DELTAS:
                        next_time = alert.scheduled_for + RECURRENCE_DELTAS[alert.recurrence_rule]
                        import uuid as _uuid
                        new_alert = AlertLog(
                            id=_uuid.uuid4(),
                            category=alert.category,
                            subject=alert.subject,
                            body_text=alert.body_text,
                            body_sms=alert.body_sms,
                            sent_by=alert.sent_by,
                            status="scheduled",
                            response_options=alert.response_options,
                            is_checkin=alert.is_checkin,
                            target_group_ids=alert.target_group_ids,
                            scheduled_for=next_time,
                            recurrence_rule=alert.recurrence_rule,
                        )
                        db.add(new_alert)
                        logger.info(
                            "Created next recurring alert %s for %s (%s)",
                            new_alert.id, next_time, alert.recurrence_rule,
                        )

                except Exception as e:
                    logger.error("Failed to dispatch scheduled alert %s: %s", alert.id, e, exc_info=True)
                    alert.status = "failed"

            await db.flush()
