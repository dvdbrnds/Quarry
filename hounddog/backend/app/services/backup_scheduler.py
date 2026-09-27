"""
Scheduled backup processor.

Runs inside the existing closure_scheduler loop every 60s.
Creates a pg_dump backup file when due. Also handles retention cleanup.

SAFETY:
- A minimum interval of 1 hour is enforced between backups.
- Writes to a temp file and renames on success (no partial dumps).
- Hard timeout of 30 minutes; kills pg_dump and deletes partial file.
- Python never holds the database contents in memory.
- Persists last attempt time so crash-restart loops don't re-trigger.
- First backup delayed at least 10 minutes after startup.
- QUARRY_BACKUP_ENABLED env var (default true) can disable entirely.
"""

import asyncio
import json
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

from ..database import async_session

logger = logging.getLogger("quarry.backup_scheduler")

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "backups"
MIN_BACKUP_INTERVAL = timedelta(hours=1)
MIN_FREE_DISK_GB = 2.0
MAX_KEEP_COUNT = 7

BACKUP_TIMEOUT_SECONDS = 30 * 60  # 30 minutes
STARTUP_DELAY_SECONDS = 10 * 60   # 10 minutes
ATTEMPT_COOLDOWN = timedelta(hours=6)

SCHEDULE_FILE = BACKUP_DIR / "_schedule.json"
ATTEMPT_FILE = BACKUP_DIR / "_last_attempt"
BACKUP_ADVISORY_LOCK_KEY = 870014

FREQUENCY_DELTAS = {
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
    "monthly": timedelta(days=30),
}

# Module-level startup timestamp to enforce 10-minute delay
_module_loaded_at = datetime.now(timezone.utc)


def _backup_enabled() -> bool:
    """Check QUARRY_BACKUP_ENABLED env var (default true)."""
    return os.environ.get("QUARRY_BACKUP_ENABLED", "true").lower() in ("true", "1", "yes")


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _parse_hhmm(time_str: str) -> tuple[int, int]:
    parts = (time_str or "02:00").split(":")
    try:
        hour = int(parts[0])
    except (ValueError, IndexError):
        hour = 2
    try:
        minute = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        minute = 0
    return max(0, min(23, hour)), max(0, min(59, minute))


def current_slot(frequency: str, time_str: str, now: datetime) -> datetime:
    """Most recent scheduled wall-clock time that has already arrived (campus TZ)."""
    from .timeutils import campus_tz
    tz = campus_tz()
    local = _aware(now).astimezone(tz)
    hour, minute = _parse_hhmm(time_str)
    slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if slot > local:
        slot -= FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return slot


def is_backup_due(
    frequency: str,
    time_str: str,
    now: datetime,
    last_scheduled: datetime | None,
) -> bool:
    """Whether a scheduled backup should run for the current slot."""
    if last_scheduled is None:
        from .timeutils import campus_tz
        local = _aware(now).astimezone(campus_tz())
        hour, minute = _parse_hhmm(time_str)
        todays_slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return local >= todays_slot

    slot = current_slot("daily", time_str, now)
    last = _aware(last_scheduled)
    if last >= slot:
        return False
    if frequency == "daily":
        return True
    period = FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return (_aware(now) - last) >= period


# ---------------------------------------------------------------------------
# Attempt tracking (prevents restart loops)
# ---------------------------------------------------------------------------

def _read_last_attempt() -> datetime | None:
    """Read last backup attempt timestamp from disk."""
    try:
        if ATTEMPT_FILE.exists():
            ts = ATTEMPT_FILE.read_text().strip()
            return datetime.fromisoformat(ts)
    except Exception:
        pass
    return None


def _write_last_attempt(dt: datetime | None = None):
    """Persist current time as last backup attempt."""
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ATTEMPT_FILE.write_text((dt or datetime.now(timezone.utc)).isoformat())
    except Exception as e:
        logger.warning("Failed to write last attempt timestamp: %s", e)


def _too_soon_after_startup() -> bool:
    """Return True if we're within 10 minutes of module load (startup)."""
    elapsed = (datetime.now(timezone.utc) - _module_loaded_at).total_seconds()
    return elapsed < STARTUP_DELAY_SECONDS


