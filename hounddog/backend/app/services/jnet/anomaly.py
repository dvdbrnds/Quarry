"""
CJIS anomaly detection — AU-6(1).

Lightweight per-query checks run inline. Comprehensive analysis runs
as a periodic background task.
"""

import ipaddress
import uuid
from datetime import datetime, timezone, timedelta

import sentry_sdk
import structlog
from sqlalchemy import select, func, and_

from ...database import async_session
from ...models.cjis_audit_log import CJISAuditLog
from ...models.cjis_audit_alert import CJISAuditAlert
from .config import jnet_settings

logger = structlog.get_logger("quarry.cjis.anomaly")


def _parse_allowed_ip_ranges() -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Parse comma-separated CIDR list from config."""
    raw = jnet_settings.jnet_allowed_ip_ranges.strip()
    if not raw:
        return []
    networks = []
    for cidr in raw.split(","):
        cidr = cidr.strip()
        if cidr:
            try:
                networks.append(ipaddress.ip_network(cidr, strict=False))
            except ValueError:
                logger.warning("invalid_cidr_in_config", cidr=cidr)
    return networks


def _ip_in_allowed_ranges(ip: str, networks: list) -> bool:
    """Check if an IP is within the allowed campus ranges."""
    if not networks:
        return True
    try:
        addr = ipaddress.ip_address(ip)
        return any(addr in net for net in networks)
    except ValueError:
        return False


async def _create_alert(
    audit_log_id: uuid.UUID | None,
    alert_type: str,
    description: str,
) -> None:
    """Create a CJIS audit alert. Never raises."""
    try:
        async with async_session() as session:
            async with session.begin():
                session.add(CJISAuditAlert(
                    audit_log_id=audit_log_id,
                    alert_type=alert_type,
                    description=description,
                ))
        logger.warning("cjis_alert_created", alert_type=alert_type, description=description)
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("cjis_alert_creation_failed", error=str(exc))


async def check_query_anomalies(
    *,
    audit_log_id: uuid.UUID,
    user_id: uuid.UUID,
    user_email: str,
    query_plate: str,
    source_ip: str,
) -> None:
    """
    Lightweight per-query anomaly checks. Run after every JNET query.
    Never raises — failures are logged.
    """
    try:
        now = datetime.now(timezone.utc)

        # 1. Same plate queried too many times in 24 hours
        threshold = jnet_settings.jnet_max_same_plate_queries_24h
        cutoff_24h = now - timedelta(hours=24)

        async with async_session() as session:
            same_plate_count = (
                await session.execute(
                    select(func.count()).where(
                        and_(
                            CJISAuditLog.user_id == user_id,
                            CJISAuditLog.query_plate == query_plate,
                            CJISAuditLog.timestamp >= cutoff_24h,
                        )
                    )
                )
            ).scalar() or 0

        if same_plate_count > threshold:
            await _create_alert(
                audit_log_id=audit_log_id,
                alert_type="repeated_plate_query",
                description=(
                    f"Officer {user_email} queried plate {query_plate} "
                    f"{same_plate_count} times in 24 hours (threshold: {threshold})."
                ),
            )

        # 2. Query outside configured shift hours
        local_hour = now.hour
        if not (jnet_settings.jnet_shift_start_hour <= local_hour < jnet_settings.jnet_shift_end_hour):
            await _create_alert(
                audit_log_id=audit_log_id,
                alert_type="off_hours_query",
                description=(
                    f"Officer {user_email} performed JNET query at {now.strftime('%H:%M')} UTC, "
                    f"outside configured shift hours "
                    f"({jnet_settings.jnet_shift_start_hour}:00–{jnet_settings.jnet_shift_end_hour}:00)."
                ),
            )

        # 3. Query from outside allowed IP ranges
        networks = _parse_allowed_ip_ranges()
        if networks and not _ip_in_allowed_ranges(source_ip, networks):
            await _create_alert(
                audit_log_id=audit_log_id,
                alert_type="outside_network_query",
                description=(
                    f"Officer {user_email} performed JNET query from IP {source_ip}, "
                    f"outside allowed campus network ranges."
                ),
            )
            # This is a critical anomaly — also trigger incident
            from .incident import report_cjis_incident
            await report_cjis_incident(
                incident_type="policy_violation",
                description=(
                    f"JNET query from unauthorized IP {source_ip} by {user_email}."
                ),
                affected_records=1,
                detected_by="anomaly_detection",
            )

    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("cjis_anomaly_check_failed", error=str(exc))


async def run_comprehensive_anomaly_scan() -> None:
    """
    Background task: comprehensive anomaly analysis.

    Checks officer query volume against 30-day average (2 std dev threshold).
    """
    try:
        now = datetime.now(timezone.utc)
        thirty_days_ago = now - timedelta(days=30)
        one_day_ago = now - timedelta(days=1)

        async with async_session() as session:
            # Get daily query counts per user for the last 30 days
            daily_counts = (
                await session.execute(
                    select(
                        CJISAuditLog.user_id,
                        CJISAuditLog.user_email,
                        func.date_trunc("day", CJISAuditLog.timestamp).label("day"),
                        func.count().label("count"),
                    )
                    .where(CJISAuditLog.timestamp >= thirty_days_ago)
                    .group_by(
                        CJISAuditLog.user_id,
                        CJISAuditLog.user_email,
                        func.date_trunc("day", CJISAuditLog.timestamp),
                    )
                )
            ).all()

        # Group by user
        user_daily: dict[str, list[int]] = {}
        user_emails: dict[str, str] = {}
        for row in daily_counts:
            uid = str(row.user_id)
            user_daily.setdefault(uid, []).append(row.count)
            user_emails[uid] = row.user_email

        # Check each user's today count vs their 30-day stats
        import statistics

        for uid, counts in user_daily.items():
            if len(counts) < 7:
                continue

            mean = statistics.mean(counts)
            stdev = statistics.stdev(counts) if len(counts) > 1 else 0

            if stdev == 0:
                continue

            today_count = counts[-1] if counts else 0
            threshold = mean + (2 * stdev)

            if today_count > threshold:
                await _create_alert(
                    audit_log_id=None,
                    alert_type="volume_anomaly",
                    description=(
                        f"Officer {user_emails[uid]} made {today_count} JNET queries today, "
                        f"exceeding 2 standard deviations from their 30-day average "
                        f"(mean: {mean:.1f}, stdev: {stdev:.1f}, threshold: {threshold:.1f})."
                    ),
                )

        logger.info("cjis_comprehensive_anomaly_scan_complete")

    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.error("cjis_comprehensive_anomaly_scan_failed", error=str(exc))
