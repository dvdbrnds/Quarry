"""
Database backup & restore API.

Export dumps every user-data table (skipping alembic_version) as JSON.
Restore wipes existing data and re-inserts from the uploaded file.
Scheduled backups store snapshots to disk on a cron-like interval.
Both endpoints require admin role.
"""

import io
import json
import logging
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy import text, inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, require_admin
from ..database import get_db, engine

logger = logging.getLogger("quarry.backup")

router = APIRouter(dependencies=[Depends(require_admin())])

SKIP_TABLES = {"alembic_version"}

BACKUP_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "backups"
SCHEDULE_FILE = BACKUP_DIR / "_schedule.json"
MAX_RETENTION = 90  # days


def _serialise(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    return value


async def _get_table_names() -> list[str]:
    """Return all user-data table names from the database."""
    async with engine.connect() as conn:
        def _inspect(sync_conn):
            insp = sa_inspect(sync_conn)
            return insp.get_table_names()
        names = await conn.run_sync(_inspect)
    return sorted(n for n in names if n not in SKIP_TABLES)


@router.get("/tables")
async def list_tables(
    db: AsyncSession = Depends(get_db),
):
    """Return table names and row counts for the backup preview."""
    tables = await _get_table_names()
    counts = {}
    for tbl in tables:
        row = await db.execute(text(f'SELECT count(*) FROM "{tbl}"'))
        counts[tbl] = row.scalar() or 0
    return {"tables": counts}


@router.get("/export")
async def export_backup(
    db: AsyncSession = Depends(get_db),
):
    """Stream a full JSON backup of all data tables."""
    tables = await _get_table_names()
    payload: dict[str, list[dict]] = {}

    for tbl in tables:
        result = await db.execute(text(f'SELECT * FROM "{tbl}"'))
        columns = list(result.keys())
        rows = []
        for row in result.fetchall():
            rows.append({col: _serialise(row[i]) for i, col in enumerate(columns)})
        payload[tbl] = rows

    backup = {
        "format": "quarry_backup_v1",
        "exported_at": datetime.utcnow().isoformat(),
        "tables": payload,
    }

    content = json.dumps(backup, indent=2, default=str)
    buf = io.BytesIO(content.encode("utf-8"))
    filename = f"quarry_backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

    return StreamingResponse(
        buf,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore")
async def restore_backup(
    file: UploadFile = File(...),
    _admin: OktaUser = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """
    Restore all data from a previously exported JSON backup.

    This TRUNCATES every table in the backup then re-inserts all rows.
    Foreign key checks are deferred during the restore.
    """
    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid JSON file")

    if data.get("format") != "quarry_backup_v1":
        raise HTTPException(400, "Unrecognised backup format. Expected quarry_backup_v1.")

    tables_data: dict[str, list[dict]] = data.get("tables", {})
    if not tables_data:
        raise HTTPException(400, "Backup file contains no table data")

    existing_tables = set(await _get_table_names())
    unknown = set(tables_data.keys()) - existing_tables
    if unknown:
        logger.warning("Backup contains unknown tables (skipping): %s", unknown)

    restored = {}
    skipped = []

    try:
        # Defer FK constraints so we can truncate/insert in any order
        await db.execute(text("SET CONSTRAINTS ALL DEFERRED"))

        for tbl_name in tables_data:
            if tbl_name not in existing_tables:
                skipped.append(tbl_name)
                continue

            rows = tables_data[tbl_name]
            await db.execute(text(f'TRUNCATE TABLE "{tbl_name}" CASCADE'))

            if rows:
                cols = list(rows[0].keys())
                col_list = ", ".join(f'"{c}"' for c in cols)
                param_list = ", ".join(f":{c}" for c in cols)
                insert_sql = text(f'INSERT INTO "{tbl_name}" ({col_list}) VALUES ({param_list})')
                for row in rows:
                    await db.execute(insert_sql, row)

            restored[tbl_name] = len(rows)

    except Exception as e:
        logger.exception("Restore failed")
        raise HTTPException(500, f"Restore failed: {e}")

    return {
        "status": "ok",
        "restored": restored,
        "skipped": skipped,
        "exported_at": data.get("exported_at"),
    }


@router.delete("/clear-tickets")
async def clear_tickets(
    _admin: OktaUser = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Delete all rows from the tickets table (and cascading payments)."""
    count_row = await db.execute(text('SELECT count(*) FROM "tickets"'))
    count = count_row.scalar() or 0
    await db.execute(text('TRUNCATE TABLE "tickets" CASCADE'))
    return {"deleted": count}


@router.delete("/clear-permits")
async def clear_permits(
    _admin: OktaUser = Depends(require_admin()),
    db: AsyncSession = Depends(get_db),
):
    """Delete all permits, permit applications, lottery applications, and permit-related payments."""
    permits_row = await db.execute(text('SELECT count(*) FROM "permits"'))
    permits_count = permits_row.scalar() or 0

    apps_row = await db.execute(text('SELECT count(*) FROM "permit_applications"'))
    apps_count = apps_row.scalar() or 0

    lottery_apps_row = await db.execute(text('SELECT count(*) FROM "lottery_v2_applications"'))
    lottery_apps_count = lottery_apps_row.scalar() or 0

    payments_row = await db.execute(text(
        "SELECT count(*) FROM payments WHERE payment_type IN "
        "('direct_permit_purchase', 'lottery_permit', 'lottery_v2_permit', 'standalone_permit_purchase', 'fee_exempt')"
    ))
    payments_count = payments_row.scalar() or 0

    await db.execute(text('TRUNCATE TABLE "permit_applications" CASCADE'))
    await db.execute(text('TRUNCATE TABLE "lottery_v2_applications" CASCADE'))
    await db.execute(text('TRUNCATE TABLE "permits" CASCADE'))
    await db.execute(text(
        "DELETE FROM payments WHERE payment_type IN "
        "('direct_permit_purchase', 'lottery_permit', 'lottery_v2_permit', 'standalone_permit_purchase', 'fee_exempt')"
    ))

    return {
        "permits_deleted": permits_count,
        "applications_deleted": apps_count + lottery_apps_count,
        "payments_deleted": payments_count,
    }


# ---------------------------------------------------------------------------
# Scheduled backup configuration & history
# ---------------------------------------------------------------------------

class BackupSchedule(BaseModel):
    enabled: bool = False
    frequency: str = "daily"  # daily | weekly | monthly
    time: str = "02:00"       # HH:MM in UTC
    retention_days: int = 30  # auto-delete after N days
    google_drive_folder_id: str = ""  # Google Drive folder to upload backups to
    last_run: str | None = None
    next_run: str | None = None
    last_drive_upload: str | None = None


def _read_schedule() -> dict:
    """Read the schedule JSON from disk, returning defaults if absent.

    DEPRECATED: new code should use _read_schedule_db / _write_schedule_db.
    Kept as sync fallback only for the scheduler service.
    """
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return {"enabled": False, "frequency": "daily", "time": "02:00", "retention_days": 30}


def _write_schedule(data: dict):
    """Write schedule to disk (legacy). Also writes to DB for persistence."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(data, indent=2))


async def _read_schedule_db(db: AsyncSession) -> dict:
    """Read backup schedule from the app_config table (survives redeploys)."""
    try:
        async with db.begin_nested():
            result = await db.execute(
                text("SELECT value FROM app_config WHERE key = 'backup_schedule'")
            )
            row = result.scalar()
            if row:
                return row if isinstance(row, dict) else json.loads(row)
    except Exception as e:
        logger.warning("Failed to read schedule from DB: %s", e)
    return {"enabled": False, "frequency": "daily", "time": "02:00", "retention_days": 30}


async def _write_schedule_db(db: AsyncSession, data: dict):
    """Persist backup schedule to both DB and disk (disk for scheduler reads)."""
    import json as _json
    value_str = _json.dumps(data)
    async with db.begin_nested():
        await db.execute(text("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES ('backup_schedule', :val::jsonb, now())
            ON CONFLICT (key) DO UPDATE SET value = :val::jsonb, updated_at = now()
        """), {"val": value_str})
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        SCHEDULE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.warning("Failed to write schedule to disk (DB persisted): %s", e)


@router.get("/schedule")
async def get_schedule(db: AsyncSession = Depends(get_db)):
    """Return the current scheduled backup configuration."""
    return await _read_schedule_db(db)


@router.post("/schedule")
async def set_schedule(body: BackupSchedule, db: AsyncSession = Depends(get_db)):
    """Create or update the scheduled backup configuration."""
    try:
        data = body.model_dump()
        try:
            existing = await _read_schedule_db(db)
        except Exception:
            existing = {}
        data["last_run"] = existing.get("last_run")
        data["next_run"] = existing.get("next_run")
        data["last_drive_upload"] = existing.get("last_drive_upload")
        data["last_drive_file_id"] = existing.get("last_drive_file_id")
        await _write_schedule_db(db, data)
        await db.flush()
        return data
    except Exception as e:
        logger.exception("Failed to set backup schedule")
        raise HTTPException(500, f"Failed to save schedule: {type(e).__name__}: {e}")


@router.post("/schedule/disable")
async def disable_schedule(db: AsyncSession = Depends(get_db)):
    """Disable scheduled backups."""
    data = await _read_schedule_db(db)
    data["enabled"] = False
    await _write_schedule_db(db, data)
    return data


@router.get("/history")
async def list_backup_history():
    """List all stored backup files with metadata."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(BACKUP_DIR.glob("quarry_backup_*.json"), reverse=True)
    history = []
    for f in files:
        stat = f.stat()
        history.append({
            "filename": f.name,
            "size_bytes": stat.st_size,
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    return history


@router.get("/history/{filename}")
async def download_backup_file(filename: str):
    """Download a specific stored backup file."""
    if ".." in filename or "/" in filename:
        raise HTTPException(400, "Invalid filename")
    path = BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Backup file not found")
    return FileResponse(
        path,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/history/{filename}")
async def delete_backup_file(filename: str):
    """Delete a specific stored backup file."""
    if ".." in filename or "/" in filename:
        raise HTTPException(400, "Invalid filename")
    path = BACKUP_DIR / filename
    if not path.exists():
        raise HTTPException(404, "Backup file not found")
    path.unlink()
    return {"deleted": filename}


@router.post("/test-drive")
async def test_google_drive(
    folder_id: str = Query(""),
    db: AsyncSession = Depends(get_db),
):
    """Test Google Drive connectivity for the given folder ID."""
    if not folder_id:
        schedule = await _read_schedule_db(db)
        folder_id = schedule.get("google_drive_folder_id", "")
    if not folder_id:
        raise HTTPException(400, "No folder ID provided")

    from ..services.google_drive import test_drive_connection
    result = test_drive_connection(folder_id)
    if not result["ok"]:
        raise HTTPException(400, result["error"])
    return result
