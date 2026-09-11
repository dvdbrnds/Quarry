"""Ingest logs from BirdDog enforcement devices."""
import structlog
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from ..auth.okta import require_office
from ..logging_config import get_axiom_client
from ..config import settings

logger = structlog.get_logger("quarry.device_logs")
router = APIRouter()


class DeviceLogEntry(BaseModel):
    timestamp: datetime
    level: str = "info"
    event: str
    device_id: str
    officer_email: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    battery_pct: Optional[int] = None
    app_version: Optional[str] = None
    extra: Optional[dict] = None


class DeviceLogBatch(BaseModel):
    entries: list[DeviceLogEntry]


@router.post("", status_code=202)
async def ingest_device_logs(
    batch: DeviceLogBatch,
    _user=Depends(require_office),
):
    if not batch.entries:
        raise HTTPException(400, "Empty batch")
    if len(batch.entries) > 500:
        raise HTTPException(400, "Batch too large (max 500)")

    client = get_axiom_client()
    if not client:
        logger.warning("device_logs_dropped", count=len(batch.entries),
                       reason="axiom_not_configured")
        return {"accepted": 0, "reason": "logging not configured"}

    events = []
    for entry in batch.entries:
        ev = {
            "_time": entry.timestamp.isoformat(),
            "level": entry.level,
            "event": entry.event,
            "device_id": entry.device_id,
            "officer": entry.officer_email,
            "app_version": entry.app_version,
        }
        if entry.lat and entry.lon:
            ev["location"] = {"lat": entry.lat, "lon": entry.lon}
        if entry.battery_pct is not None:
            ev["battery_pct"] = entry.battery_pct
        if entry.extra:
            ev.update(entry.extra)
        events.append(ev)

    try:
        client.ingest_events(settings.axiom_device_dataset, events)
    except Exception as exc:
        logger.error("axiom_ingest_failed", dataset="birddog", error=str(exc))
        raise HTTPException(502, "Log shipping failed")

    logger.info("device_logs_ingested", count=len(events),
                device_id=batch.entries[0].device_id)
    return {"accepted": len(events)}
