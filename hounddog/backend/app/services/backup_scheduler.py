"""
Scheduled backup processor.

Runs inside the existing closure_scheduler loop every 60s.
Checks the schedule config from the database (with disk fallback) and creates
a JSON backup file when due. Also handles retention cleanup of old backup files.

SAFETY: A minimum interval of 1 hour is enforced between backups regardless
of config to prevent runaway backup loops from filling disk.
"""

import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import text, inspect as sa_inspect

from ..database import engine, async_session
from ..models.audit_log import AuditLog

logger = logging.getLogger("quarry.backup_scheduler")

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "backups"
MIN_BACKUP_INTERVAL = timedelta(hours=1)
MIN_FREE_DISK_GB = 2.0
MAX_KEEP_COUNT = 7


async def _audit(summary: str, action: str = "POST", details: dict | None = None):
    """Write a system-level audit entry visible in the Activity Log."""
    try:
        async with async_session() as db:
            async with db.begin():
                db.add(AuditLog(
                    user_email="system:backup_scheduler",
                    user_sub="system",
                    action=action,
                    resource_type="backup",
                    endpoint="/system/backup_scheduler",
                    summary=summary,
                    response_status=200,
                    changes=details,
                ))
    except Exception as e:
        logger.warning("Failed to write backup audit entry: %s", e)
SCHEDULE_FILE = BACKUP_DIR / "_schedule.json"
SKIP_TABLES = {"alembic_version", "backup_snapshots"}

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
                parsed = row if isinstance(row, dict) else json.loads(row)
                logger.debug("Backup schedule from DB: %s", parsed)
                return parsed
            else:
                logger.warning("Backup schedule: no row found in app_config for 'backup_schedule'")
    except Exception as e:
        logger.warning("Backup schedule: failed to read from DB: %s", e)
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


async def _create_backup_payload() -> tuple[str, str, dict]:
    """Build a backup JSON payload. Returns (filename, json_text, backup_dict)."""
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
    content = json.dumps(backup, indent=2, default=str)
    return filename, content, backup


async def _persist_backup(filename: str, content: str, source: str = "scheduled") -> str:
    """Store backup in Postgres (survives redeploys) and mirror to disk for Drive upload."""
    size = len(content.encode("utf-8"))

    async with async_session() as db:
        await db.execute(
            text("""
                INSERT INTO backup_snapshots (filename, source, size_bytes, content, created_at)
                VALUES (:filename, :source, :size_bytes, :content, now())
                ON CONFLICT (filename) DO UPDATE SET
                    content = EXCLUDED.content,
                    size_bytes = EXCLUDED.size_bytes,
                    source = EXCLUDED.source,
                    created_at = now()
            """),
            {
                "filename": filename,
                "source": source,
                "size_bytes": size,
                "content": content,
            },
        )
        await db.commit()

    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        (BACKUP_DIR / filename).write_text(content)
    except Exception as e:
        logger.warning("Disk mirror of backup failed (DB copy saved): %s", e)

    logger.info("Backup saved: %s (%.1f KB) source=%s", filename, size / 1024, source)
    return filename


async def create_backup_now(source: str = "manual") -> str:
    """Create and persist a backup immediately. Returns filename."""
    if not _check_disk_space():
        raise RuntimeError(
            f"Insufficient disk space (need ≥{MIN_FREE_DISK_GB}GB free). Backup aborted."
        )
    filename, content, backup = await _create_backup_payload()
    backup["source"] = source
    content = json.dumps(backup, indent=2, default=str)
    result = await _persist_backup(filename, content, source=source)
    _cleanup_old_backups_disk(MAX_KEEP_COUNT)
    await _cleanup_old_backups_db(MAX_KEEP_COUNT)
    return result


async def _create_backup_file() -> str:
    """Create a scheduled backup (DB + disk). Returns filename."""
    return await create_backup_now(source="scheduled")


