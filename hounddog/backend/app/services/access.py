"""
Pure-function lot access checks — extracted for testability.

The schedule data lives in routers/lots.py (DESIGNATION_SCHEDULES).
This module imports it and provides a single function:
    check_lot_access(permit_type, designation, current_time, day_of_week) -> bool

See BUSINESS_RULES.md for the human-readable version of these rules.
"""

from datetime import time


# Import the canonical schedule data from the router module.
# These are plain dicts/lists with no DB or FastAPI dependencies.
from ..routers.lots import DESIGNATION_SCHEDULES


DAY_ABBREV = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat", 6: "sun",
}


def _time_in_range(start: time, end: time, t: time) -> bool:
    """Check if t falls within [start, end), handling overnight ranges."""
    if start <= end:
        return start <= t < end
    else:
        # Overnight range (e.g. 16:00 -> 07:00)
        return t >= start or t < end


def check_lot_access(
    permit_type: str,
    designation: str,
    current_time: time,
    day_of_week: int = 0,
) -> bool:
    """Return True if a permit_type has access to a lot with the given designation
    at current_time on day_of_week (0=Monday ... 6=Sunday).

    Rules:
      - If the designation has no schedule, access is unrestricted (True).
      - If a matching time rule has an empty allowed_permit_types list,
        ALL permit holders have access.
      - Otherwise, only the listed types have access during that window.
    """
    designation = (designation or "").upper().strip()
    permit_type = (permit_type or "").lower().strip()

    schedule_list = DESIGNATION_SCHEDULES.get(designation)
    if not schedule_list:
        return True  # no schedule = unrestricted

    day_str = DAY_ABBREV.get(day_of_week, "mon")

    for season_block in schedule_list:
        for rule in season_block.get("rules", []):
            days = rule.get("days", [])
            if day_str not in days:
                continue
            start = time.fromisoformat(rule["start"])
            end = time.fromisoformat(rule["end"])
            if not _time_in_range(start, end, current_time):
                continue
            # Found the matching time window
            allowed = rule.get("allowed_permit_types", [])
            if not allowed:
                return True  # empty list = all permit holders
            return permit_type in allowed

    # No matching rule found — default to unrestricted
    return True
