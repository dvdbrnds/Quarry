"""Unit tests for Lottery V2 waterfall placement.

Loads lottery_v2_runner pure functions with stubbed heavy imports.
"""

import importlib.util
import sys
import types
import uuid
from datetime import datetime, timezone
from pathlib import Path

# ── Stub packages so we can load the runner without full app deps ──

_stubs = [
    "app",
    "app.config",
    "app.models",
    "app.models.lottery_v2",
    "app.models.permit",
    "app.models.permit_type",
    "app.services",
    "app.services.email",
    "app.services.lottery",
    "sqlalchemy",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
]

for name in _stubs:
    if name not in sys.modules:
        mod = types.ModuleType(name)
        if name in ("app", "app.models", "app.services", "sqlalchemy", "sqlalchemy.ext"):
            mod.__path__ = []
        sys.modules[name] = mod

# sqlalchemy surface used at import time
_sa = sys.modules["sqlalchemy"]
_sa.func = types.SimpleNamespace()
_sa.select = lambda *a, **k: None
_sa.text = lambda *a, **k: None
sys.modules["sqlalchemy.ext.asyncio"].AsyncSession = type("AsyncSession", (), {})

# Minimal config
_cfg = sys.modules["app.config"]
_cfg.settings = types.SimpleNamespace(
    school_name="Test U",
    brand_primary_color="#000",
    student_facing_url="http://localhost",
)

# lottery helpers used by runner
_lottery = types.ModuleType("app.services.lottery")


def distribute_capacity(total, lot_names):
    if not lot_names:
        return {}
    base = total // len(lot_names)
    rem = total % len(lot_names)
    return {n: base + (1 if i < rem else 0) for i, n in enumerate(lot_names)}


_lottery.distribute_capacity = distribute_capacity
sys.modules["app.services.lottery"] = _lottery

# email stubs
_email = sys.modules["app.services.email"]


async def _noop(*_a, **_k):
    return None


_email.send_email = _noop
_email.send_lottery_selection_email = _noop
_email.branded_email_shell = _noop
_email.extract_first_name = lambda n: (n or "Student").split()[0]
_email.get_department_name = _noop

# model stubs (not used by pure functions)
sys.modules["app.models.lottery_v2"].LotteryV2Application = type("LotteryV2Application", (), {})
sys.modules["app.models.lottery_v2"].LotteryV2AuditLog = type("LotteryV2AuditLog", (), {})
sys.modules["app.models.lottery_v2"].LotteryV2Cycle = type("LotteryV2Cycle", (), {})
sys.modules["app.models.permit"].Permit = type("Permit", (), {})
sys.modules["app.models.permit_type"].PermitType = type("PermitType", (), {})

