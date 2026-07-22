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

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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


# ---------------------------------------------------------------------------
# Scheduled backup configuration & history
# ---------------------------------------------------------------------------

class BackupSchedule(BaseModel):
    enabled: bool = False
    frequency: str = "daily"  # daily | weekly | monthly
    time: str = "02:00"       # HH:MM in UTC
    retention_days: int = 30  # auto-delete after N days
    last_run: str | None = None
    next_run: str | None = None


def _read_schedule() -> dict:
    """Read the schedule JSON from disk, returning defaults if absent."""
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text())
        except Exception:
            pass
    return {"enabled": False, "frequency": "daily", "time": "02:00", "retention_days": 30}


def _write_schedule(data: dict):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(data, indent=2))


@router.get("/schedule")
async def get_schedule():
    """Return the current scheduled backup configuration."""
    return _read_schedule()


@router.put("/schedule")
async def set_schedule(body: BackupSchedule):
    """Create or update the scheduled backup configuration."""
    data = body.model_dump()
    existing = _read_schedule()
    data["last_run"] = existing.get("last_run")
    data["next_run"] = existing.get("next_run")
    _write_schedule(data)
    return data


@router.delete("/schedule")
async def disable_schedule():
    """Disable scheduled backups."""
    data = _read_schedule()
    data["enabled"] = False
    _write_schedule(data)
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
