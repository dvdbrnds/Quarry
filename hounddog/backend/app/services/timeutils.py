"""Campus-local time helpers (Moravian = America/New_York).

Storage timestamps stay UTC. Business dates (permit start, "today")
and scheduled jobs use Eastern Time so evenings don't roll to the next day.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from ..config import settings

EASTERN = ZoneInfo("America/New_York")


def campus_tz() -> ZoneInfo:
    try:
        return ZoneInfo(settings.app_timezone or "America/New_York")
    except Exception:
        return EASTERN


def now_local() -> datetime:
    """Current time in the campus timezone."""
    return datetime.now(campus_tz())


def today_local() -> date:
    """Today's calendar date in the campus timezone (not UTC)."""
    return now_local().date()


def to_local(dt: datetime) -> datetime:
    """Convert a datetime to campus local time for display."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(campus_tz())
