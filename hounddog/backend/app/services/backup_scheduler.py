"""
Scheduled backup processor.

Runs inside the existing closure_scheduler loop every 60s.
Checks the schedule config from the database (with disk fallback) and creates
a JSON backup file when due. Also handles retention cleanup of old backup files.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text, inspect as sa_inspect

from ..database import engine, async_session

logger = logging.getLogger("quarry.backup_scheduler")

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "backups"
SCHEDULE_FILE = BACKUP_DIR / "_schedule.json"
SKIP_TABLES = {"alembic_version"}

FREQUENCY_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}


def _serialise(value):
    from datetime import date as _date
    from decimal import Decimal
    from uuid import UUID as _UUID
    if isinstance(value, (datetime, _date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, _UUID):
        return str(value)
    return value


async def _read_schedule_from_db() -> dict | None:
    """Try reading backup schedule from the app_config table."""
    try:
        async with async_session() as db:
            result = await db.execute(
                text("SELECT value FROM app_config WHERE key = 'backup_schedule'")
            )
            row = result.scalar()
            if row:
                return row if isinstance(row, dict) else json.loads(row)
    except Exception:
        pass
    return None


def _read_schedule_from_disk() -> dict:
    """Fallback: read from disk file."""
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return {"enabled": False}


async def _read_schedule() -> dict:
    """Read schedule from DB first, fall back to disk."""
    db_config = await _read_schedule_from_db()
    if db_config is not None:
        return db_config
    return _read_schedule_from_disk()


async def _write_schedule(data: dict):
    """Write schedule to both DB and disk."""
    try:
        value_str = json.dumps(data)
        async with async_session() as db:
            await db.execute(text("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES ('backup_schedule', :val::jsonb, now())
                ON CONFLICT (key) DO UPDATE SET value = :val::jsonb, updated_at = now()
            """), {"val": value_str})
            await db.commit()
    except Exception as e:
        logger.warning("Failed to write schedule to DB: %s", e)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(data, indent=2))


def _compute_next_run(frequency: str, time_str: str, from_dt: datetime | None = None) -> datetime:
    """Compute the next run datetime based on frequency and time (HH:MM Eastern)."""
    from .timeutils import campus_tz, now_local
    tz = campus_tz()
    now = from_dt.astimezone(tz) if from_dt else now_local()
    parts = time_str.split(":")
    hour = int(parts[0]) if len(parts) > 0 else 2
    minute = int(parts[1]) if len(parts) > 1 else 0

    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return candidate


async def _create_backup_file() -> str:
    """Create a backup JSON file on disk and return the filename."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = sa_inspect(sync_conn)
            return insp.get_table_names()
        table_names = await conn.run_sync(_inspect)

    tables = sorted(n for n in table_names if n not in SKIP_TABLES)

    async with engine.connect() as conn:
        payload: dict[str, list[dict]] = {}
        for tbl in tables:
            result = await conn.execute(text(f'SELECT * FROM "{tbl}"'))
            columns = list(result.keys())
            rows = []
            for row in result.fetchall():
                rows.append({col: _serialise(row[i]) for i, col in enumerate(columns)})
            payload[tbl] = rows

    backup = {
        "format": "quarry_backup_v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": "scheduled",
        "tables": payload,
    }

    filename = f"quarry_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    filepath = BACKUP_DIR / filename
    filepath.write_text(json.dumps(backup, indent=2, default=str))
    logger.info("Scheduled backup created: %s (%.1f KB)", filename, filepath.stat().st_size / 1024)
    return filename


def _cleanup_old_backups(retention_days: int):
    """Delete backup files older than retention_days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for f in BACKUP_DIR.glob("quarry_backup_*.json"):
        try:
            mtime = datetime.utcfromtimestamp(f.stat().st_mtime).replace(tzinfo=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                logger.info("Deleted old backup: %s", f.name)
        except Exception as e:
            logger.warning("Failed to delete old backup %s: %s", f.name, e)


async def process_scheduled_backups():
    """Check if a scheduled backup is due and execute it."""
    config = await _read_schedule()
    if not config.get("enabled"):
        return

    frequency = config.get("frequency", "daily")
    time_str = config.get("time", "02:00")
    retention = config.get("retention_days", 30)
    next_run_str = config.get("next_run")

    now = datetime.now(timezone.utc)

    if next_run_str:
        try:
            next_run = datetime.fromisoformat(next_run_str)
            if next_run.tzinfo is None:
                from .timeutils import campus_tz
                next_run = next_run.replace(tzinfo=campus_tz())
        except (ValueError, TypeError):
            next_run = _compute_next_run(frequency, time_str)
    else:
        next_run = _compute_next_run(frequency, time_str)
        config["next_run"] = next_run.isoformat()
        await _write_schedule(config)
        return

    if now < next_run:
        return

    try:
        filename = await _create_backup_file()
        config["last_run"] = now.isoformat()
        config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
        await _write_schedule(config)

        drive_folder_id = config.get("google_drive_folder_id")
        if drive_folder_id:
            filepath = BACKUP_DIR / filename
            try:
                from .google_drive import upload_to_drive
                file_id = upload_to_drive(filepath, drive_folder_id)
                if file_id:
                    config["last_drive_upload"] = now.isoformat()
                    config["last_drive_file_id"] = file_id
                    await _write_schedule(config)
                    logger.info("Backup uploaded to Google Drive: %s", file_id)
                else:
                    logger.warning("Google Drive upload returned no file ID")
            except Exception as e:
                logger.error("Google Drive upload failed (backup still saved locally): %s", e)

        _cleanup_old_backups(retention)
    except Exception as e:
        logger.error("Scheduled backup failed: %s", e, exc_info=True)
