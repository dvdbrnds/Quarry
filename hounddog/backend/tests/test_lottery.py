"""Unit tests for the lottery engine strategies and helpers.

Loads the lottery module with stubbed-out SQLAlchemy dependencies so
tests can run without a database or heavy framework imports.
"""

import importlib.util
import os
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Stub out the ORM model import the lottery module needs ──

_fake_permit_app = types.ModuleType("app.models.permit_application")


class _PermitApplication:
    pass


_fake_permit_app.PermitApplication = _PermitApplication

_pkg_tree = {
    "app": [],
    "app.models": [],
    "app.models.permit_application": None,
    "app.services": [],
    "app.services.lottery": None,
}
for name, path in _pkg_tree.items():
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if path is not None:
            mod.__path__ = path
        sys.modules[name] = mod

sys.modules["app.models.permit_application"] = _fake_permit_app

# ── Load lottery.py directly by file path ──

_lottery_path = Path(__file__).resolve().parent.parent / "app" / "services" / "lottery.py"
_spec = importlib.util.spec_from_file_location("app.services.lottery", _lottery_path)
_lottery = importlib.util.module_from_spec(_spec)
sys.modules["app.services.lottery"] = _lottery
_spec.loader.exec_module(_lottery)

SeniorityWeightedStrategy = _lottery.SeniorityWeightedStrategy
PureRandomStrategy = _lottery.PureRandomStrategy
ClassPriorityStrategy = _lottery.ClassPriorityStrategy
SeniorityTimestampStrategy = _lottery.SeniorityTimestampStrategy
get_strategy = _lottery.get_strategy
assign_lots = _lottery.assign_lots
distribute_capacity = _lottery.distribute_capacity


class FakeApp:
    """Lightweight stand-in for PermitApplication."""

    def __init__(self, class_year: int, created_at: datetime | None = None, lot_preferences: list[str] | None = None):
        self.id = uuid.uuid4()
        self.class_year = class_year
        self.created_at = created_at or datetime.now(timezone.utc)
        self.lot_preferences = lot_preferences or []
        self.assigned_lot = None


def _make_apps(years: list[int]) -> list[FakeApp]:
    return [
        FakeApp(y, created_at=datetime(2026, 1, 1, i, tzinfo=timezone.utc))
        for i, y in enumerate(years)
    ]


# ── PureRandomStrategy ──


class TestPureRandom:
    def test_correct_counts(self):
        apps = _make_apps([2027, 2028, 2029, 2030, 2026])
        s = PureRandomStrategy()
        selected, waitlisted = s.rank(apps, 3, seed="test-seed")
        assert len(selected) == 3
        assert len(waitlisted) == 2
        assert set(a.id for a in selected + waitlisted) == set(a.id for a in apps)

    def test_same_seed_same_result(self):
        apps = _make_apps([2027, 2028, 2029, 2030, 2026])
        s = PureRandomStrategy()
        sel1, wl1 = s.rank(apps, 3, seed="deterministic")
        sel2, wl2 = s.rank(apps, 3, seed="deterministic")
        assert [a.id for a in sel1] == [a.id for a in sel2]
        assert [a.id for a in wl1] == [a.id for a in wl2]

    def test_different_seed_different_result(self):
        apps = _make_apps([2027, 2028, 2029, 2030, 2026, 2025, 2024])
        s = PureRandomStrategy()
        sel1, _ = s.rank(apps, 3, seed="seed-a")
        sel2, _ = s.rank(apps, 3, seed="seed-b")
        assert [a.id for a in sel1] != [a.id for a in sel2]

    def test_empty_applications(self):
        s = PureRandomStrategy()
        selected, waitlisted = s.rank([], 5, seed="x")
        assert selected == []
        assert waitlisted == []

    def test_more_spots_than_applicants(self):
        apps = _make_apps([2027, 2028])
        s = PureRandomStrategy()
        selected, waitlisted = s.rank(apps, 10, seed="x")
        assert len(selected) == 2
        assert len(waitlisted) == 0


# ── SeniorityWeightedStrategy ──


class TestSeniorityWeighted:
    def test_correct_counts(self):
        apps = _make_apps([2027, 2028, 2029, 2030])
        s = SeniorityWeightedStrategy()
        selected, waitlisted = s.rank(apps, 2, seed="test")
        assert len(selected) == 2
        assert len(waitlisted) == 2

    def test_seeded_determinism(self):
        apps = _make_apps([2027, 2028, 2029, 2030])
        s = SeniorityWeightedStrategy()
        sel1, _ = s.rank(apps, 2, seed="fixed")
        sel2, _ = s.rank(apps, 2, seed="fixed")
        assert [a.id for a in sel1] == [a.id for a in sel2]

    def test_different_seeds(self):
        apps = _make_apps([2025, 2026, 2027, 2028, 2029, 2030, 2031])
        s = SeniorityWeightedStrategy()
        sel1, _ = s.rank(apps, 3, seed="aaa")
        sel2, _ = s.rank(apps, 3, seed="bbb")
        assert [a.id for a in sel1] != [a.id for a in sel2]

    def test_empty(self):
        s = SeniorityWeightedStrategy()
        selected, waitlisted = s.rank([], 5, seed="x")
        assert selected == []
        assert waitlisted == []