_path = Path(__file__).resolve().parent.parent / "app" / "services" / "lottery_v2_runner.py"
_spec = importlib.util.spec_from_file_location("app.services.lottery_v2_runner", _path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.services.lottery_v2_runner"] = _mod
_spec.loader.exec_module(_mod)

waterfall_place = _mod.waterfall_place
try_place_one = _mod.try_place_one
TierCapacity = _mod.TierCapacity
WaterfallApplicant = _mod.WaterfallApplicant


def _ts(minute: int) -> datetime:
    return datetime(2026, 3, 1, 12, minute, tzinfo=timezone.utc)


def _tier(spots: int, lots: list[str] | None = None) -> TierCapacity:
    ptid = uuid.uuid4()
    lots = lots or ["A", "B"]
    caps = distribute_capacity(spots, lots)
    return TierCapacity(
        permit_type_id=ptid,
        code="test",
        label="Test",
        price=100,
        remaining=spots,
        lot_order=lots,
        lot_remaining=dict(caps),
    )


class TestWaterfallPlace:
    def test_senior_gets_first_choice(self):
        t_premium = _tier(1, ["I"])
        t_guaranteed = _tier(5, ["B", "C"])
        tiers = {
            t_premium.permit_type_id: t_premium,
            t_guaranteed.permit_type_id: t_guaranteed,
        }
        senior = WaterfallApplicant(
            id="senior",
            class_year=2026,
            created_at=_ts(10),
            tier_preferences=[t_premium.permit_type_id, t_guaranteed.permit_type_id],
        )
        junior = WaterfallApplicant(
            id="junior",
            class_year=2027,
            created_at=_ts(1),
            tier_preferences=[t_premium.permit_type_id, t_guaranteed.permit_type_id],
        )
        selected, waitlisted, _ = waterfall_place([junior, senior], tiers)
        assert len(selected) == 2
        assert len(waitlisted) == 0
        by_id = {p.app_id: p for p in selected}
        assert by_id["senior"].assigned_permit_type_id == t_premium.permit_type_id
        assert by_id["junior"].assigned_permit_type_id == t_guaranteed.permit_type_id
        assert by_id["senior"].lottery_rank == 1
        assert by_id["junior"].lottery_rank == 2

    def test_cascades_to_second_tier_when_full(self):
        t1 = _tier(1, ["Z"])
        t2 = _tier(2, ["U"])
        tiers = {t1.permit_type_id: t1, t2.permit_type_id: t2}
        a = WaterfallApplicant("a", 2026, _ts(1), [t1.permit_type_id, t2.permit_type_id])
        b = WaterfallApplicant("b", 2026, _ts(2), [t1.permit_type_id, t2.permit_type_id])
        selected, waitlisted, _ = waterfall_place([a, b], tiers)
        assert len(selected) == 2
        assert len(waitlisted) == 0
        by_id = {p.app_id: p for p in selected}
        assert by_id["a"].assigned_permit_type_id == t1.permit_type_id
        assert by_id["b"].assigned_permit_type_id == t2.permit_type_id

    def test_waitlist_when_all_tiers_full(self):
        t1 = _tier(1, ["I"])
        tiers = {t1.permit_type_id: t1}
        apps = [
            WaterfallApplicant("a", 2026, _ts(1), [t1.permit_type_id]),
            WaterfallApplicant("b", 2026, _ts(2), [t1.permit_type_id]),
            WaterfallApplicant("c", 2027, _ts(3), [t1.permit_type_id]),
        ]
        selected, waitlisted, _ = waterfall_place(apps, tiers)
        assert len(selected) == 1
        assert selected[0].app_id == "a"
        assert len(waitlisted) == 2
        assert waitlisted[0].waitlist_position == 1
        assert waitlisted[1].waitlist_position == 2

    def test_timestamp_tiebreak_within_class_year(self):
        t1 = _tier(1, ["Q"])
        tiers = {t1.permit_type_id: t1}
        late = WaterfallApplicant("late", 2026, _ts(30), [t1.permit_type_id])
        early = WaterfallApplicant("early", 2026, _ts(5), [t1.permit_type_id])
        selected, waitlisted, _ = waterfall_place([late, early], tiers)
        assert selected[0].app_id == "early"
        assert waitlisted[0].app_id == "late"

    def test_assigns_lot_within_tier(self):
        t1 = _tier(3, ["B", "C", "D"])
        tiers = {t1.permit_type_id: t1}
        apps = [
            WaterfallApplicant(f"s{i}", 2026, _ts(i), [t1.permit_type_id])
            for i in range(3)
        ]
        selected, waitlisted, _ = waterfall_place(apps, tiers)
        assert len(selected) == 3
        assert len(waitlisted) == 0
        lots = {p.assigned_lot for p in selected}
        assert lots <= {"B", "C", "D"}
        assert len(lots) >= 1

    def test_try_place_one_promotes_waitlisted(self):
        t1 = _tier(1, ["I"])
        tiers = {t1.permit_type_id: t1}
        app = WaterfallApplicant("w", 2027, _ts(1), [t1.permit_type_id])
        placement = try_place_one(app, tiers)
        assert placement is not None
        assert placement.status == "selected"
        assert placement.assigned_lot == "I"
        assert t1.remaining == 0
        assert try_place_one(app, tiers) is None