def _attempted_recently() -> bool:
    """Return True if a backup was attempted in the last 6 hours."""
    last = _read_last_attempt()
    if last is None:
        return False
    return (datetime.now(timezone.utc) - _aware(last)) < ATTEMPT_COOLDOWN


# ---------------------------------------------------------------------------
# Schedule config (DB + disk)
# ---------------------------------------------------------------------------

async def _read_schedule_from_db() -> dict | None:
    try:
        from sqlalchemy import text
        async with async_session() as db:
            result = await db.execute(
                text("SELECT value FROM app_config WHERE key = 'backup_schedule'")
            )
            row = result.scalar()
            if row:
                parsed = row if isinstance(row, dict) else json.loads(row)
                return parsed
    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.warning("Backup schedule: failed to read from DB: %s", e)
    return None


def _read_schedule_from_disk() -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return {"enabled": False}


async def _read_schedule() -> dict:
    db_config = await _read_schedule_from_db()
    if db_config is not None:
        return db_config
    return _read_schedule_from_disk()


async def _write_schedule(data: dict):
    try:
        from sqlalchemy import text
        value_str = json.dumps(data)
        async with async_session() as db:
            await db.execute(text("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES ('backup_schedule', CAST(:val AS jsonb), now())
                ON CONFLICT (key) DO UPDATE SET value = CAST(:val AS jsonb), updated_at = now()
            """), {"val": value_str})
            await db.commit()
    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.error("Failed to write schedule to DB: %s", e)
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        SCHEDULE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.warning("Failed to write schedule to disk: %s", e)


def _compute_next_run(frequency: str, time_str: str, from_dt: datetime | None = None) -> datetime:
    from .timeutils import campus_tz, now_local
    tz = campus_tz()
    now = _aware(from_dt).astimezone(tz) if from_dt else now_local()
    hour, minute = _parse_hhmm(time_str)
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += FREQUENCY_DELTAS.get(frequency, timedelta(days=1))
    return candidate


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

async def _audit(summary: str, action: str = "POST", details: dict | None = None):
    try:
        from ..models.audit_log import AuditLog
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
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.warning("Failed to write backup audit entry: %s", e)


# ---------------------------------------------------------------------------
# pg_dump based backup
# ---------------------------------------------------------------------------

def _parse_database_url() -> dict:
    """Parse DATABASE_URL into components for pg_dump.

    Converts asyncpg:// to postgresql:// and extracts host, port, user, password, dbname.
    """
    from ..config import settings
    url = settings.database_url

    # Normalize driver prefix for parsing
    for prefix in ("postgresql+asyncpg://", "asyncpg://"):
        if url.startswith(prefix):
            url = "postgresql://" + url[len(prefix):]
            break

    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "quarry",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "quarry",
    }


async def _run_pg_dump(output_path: Path) -> None:
    """Run pg_dump -Fc writing directly to output_path.

    Uses asyncio subprocess so we don't block the event loop.
    Password is passed via PGPASSWORD env var (never on command line).
    Hard timeout of 30 minutes.
    """
    db = _parse_database_url()

    env = {**os.environ, "PGPASSWORD": db["password"]}
    # Remove any vars that could interfere
    env.pop("PGDATABASE", None)
    env.pop("PGUSER", None)
    env.pop("PGHOST", None)
    env.pop("PGPORT", None)

    cmd = [
        "pg_dump",
        "-Fc",                       # Custom format (compressed, streamable)
        "-h", db["host"],
        "-p", db["port"],
        "-U", db["user"],
        "-d", db["dbname"],
        "--no-owner",
        "--no-acl",
        "-f", str(output_path),
    ]

    logger.info("Starting pg_dump: host=%s db=%s -> %s", db["host"], db["dbname"], output_path.name)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        env=env,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=BACKUP_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.error("pg_dump timed out after %d seconds — killing", BACKUP_TIMEOUT_SECONDS)
        proc.kill()
        await proc.wait()
        # Clean up partial file
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"pg_dump timed out after {BACKUP_TIMEOUT_SECONDS}s")

    if proc.returncode != 0:
        stderr_text = stderr.decode("utf-8", errors="replace").strip() if stderr else ""
        # Clean up partial file
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"pg_dump failed (rc={proc.returncode}): {stderr_text[:500]}")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("pg_dump completed: %s (%.1f MB)", output_path.name, size_mb)


async def _create_backup_file(source: str = "scheduled") -> str:
    """Create a pg_dump backup file. Returns filename.

    Writes to a .tmp file first, renames on success.
    """
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"quarry_backup_{timestamp}.dump"
    final_path = BACKUP_DIR / filename
    tmp_path = BACKUP_DIR / f".{filename}.tmp"

    try:
        await _run_pg_dump(tmp_path)
        tmp_path.rename(final_path)
    except Exception:
        # Cleanup temp file on any failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise

    logger.info("Backup saved: %s (%.1f KB) source=%s",
                filename, final_path.stat().st_size / 1024, source)
    return filename


async def create_backup_now(source: str = "manual") -> str:
    """Create a backup immediately. Returns filename."""
    if not _check_disk_space():
        raise RuntimeError(
            f"Insufficient disk space (need ≥{MIN_FREE_DISK_GB}GB free). Backup aborted."
        )
    filename = await _create_backup_file(source=source)
    _cleanup_old_backups_disk(MAX_KEEP_COUNT)
    return filename


# ---------------------------------------------------------------------------
# Backup history (disk-based — no more storing dumps in Postgres)
# ---------------------------------------------------------------------------

async def list_persisted_backups() -> list[dict]:
    """List backup files on disk."""
    history: list[dict] = []
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for f in sorted(BACKUP_DIR.glob("quarry_backup_*.*"), reverse=True):
        if f.name.startswith("."):
            continue
        try:
            stat = f.stat()
            history.append({
                "filename": f.name,
                "size_bytes": stat.st_size,
                "source": "disk",
                "created_at": datetime.utcfromtimestamp(stat.st_mtime).replace(
                    tzinfo=timezone.utc
                ).isoformat(),
            })
        except Exception:
            pass
    return history


async def get_persisted_backup_content(filename: str) -> bytes | None:
    """Read a backup file from disk. Returns bytes (dump is binary)."""
    path = BACKUP_DIR / filename
    if path.exists():
        return path.read_bytes()
    return None


async def delete_persisted_backup(filename: str) -> bool:
    path = BACKUP_DIR / filename
    if path.exists():
        path.unlink()
        return True
    return False


# ---------------------------------------------------------------------------
# Latest scheduled backup
# ---------------------------------------------------------------------------

async def _latest_scheduled_created_at() -> datetime | None:
    """Timestamp of the most recent scheduled backup file on disk."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = sorted(BACKUP_DIR.glob("quarry_backup_*.*"), key=lambda f: f.stat().st_mtime, reverse=True)
    for f in backups:
        if f.name.startswith("."):
            continue
        try:
            return _aware(datetime.utcfromtimestamp(f.stat().st_mtime).replace(tzinfo=timezone.utc))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------

def _cleanup_old_backups_disk(keep: int = MAX_KEEP_COUNT):
    if not BACKUP_DIR.exists():
        return
    backups = sorted(
        [f for f in BACKUP_DIR.glob("quarry_backup_*.*") if not f.name.startswith(".")],
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
            import sentry_sdk
            sentry_sdk.capture_exception(e)
            logger.warning("Failed to delete old backup %s: %s", old_file.name, e)
    if deleted:
        logger.info("Backup retention: kept %d, deleted %d on disk", min(keep, len(backups)), deleted)


async def _cleanup_old_backups_db(keep: int = MAX_KEEP_COUNT):
    """Clean up legacy backup_snapshots rows if the table exists."""
    try:
        from sqlalchemy import text
        async with async_session() as db:
            await db.execute(text("""
                DELETE FROM backup_snapshots
                WHERE filename NOT IN (
                    SELECT filename FROM backup_snapshots
                    ORDER BY created_at DESC LIMIT :keep
                )
            """), {"keep": keep})
            await db.commit()
    except Exception:
        pass  # Table may not exist or be empty — fine


def _check_disk_space() -> bool:
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
        import sentry_sdk
        sentry_sdk.capture_exception(e)
        logger.warning("Disk space check failed: %s — proceeding with backup", e)
        return True


def _check_backup_dir_size():
    if not BACKUP_DIR.exists():
        return
    total = sum(f.stat().st_size for f in BACKUP_DIR.glob("*") if f.is_file())
    total_gb = total / (1024 ** 3)
    if total_gb > 1.0:
        logger.warning("Backup directory is %.1fGB — check retention policy", total_gb)


# ---------------------------------------------------------------------------
# Main scheduler entry point
# ---------------------------------------------------------------------------

async def process_scheduled_backups():
    """Check if a scheduled backup is due and execute it.

    Called every 60s from the closure_scheduler loop.
    """
    if not _backup_enabled():
        logger.debug("Backups disabled via QUARRY_BACKUP_ENABLED=false")
        return

    if _too_soon_after_startup():
        logger.debug("Backup scheduler: waiting for startup delay (%ds)", STARTUP_DELAY_SECONDS)
        return

    if _attempted_recently():
        logger.debug("Backup scheduler: attempt within last %s, skipping", ATTEMPT_COOLDOWN)
        return

    config = await _read_schedule()
    if not config.get("enabled"):
        return

    frequency = config.get("frequency", "daily")
    time_str = config.get("time", "02:00")
    now = datetime.now(timezone.utc)
    last_scheduled = await _latest_scheduled_created_at()

    if last_scheduled and (now - last_scheduled) < MIN_BACKUP_INTERVAL:
        return

    if not is_backup_due(frequency, time_str, now, last_scheduled):
        if not config.get("next_run"):
            config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
            await _write_schedule(config)
        return

    # Only one worker proceeds with the actual backup
    from ..database import engine
    from sqlalchemy import text
    async with engine.connect() as lock_conn:
        got_lock = (await lock_conn.execute(
            text("SELECT pg_try_advisory_lock(:k)"),
            {"k": BACKUP_ADVISORY_LOCK_KEY},
        )).scalar()
        if not got_lock:
            return
        try:
            last_scheduled = await _latest_scheduled_created_at()
            if last_scheduled and (now - last_scheduled) < MIN_BACKUP_INTERVAL:
                return
            if not is_backup_due(frequency, time_str, now, last_scheduled):
                return
            await _execute_scheduled_backup(config, frequency, time_str, now)
        finally:
            await lock_conn.execute(
                text("SELECT pg_advisory_unlock(:k)"),
                {"k": BACKUP_ADVISORY_LOCK_KEY},
            )
            await lock_conn.commit()


async def _execute_scheduled_backup(
    config: dict, frequency: str, time_str: str, now: datetime,
):
    # Record attempt BEFORE starting so crash-restarts won't retry immediately
    _write_last_attempt(now)

    if not _check_disk_space():
        await _audit("Backup SKIPPED: insufficient disk space", action="DELETE")
        return

    try:
        logger.info("Backup scheduler: starting scheduled backup")
        filename = await _create_backup_file(source="scheduled")
        logger.info("Backup scheduler: backup created — %s", filename)
        config["last_run"] = now.isoformat()
        config["next_run"] = _compute_next_run(frequency, time_str, now).isoformat()
        await _write_schedule(config)

        await _audit(
            f"Scheduled backup completed: {filename}",
            details={"filename": filename, "next_run": config["next_run"]},
        )

        drive_folder_id = config.get("google_drive_folder_id")
        if drive_folder_id:
            filepath = BACKUP_DIR / filename
            if filepath.exists():
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
                    import sentry_sdk
                    sentry_sdk.capture_exception(e)
                    logger.error("Google Drive upload failed (backup still saved on disk): %s", e)
                    await _audit(f"Google Drive upload failed: {e}", action="DELETE")

        _cleanup_old_backups_disk(MAX_KEEP_COUNT)
        _check_backup_dir_size()

    except Exception as e:
        logger.error("Scheduled backup failed: %s", e, exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        await _audit(f"Scheduled backup FAILED: {e}", action="DELETE")
