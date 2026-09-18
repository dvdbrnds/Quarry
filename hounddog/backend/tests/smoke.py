"""
Smoke tests for the logic that keeps breaking.
Run manually: python -m tests.smoke (from backend/)
No frameworks. No fixtures. Just assertions on pure functions.

These cover the areas with the most rework commits:
- After-hours access logic (8 rework commits)
- Lot name normalization (4 rework commits)
- Lot assignment parsing and formatting

Add tests here when you fix a bug in any of these areas.
"""

import sys
from datetime import time


def test_after_hours_access():
    """
    After-hours access was reimplemented 8 times.
    These assertions encode the rules from BUSINESS_RULES.md.
    """
    from app.services.access import check_lot_access

    # --- FSC (Commuter Evening) ---
    # Before 4 PM weekday: only faculty_staff and visitors
    assert not check_lot_access("commuter_undergrad", "FSC", time(15, 59), day_of_week=0), \
        "Commuter should NOT have FSC access at 3:59 PM weekday"
    assert check_lot_access("faculty_staff", "FSC", time(15, 59), day_of_week=0), \
        "Faculty/staff SHOULD have FSC access at 3:59 PM weekday"

    # At exactly 4 PM weekday: all permit holders
    assert check_lot_access("commuter_undergrad", "FSC", time(16, 0), day_of_week=0), \
        "Commuter SHOULD have FSC access at 4:00 PM weekday"

    # Midnight weekday: falls in 16:00-07:00 overnight range
    assert check_lot_access("commuter_undergrad", "FSC", time(0, 0), day_of_week=0), \
        "Commuter SHOULD have FSC access at midnight weekday"

    # Weekend: all day access for everyone
    assert check_lot_access("commuter_undergrad", "FSC", time(10, 0), day_of_week=5), \
        "Commuter SHOULD have FSC access on Saturday morning"

    # --- C/PC (Commuter Lots) ---
    # Before 4 PM weekday: commuters + faculty + visitors
    assert check_lot_access("commuter_undergrad", "C", time(10, 0), day_of_week=1), \
        "Commuter SHOULD have C access at 10 AM weekday"
    assert check_lot_access("faculty_staff", "C", time(10, 0), day_of_week=1), \
        "Faculty SHOULD have C access at 10 AM weekday"

    # Residents don't have access to commuter lots during daytime
    assert not check_lot_access("north_premium_resident", "C", time(10, 0), day_of_week=1), \
        "Resident should NOT have C access at 10 AM weekday"

    # After 4 PM: residents DO have access
    assert check_lot_access("north_premium_resident", "C", time(18, 0), day_of_week=1), \
        "Resident SHOULD have C access at 6 PM weekday"

    # --- RS/PR (Resident Lots) ---
    # Commuters don't have daytime access to resident lots
    assert not check_lot_access("commuter_undergrad", "RS", time(10, 0), day_of_week=2), \
        "Commuter should NOT have RS access at 10 AM weekday"
    assert check_lot_access("north_premium_resident", "RS", time(10, 0), day_of_week=2), \
        "Resident SHOULD have RS access at 10 AM weekday"

    # After 4 PM: commuters DO have access
    assert check_lot_access("commuter_undergrad", "RS", time(18, 0), day_of_week=2), \
        "Commuter SHOULD have RS access at 6 PM weekday"

    # Unknown designation: unrestricted
    assert check_lot_access("commuter_undergrad", "UNKNOWN", time(10, 0)), \
        "Unknown designation should be unrestricted"

    print("  pass: after-hours access")


def test_lot_normalization():
    """
    Lot name normalization broke 4 times because of inconsistent
    prefix handling ("Lot M" vs "M" vs "lot m").
    """
    from app.services.lot_assignment import lot_filter_variants

    # "Lot M" should produce both "Lot M" and "M"
    variants = lot_filter_variants("Lot M")
    assert "Lot M" in variants
    assert "M" in variants

    # "M" should just produce "M"
    variants = lot_filter_variants("M")
    assert "M" in variants

    # "lot m" (lowercase) should strip prefix
    variants = lot_filter_variants("lot m")
    assert "lot m" in variants
    assert "m" in variants

    # "FSC" should stay as-is (no "Lot" prefix)
    variants = lot_filter_variants("FSC")
    assert "FSC" in variants

    # Empty string
    assert lot_filter_variants("") == []
    assert lot_filter_variants(None) == []

    print("  pass: lot normalization")


def test_lot_assignment_parsing():
    """
    Lot assignment parsing and formatting.
    """
    from app.services.lot_assignment import (
        parse_lot_assignment,
        format_lot_assignment,
        effective_lot_assignment,
    )

    # CSV string parsing
    assert parse_lot_assignment("Lot M, FSC, Lot G") == ["Lot M", "FSC", "Lot G"]

    # Deduplication (case-insensitive)
    assert parse_lot_assignment("Lot M, lot m, FSC") == ["Lot M", "FSC"]

    # List input
    assert parse_lot_assignment(["Lot M", "FSC"]) == ["Lot M", "FSC"]

    # None / empty
    assert parse_lot_assignment(None) == []
    assert parse_lot_assignment("") == []

    # Formatting
    assert format_lot_assignment("Lot M, FSC") == "Lot M, FSC"

    # Effective: custom overrides type defaults
    assert effective_lot_assignment("Lot M", "FSC, Lot G") == "Lot M"
    assert effective_lot_assignment(None, "FSC, Lot G") == "FSC, Lot G"
    assert effective_lot_assignment("", "FSC, Lot G") == "FSC, Lot G"

    print("  pass: lot assignment parsing")


if __name__ == "__main__":
    print("Running smoke tests...\n")
    passed = 0
    failed = 0

    for name, func in sorted(globals().items()):
        if name.startswith("test_") and callable(func):
            try:
                func()
                passed += 1
            except Exception as e:
                print(f"  FAIL: {name}: {e}")
                failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
