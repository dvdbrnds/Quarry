"""
Central alert dispatcher. Fans out an alert to all configured channels
concurrently. Each channel sends independently -- one failure doesn't
block others.
"""

import asyncio
import logging
from dataclasses import asdict

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.alert_log import AlertLog
from ..models.alert_subscriber import AlertSubscriber
from .channels import ChannelResult, get_registry

logger = logging.getLogger("quarry.dispatcher")


async def _get_subscribers(alert: AlertLog, db: AsyncSession) -> list:
    is_emergency = alert.category == "emergency"

    if is_emergency:
        q = select(AlertSubscriber).where(
            or_(
                AlertSubscriber.email.isnot(None),
                AlertSubscriber.phone.isnot(None),
            )
        )
    else:
        q = select(AlertSubscriber).where(
            AlertSubscriber.categories.op("@>")(f'["{alert.category}"]'),
            or_(
                AlertSubscriber.email.isnot(None),
                AlertSubscriber.phone.isnot(None),
            ),
        )

    result = await db.execute(q)
    return list(result.scalars().all())


async def dispatch_alert(
    alert_id,
    db: AsyncSession,
    channels: list[str] | None = None,
) -> dict[str, dict]:
    """
    Fan out an alert to all configured channels.

    Args:
        alert_id: UUID of the AlertLog entry
        db: database session
        channels: optional list of channel names to limit delivery to

    Returns:
        dict of channel_name -> {sent, failed, error}
    """
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise ValueError(f"Alert {alert_id} not found")

    subscribers = await _get_subscribers(alert, db)
    registry = get_registry()

    results: dict[str, dict] = {}

    for channel in registry:
        if channels and channel.name not in channels:
            continue
        if not channel.is_configured():
            continue
        if channel.emergency_only and alert.category != "emergency":
            continue

        try:
            result = await channel.send(alert, subscribers)
            results[channel.name] = {
                "sent": result.sent,
                "failed": result.failed,
                "error": result.error,
            }
        except Exception as e:
            logger.error("Channel %s failed: %s", channel.name, e, exc_info=True)
            results[channel.name] = {"sent": 0, "failed": 0, "error": str(e)}

    alert.channel_results = results

    total_email = results.get("email", {}).get("sent", 0)
    total_sms = results.get("sms", {}).get("sent", 0)
    alert.email_count = total_email
    alert.sms_count = total_sms

    await db.flush()

    return results


async def clear_alert(alert_id, cleared_by: str, db: AsyncSession) -> AlertLog | None:
    """Clear an active alert and notify stateful channels."""
    alert = await db.get(AlertLog, alert_id)
    if not alert or alert.status != "active":
        return None

    from datetime import datetime, timezone
    alert.status = "cleared"
    alert.cleared_at = datetime.now(timezone.utc)
    alert.cleared_by = cleared_by

    for channel in get_registry():
        try:
            await channel.clear(alert)
        except Exception as e:
            logger.error("Channel %s clear failed: %s", channel.name, e)

    await db.flush()
    await db.refresh(alert)
    return alert


def init_channels():
    """Register all channel instances. Called once at startup."""
    from .channels import register_channel
    from .channels.sms_channel import SmsChannel
    from .channels.email_channel import EmailChannel
    from .channels.voice_channel import VoiceChannel
    from .channels.signage_channel import SignageChannel
    from .channels.banner_channel import BannerChannel
    from .channels.teams_channel import TeamsChannel
    from .channels.crestron_channel import CrestronChannel
    from .channels.pa_channel import PaChannel
    from .channels.zoom_phone_channel import ZoomPhoneChannel

    register_channel(SmsChannel())
    register_channel(EmailChannel())
    register_channel(VoiceChannel())
    register_channel(SignageChannel())
    register_channel(BannerChannel())
    register_channel(TeamsChannel())
    register_channel(CrestronChannel())
    register_channel(PaChannel())
    register_channel(ZoomPhoneChannel())

    configured = [c.name for c in get_registry() if c.is_configured()]
    logger.info("Alert channels initialized. Configured: %s", configured)