async def list_persisted_backups() -> list[dict]:
    """List backups from DB (durable), falling back to disk files."""
    history: list[dict] = []
    try:
        async with async_session() as db:
            result = await db.execute(text("""
                SELECT filename, size_bytes, source, created_at
                FROM backup_snapshots
                ORDER BY created_at DESC
            """))
            for row in result.fetchall():
                history.append({
                    "filename": row[0],
                    "size_bytes": row[1] or 0,
                    "source": row[2] or "scheduled",
                    "created_at": row[3].isoformat() if row[3] else None,
                })
    except Exception as e:
        logger.warning("Failed to list DB backups: %s", e)

    if history:
        return history

    # Disk fallback (legacy / pre-migration)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(BACKUP_DIR.glob("quarry_backup_*.json"), reverse=True):
        try:
            stat = f.stat()
            history.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "source": "disk",
                "created_at": datetime.utcfromtimestamp(stat.st_mtime).replace(tzinfo=timezone.utc).isoformat(),
            })
        except Exception:
            pass
    return history


async def get_persisted_backup_content(filename: str) -> str | None:
    try:
        async with async_session() as db:
            result = await db.execute(
                text("SELECT content FROM backup_snapshots WHERE filename = :f"),
                {"f": filename},
            )
            row = result.scalar()
            if row:
                return row
    except Exception as e:
        logger.warning("Failed to read DB backup %s: %s", filename, e)

    path = BACKUP_DIR / filename
    if path.exists():
        return path.read_text()
    return None


async def delete_persisted_backup(filename: str) -> bool:
    deleted = False
    try:
        async with async_session() as db:
            result = await db.execute(
                text("DELETE FROM backup_snapshots WHERE filename = :f"),
                {"f": filename},
            )
            await db.commit()
            deleted = (result.rowcount or 0) > 0
    except Exception as e:
        logger.warning("Failed to delete DB backup %s: %s", filename, e)

    path = BACKUP_DIR / filename
    if path.exists():
        path.unlink()
        deleted = True
    return deleted


