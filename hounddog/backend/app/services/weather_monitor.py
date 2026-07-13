"""
NWS weather alert auto-trigger.

Polls the National Weather Service API for active alerts in the configured zone
(default: PAC077 — Northampton County, PA / Bethlehem). When a matching event
type is detected, auto-dispatches an alert using the mapped template.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

from ..config import settings
from ..database import async_session
from ..models.alert_log import AlertLog
from ..models.alert_template import AlertTemplate
from .alert_dispatcher import dispatch_alert

logger = logging.getLogger("quarry.weather")

NWS_API = "https://api.weather.gov"
_seen_event_ids: set[str] = set()
_task: asyncio.Task | None = None

DEFAULT_EVENT_MAPPINGS = {
    "Tornado Warning": {"category": "emergency", "auto_send": True},
    "Severe Thunderstorm Warning": {"category": "weather", "auto_send": True},
    "Flash Flood Warning": {"category": "weather", "auto_send": True},
    "Blizzard Warning": {"category": "weather", "auto_send": True},
    "Winter Storm Warning": {"category": "weather", "auto_send": False},
    "Winter Weather Advisory": {"category": "weather", "auto_send": False},
    "Flood Warning": {"category": "weather", "auto_send": False},
    "Heat Advisory": {"category": "weather", "auto_send": False},
}


def _get_event_mappings() -> dict:
    if settings.nws_event_mappings:
        try:
            return json.loads(settings.nws_event_mappings)
        except json.JSONDecodeError:
            logger.warning("Invalid NWS event mappings JSON, using defaults")
    return DEFAULT_EVENT_MAPPINGS


async def _check_weather():
    zone = settings.nws_zone_id
    url = f"{NWS_API}/alerts/active/zone/{zone}"

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(url, headers={"User-Agent": "Quarry/1.0 (quarry@moravian.edu)"})
        resp.raise_for_status()
        data = resp.json()

    features = data.get("features", [])
    mappings = _get_event_mappings()

    for feature in features:
        props = feature.get("properties", {})
        event_id = props.get("id", "")
        event_type = props.get("event", "")

        if event_id in _seen_event_ids:
            continue

        _seen_event_ids.add(event_id)

        mapping = mappings.get(event_type)
        if not mapping or not mapping.get("auto_send"):
            continue

        category = mapping.get("category", "weather")
        headline = props.get("headline", event_type)
        description = props.get("description", "")
        instruction = props.get("instruction", "")

        body = f"{description}\n\n{instruction}".strip() if instruction else description
        sms_body = headline[:300] if headline else event_type

        logger.info("Auto-triggering weather alert: %s (%s)", headline, event_id)

        async with async_session() as db:
            async with db.begin():
                template_id = mapping.get("template_id")
                if template_id:
                    from sqlalchemy import select
                    tmpl = await db.get(AlertTemplate, uuid.UUID(template_id))
                    if tmpl:
                        body = tmpl.body_text.replace("{{headline}}", headline).replace("{{description}}", description)
                        sms_body = tmpl.body_sms.replace("{{headline}}", headline) if tmpl.body_sms else sms_body

                log_entry = AlertLog(
                    category=category,
                    subject=f"Weather Alert: {headline}",
                    body_text=body,
                    body_sms=sms_body,
                    sent_by="weather-auto",
                    status="active",
                )
                db.add(log_entry)
                await db.flush()
                await db.refresh(log_entry)

                await dispatch_alert(log_entry.id, db)
                logger.info("Weather alert dispatched: %s", log_entry.id)


async def _poll_loop():
    interval = settings.nws_poll_interval_seconds
    logger.info("Weather monitor started (zone=%s, interval=%ds)", settings.nws_zone_id, interval)
    while True:
        try:
            await _check_weather()
        except Exception as e:
            logger.error("Weather check failed: %s", e, exc_info=True)
        await asyncio.sleep(interval)


def start_weather_monitor():
    global _task
    if not settings.nws_alerts_enabled:
        logger.info("Weather monitor disabled")
        return
    if _task is None or _task.done():
        _task = asyncio.create_task(_poll_loop())
        logger.info("Weather monitor task created")


def stop_weather_monitor():
    global _task
    if _task and not _task.done():
        _task.cancel()
        _task = None


def get_seen_events() -> set[str]:
    return _seen_event_ids.copy()
