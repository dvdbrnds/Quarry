"""Unit tests for scheduled backup due-ness (slot-based, Eastern Time).

Loads backup_scheduler.py with stubbed SQLAlchemy/DB imports so tests
can run without a database or installed backend deps.
"""

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# ── Stub heavy imports the scheduler module needs at import time ──

_sqlalchemy = types.ModuleType("sqlalchemy")
_sqlalchemy.text = lambda *a, **k: None
_sqlalchemy.inspect = lambda *a, **k: None
sys.modules.setdefault("sqlalchemy", _sqlalchemy)

_database = types.ModuleType("app.database")
_database.engine = None
_database.async_session = None

_audit = types.ModuleType("app.models.audit_log")


class _AuditLog:
    pass


_audit.AuditLog = _AuditLog

_config = types.ModuleType("app.config")


class _Settings:
    app_timezone = "America/New_York"
    debug = False
    database_url = "postgresql+asyncpg://quarry:quarry@localhost:5432/quarry"


_config.settings = _Settings()

_app_dir = Path(__file__).resolve().parent.parent / "app"
_services_dir = _app_dir / "services"

for name, mod, path in [
    ("app", types.ModuleType("app"), [_app_dir]),
    ("app.models", types.ModuleType("app.models"), [_app_dir / "models"]),
    ("app.services", types.ModuleType("app.services"), [_services_dir]),
]:
    if name not in sys.modules:
        mod.__path__ = [str(p) for p in path]
        sys.modules[name] = mod

sys.modules["app.models.audit_log"] = _audit
sys.modules["app.database"] = _database
sys.modules["app.config"] = _config

_path = Path(__file__).resolve().parent.parent / "app" / "services" / "backup_scheduler.py"
_spec = importlib.util.spec_from_file_location("app.services.backup_scheduler", _path)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["app.services.backup_scheduler"] = _mod
_spec.loader.exec_module(_mod)

_compute_next_run = _mod._compute_next_run
_parse_hhmm = _mod._parse_hhmm
current_slot = _mod.current_slot
is_backup_due = _mod.is_backup_due

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _et(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=ET)


def test_parse_hhmm():
    assert _parse_hhmm("02:00") == (2, 0)
    assert _parse_hhmm("14:30") == (14, 30)
    assert _parse_hhmm("") == (2, 0)
    assert _parse_hhmm("25:99") == (23, 59)


def test_due_when_todays_2am_passed_and_no_scheduled_backup():
    """The production failure: enabled daily at 02:00, last auto backup days ago."""
    now = _et(2026, 8, 14, 10, 49)
    last = datetime(2026, 8, 8, 17, 12, tzinfo=UTC)
    assert is_backup_due("daily", "02:00", now, last) is True


def test_not_due_before_todays_slot_if_never_run():
    now = _et(2026, 8, 14, 1, 0)
    assert is_backup_due("daily", "02:00", now, None) is False


def test_due_after_todays_slot_if_never_run():
    now = _et(2026, 8, 14, 10, 49)
    assert is_backup_due("daily", "02:00", now, None) is True


def test_catchup_at_10am_does_not_skip_tomorrow_2am():
    catchup = _et(2026, 8, 14, 10, 49)
    assert is_backup_due("daily", "02:00", _et(2026, 8, 14, 11, 0), catchup) is False
    assert is_backup_due("daily", "02:00", _et(2026, 8, 15, 1, 59), catchup) is False
    assert is_backup_due("daily", "02:00", _et(2026, 8, 15, 2, 0), catchup) is True


def test_same_slot_not_due_again():
    ran_at_2am = _et(2026, 8, 14, 2, 1)
    assert is_backup_due("daily", "02:00", _et(2026, 8, 14, 10, 49), ran_at_2am) is False


def test_weekly_does_not_fire_every_day_after_a_run():
    last = _et(2026, 8, 6, 2, 0)
    assert is_backup_due("weekly", "02:00", _et(2026, 8, 10, 10, 0), last) is False
    assert is_backup_due("weekly", "02:00", _et(2026, 8, 13, 10, 0), last) is True


def test_current_slot_before_and_after_2am():
    before = current_slot("daily", "02:00", _et(2026, 8, 14, 1, 0))
    assert before == _et(2026, 8, 13, 2, 0)
    after = current_slot("daily", "02:00", _et(2026, 8, 14, 10, 49))
    assert after == _et(2026, 8, 14, 2, 0)


def test_compute_next_run_after_catchup_is_tomorrow_2am():
    nxt = _compute_next_run("daily", "02:00", _et(2026, 8, 14, 10, 49))
    assert nxt == _et(2026, 8, 15, 2, 0)