def _cleanup_old_backups_disk(keep: int = MAX_KEEP_COUNT):
    """Keep only the most recent N backup files on disk."""
    if not BACKUP_DIR.exists():
        return
    backups = sorted(
        BACKUP_DIR.glob("quarry_backup_*.json"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    deleted = 0
    for old_file in backups[keep:]:
        try:
            old_file.unlink()
            deleted += 1
            logger.info("Deleted old backup: %s", old_file.name)
        except Exception as e:
            logger.warning("Failed to delete old backup %s: %s", old_file.name, e)
    if deleted:
        logger.info("Backup retention: kept %d, deleted %d on disk", min(keep, len(backups)), deleted)


async def _cleanup_old_backups_db(keep: int = MAX_KEEP_COUNT):
    """Keep only the most recent N backup rows in the database."""
    try:
        async with async_session() as db:
            await db.execute(text("""
                DELETE FROM backup_snapshots
                WHERE filename NOT IN (
                    SELECT filename FROM backup_snapshots
                    ORDER BY created_at DESC LIMIT :keep
                )
            """), {"keep": keep})
            await db.commit()
    except Exception as e:
        logger.warning("Failed to prune DB backups: %s", e)


def _check_disk_space() -> bool:
    """Return False if disk has less than MIN_FREE_DISK_GB available."""
    try:
        usage = shutil.disk_usage(str(BACKUP_DIR.parent))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < MIN_FREE_DISK_GB:
            logger.error(
                "DISK SPACE CRITICAL: %.1fGB free (minimum %.1fGB). Backup skipped.",
                free_gb, MIN_FREE_DISK_GB,
            )
            return False
        return True
    except Exception as e:
        logger.warning("Disk space check failed: %s — proceeding with backup", e)
        return True


def _check_backup_dir_size():
    """Log a warning if the backup directory is getting large."""
    if not BACKUP_DIR.exists():
        return
    total = sum(f.stat().st_size for f in BACKUP_DIR.glob("*") if f.is_file())
    total_gb = total / (1024 ** 3)
    if total_gb > 1.0:
        logger.warning("Backup directory is %.1fGB — check retention policy", total_gb)


async def process_scheduled_backups():
    """Check if a scheduled backup is due and execute it.

    Called every 60s from the closure_scheduler loop.  All scheduling
    decisions happen here — a backup only runs when the wall-clock time
    passes the configured daily window AND at least MIN_BACKUP_INTERVAL
    has elapsed since the last run (hard safety floor).
    """
    config = await _read_schedule()
    logger.debug(
        "Backup scheduler tick — enabled=%s, config_keys=%s",
        config.get("enabled"), list(config.keys()),
    )
    if not config.get("enabled"):
        return

    frequency = config.get("frequency", "daily")
    time_str = config.get("time", "02:00")
    now = datetime.now(timezone.utc)

    # ── Hard safety floor: never run more often than MIN_BACKUP_INTERVAL ──
    last_run_str = config.get("last_run")
    if last_run_str:
        try:
            last_run = datetime.fromisoformat(last_run_str)
            if last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            elapsed = now - last_run
            if elapsed < MIN_BACKUP_INTERVAL:
                logger.debug(
                    "Backup scheduler: last run was %s ago (min interval %s), skipping",
                    elapsed, MIN_BACKUP_INTERVAL,
                )
                return
        except (ValueError, TypeError):
            pass

    # ── Determine next_run ──
    next_run_str = config.get("next_run")
    if next_run_str:
        try:
            next_run = datetime.fromisoformat(next_run_str)
            if next_run.tzinfo is None:
                from .timeutils import campus_tz
                next_run = next_run.replace(tzinfo=campus_tz())
        except (ValueError, TypeError):
            logger.warning("Backup scheduler: invalid next_run '%s', recomputing", next_run_str)
            next_run = _compute_next_run(frequency, time_str)
    else:
        # First boot or missing next_run — compute the next window
        next_run = _compute_next_run(frequency, time_str)
        config["next_run"] = next_run.isoformat()
        await _write_schedule(config)
        logger.info("Backup scheduler: initialised next_run to %s", next_run.isoformat())

    if now < next_run:
        return

    # ── Pre-flight: disk space check ──
    if not _check_disk_space():
        await _audit("Backup SKIPPED: insufficient disk space", action="DELETE")
        config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
        await _write_schedule(config)
        return

    # ── Run the backup ──
    try:
        logger.info("Backup scheduler: starting scheduled backup")
        filename = await _create_backup_file()
        logger.info("Backup scheduler: backup created — %s", filename)
        config["last_run"] = now.isoformat()
        config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
        await _write_schedule(config)
        logger.info("Backup scheduler: next_run updated to %s", config["next_run"])

        await _audit(
            f"Scheduled backup completed: {filename}",
            details={"filename": filename, "next_run": config["next_run"]},
        )

        drive_folder_id = config.get("google_drive_folder_id")
        if drive_folder_id:
            filepath = BACKUP_DIR / filename
            if not filepath.exists():
                content = await get_persisted_backup_content(filename)
                if content:
                    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
                    filepath.write_text(content)
            try:
                from .google_drive import upload_to_drive
                file_id = upload_to_drive(filepath, drive_folder_id)
                if file_id:
                    config["last_drive_upload"] = now.isoformat()
                    config["last_drive_file_id"] = file_id
                    await _write_schedule(config)
                    logger.info("Backup uploaded to Google Drive: %s", file_id)
                    await _audit(f"Backup uploaded to Google Drive: {file_id}")
                else:
                    logger.warning("Google Drive upload returned no file ID")
            except Exception as e:
                logger.error("Google Drive upload failed (backup still saved in DB): %s", e)
                await _audit(f"Google Drive upload failed: {e}", action="DELETE")

        # ── Post-backup: retention cleanup (keep last 7) ──
        _cleanup_old_backups_disk(MAX_KEEP_COUNT)
        await _cleanup_old_backups_db(MAX_KEEP_COUNT)
        _check_backup_dir_size()

    except Exception as e:
        logger.error("Scheduled backup failed: %s", e, exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        await _audit(f"Scheduled backup FAILED: {e}", action="DELETE")
        config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
        await _write_schedule(config)