# ── ClassPriorityStrategy ──


class TestClassPriority:
    def test_seniors_first(self):
        apps = _make_apps([2030, 2028, 2026, 2029, 2027])
        s = ClassPriorityStrategy()
        selected, waitlisted = s.rank(apps, 3, seed="test")
        selected_years = sorted(a.class_year for a in selected)
        assert selected_years == [2026, 2027, 2028]

    def test_seeded_within_tier(self):
        apps = _make_apps([2027, 2027, 2027, 2027, 2028])
        s = ClassPriorityStrategy()
        sel1, _ = s.rank(apps, 2, seed="same-seed")
        sel2, _ = s.rank(apps, 2, seed="same-seed")
        assert [a.id for a in sel1] == [a.id for a in sel2]

    def test_correct_counts(self):
        apps = _make_apps([2027, 2028, 2029])
        s = ClassPriorityStrategy()
        selected, waitlisted = s.rank(apps, 2, seed="x")
        assert len(selected) == 2
        assert len(waitlisted) == 1


# ── SeniorityTimestampStrategy ──


class TestSeniorityTimestamp:
    def test_deterministic_ordering(self):
        apps = _make_apps([2028, 2026, 2027, 2026])
        s = SeniorityTimestampStrategy()
        selected, waitlisted = s.rank(apps, 2)
        assert selected[0].class_year == 2026
        assert selected[1].class_year == 2026
        assert selected[0].created_at <= selected[1].created_at

    def test_seed_ignored_but_accepted(self):
        apps = _make_apps([2028, 2027, 2026])
        s = SeniorityTimestampStrategy()
        sel1, _ = s.rank(apps, 2, seed="a")
        sel2, _ = s.rank(apps, 2, seed="b")
        assert [a.id for a in sel1] == [a.id for a in sel2]


# ── get_strategy fallback ──


class TestGetStrategy:
    def test_known_strategies(self):
        assert isinstance(get_strategy("pure_random"), PureRandomStrategy)
        assert isinstance(get_strategy("seniority_weighted"), SeniorityWeightedStrategy)
        assert isinstance(get_strategy("class_priority"), ClassPriorityStrategy)
        assert isinstance(get_strategy("seniority_timestamp"), SeniorityTimestampStrategy)

    def test_fallback_to_seniority_timestamp(self):
        fallback = get_strategy("nonexistent_strategy")
        assert isinstance(fallback, SeniorityTimestampStrategy)

    def test_empty_string_fallback(self):
        fallback = get_strategy("")
        assert isinstance(fallback, SeniorityTimestampStrategy)


# ── distribute_capacity ──


class TestDistributeCapacity:
    def test_even_split(self):
        result = distribute_capacity(100, ["A", "B", "C", "D"])
        assert result == {"A": 25, "B": 25, "C": 25, "D": 25}

    def test_remainder_distribution(self):
        result = distribute_capacity(10, ["A", "B", "C"])
        assert result == {"A": 4, "B": 3, "C": 3}
        assert sum(result.values()) == 10

    def test_single_lot(self):
        result = distribute_capacity(57, ["X"])
        assert result == {"X": 57}

    def test_more_lots_than_capacity(self):
        result = distribute_capacity(2, ["A", "B", "C", "D", "E"])
        assert sum(result.values()) == 2
        assert result["A"] == 1
        assert result["B"] == 1
        assert result["C"] == 0


# ── assign_lots ──


class TestAssignLots:
    def test_respects_preferences(self):
        apps = [FakeApp(2027, lot_preferences=["B", "A"]), FakeApp(2028, lot_preferences=["A", "B"])]
        caps = {"A": 5, "B": 5}
        warnings = assign_lots(apps, caps)
        assert warnings == []
        assert apps[0].assigned_lot == "B"
        assert apps[1].assigned_lot == "A"

    def test_respects_capacity(self):
        apps = [FakeApp(2027, lot_preferences=["A"]), FakeApp(2028, lot_preferences=["A"]), FakeApp(2029, lot_preferences=["A"])]
        caps = {"A": 2, "B": 5}
        warnings = assign_lots(apps, caps)
        assert warnings == []
        assert apps[0].assigned_lot == "A"
        assert apps[1].assigned_lot == "A"
        assert apps[2].assigned_lot == "B"

    def test_overflow_warning(self):
        apps = [FakeApp(2027), FakeApp(2028)]
        caps = {"A": 1}
        warnings = assign_lots(apps, caps)
        assert len(warnings) == 1
        assert "could not be assigned" in warnings[0]
        assert apps[0].assigned_lot == "A"
        assert apps[1].assigned_lot == "A"

    def test_no_preferences_uses_lot_order(self):
        apps = [FakeApp(2027), FakeApp(2028)]
        caps = {"X": 1, "Y": 1}
        warnings = assign_lots(apps, caps)
        assert warnings == []
        assert apps[0].assigned_lot == "X"
        assert apps[1].assigned_lot == "Y"

    def test_empty_selected(self):
        warnings = assign_lots([], {"A": 5})
        assert warnings == []
