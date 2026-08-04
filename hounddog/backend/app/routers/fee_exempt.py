"""Admin endpoints for managing the fee-exempt roster."""

import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, require_admin
from ..database import get_db
from ..models.fee_exempt_roster import FeeExemptRoster
from ..services.roster_permit_status import (
    PermitMatch,
    load_active_permit_indexes,
    match_roster_to_permit,
)

logger = logging.getLogger("quarry.fee_exempt")

router = APIRouter(dependencies=[Depends(require_admin())])


class RosterEntry(BaseModel):
    id: str
    student_id: str
    email: str | None
    first_name: str
    last_name: str
    reason: str
    building: str | None
    room: str | None
    academic_year: str | None
    created_at: str
    has_permit: bool = False
    permit_number: str | None = None
    permit_type: str | None = None
    matched_by: str | None = None


class RosterAddRequest(BaseModel):
    student_id: str
    email: str | None = None
    first_name: str
    last_name: str
    reason: str = "Res Life Staff"
    building: str | None = None
    room: str | None = None
    academic_year: str | None = "2026-2027"


class RosterUploadResult(BaseModel):
    imported: int
    skipped: int
    errors: list[str]


def _entry_from_row(e: FeeExemptRoster, match: PermitMatch | None = None) -> RosterEntry:
    m = match or PermitMatch()
    return RosterEntry(
        id=str(e.id),
        student_id=e.student_id,
        email=e.email,
        first_name=e.first_name,
        last_name=e.last_name,
        reason=e.reason,
        building=e.building,
        room=e.room,
        academic_year=e.academic_year,
        created_at=e.created_at.isoformat() if e.created_at else "",
        has_permit=m.has_permit,
        permit_number=m.permit_number,
        permit_type=m.permit_type,
        matched_by=m.matched_by,
    )


@router.get("/roster", response_model=list[RosterEntry])
async def list_roster(db: AsyncSession = Depends(get_db)):
    """List all fee-exempt students with active-permit status."""
    result = await db.execute(
        select(FeeExemptRoster).order_by(FeeExemptRoster.last_name, FeeExemptRoster.first_name)
    )
    entries = result.scalars().all()
    by_email, by_student_id, by_name = await load_active_permit_indexes(db)
    return [
        _entry_from_row(
            e,
            match_roster_to_permit(
                student_id=e.student_id,
                email=e.email,
                first_name=e.first_name,
                last_name=e.last_name,
                by_email=by_email,
                by_student_id=by_student_id,
                by_name=by_name,
            ),
        )
        for e in entries
    ]


@router.get("/roster/count")
async def roster_count(db: AsyncSession = Depends(get_db)):
    count = (await db.execute(
        select(func.count()).select_from(FeeExemptRoster)
    )).scalar() or 0
    return {"count": count}


@router.post("/roster", response_model=RosterEntry, status_code=201)
async def add_single_entry(data: RosterAddRequest, db: AsyncSession = Depends(get_db)):
    """Add a single person to the fee-exempt roster."""
    entry = FeeExemptRoster(
        student_id=data.student_id.strip(),
        email=data.email.strip() if data.email else None,
        first_name=data.first_name.strip(),
        last_name=data.last_name.strip(),
        reason=data.reason,
        building=data.building,
        room=data.room,
        academic_year=data.academic_year,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    by_email, by_student_id, by_name = await load_active_permit_indexes(db)
    return _entry_from_row(
        entry,
        match_roster_to_permit(
            student_id=entry.student_id,
            email=entry.email,
            first_name=entry.first_name,
            last_name=entry.last_name,
            by_email=by_email,
            by_student_id=by_student_id,
            by_name=by_name,
        ),
    )


@router.post("/roster/upload", response_model=RosterUploadResult)
async def upload_roster(
    file: UploadFile = File(...),
    reason: str = Form("Res Life Staff"),
    academic_year: str = Form("2026-2027"),
    replace: bool = Form(False),
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Upload an Excel or CSV file to populate the fee-exempt roster.

    Expected columns: student_id (or moravian_id/id), last (or last_name),
    first (or first_name), building (optional), room (optional), email (optional).
    """
    content = await file.read()
    filename = file.filename or ""

    rows: list[dict] = []
    errors: list[str] = []

    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
            ws = wb.active
            headers_raw = [str(c.value or "").strip().lower() for c in next(ws.iter_rows(min_row=1, max_row=1))]
            headers = _normalize_headers(headers_raw)
            for row_cells in ws.iter_rows(min_row=2, values_only=True):
                row_dict = dict(zip(headers, row_cells))
                rows.append(row_dict)
        except Exception as e:
            raise HTTPException(400, f"Failed to parse Excel file: {e}")
    elif filename.endswith(".csv"):
        import csv
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text))
        raw_fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        norm_fieldnames = _normalize_headers(raw_fieldnames)
        for raw_row in reader:
            row_dict = {
                norm_fieldnames[i]: v
                for i, (_, v) in enumerate(raw_row.items())
                if i < len(norm_fieldnames)
            }
            rows.append(row_dict)
    else:
        raise HTTPException(400, "Upload an .xlsx or .csv file")

    if not rows:
        raise HTTPException(400, "File contains no data rows")

    if replace:
        await db.execute(delete(FeeExemptRoster))

    imported = 0
    skipped = 0
    for i, row in enumerate(rows, start=2):
        student_id = str(row.get("student_id") or "").strip()
        if not student_id:
            errors.append(f"Row {i}: missing student ID")
            skipped += 1
            continue

        first_name = str(row.get("first_name") or "").strip()
        last_name = str(row.get("last_name") or "").strip()
        email = str(row.get("email") or "").strip() or None
        building = str(row.get("building") or "").strip() or None
        room = str(row.get("room") or "").strip() or None

        entry = FeeExemptRoster(
            student_id=student_id,
            email=email,
            first_name=first_name,
            last_name=last_name,
            reason=reason,
            building=building,
            room=room,
            academic_year=academic_year,
        )
        db.add(entry)
        imported += 1

    if imported > 0:
        await db.flush()

    return RosterUploadResult(imported=imported, skipped=skipped, errors=errors[:20])


@router.delete("/roster/{entry_id}")
async def delete_roster_entry(
    entry_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    entry = await db.get(FeeExemptRoster, entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    await db.delete(entry)
    await db.flush()
    return {"deleted": True}


@router.delete("/roster")
async def clear_roster(db: AsyncSession = Depends(get_db)):
    """Delete all entries from the fee-exempt roster."""
    count = (await db.execute(
        select(func.count()).select_from(FeeExemptRoster)
    )).scalar() or 0
    await db.execute(delete(FeeExemptRoster))
    return {"deleted": count}


def _normalize_headers(headers: list[str]) -> list[str]:
    """Map common header variations to canonical field names."""
    mapping = {
        "moravian id": "student_id",
        "moravian_id": "student_id",
        "id": "student_id",
        "student id": "student_id",
        "student_id": "student_id",
        "last": "last_name",
        "last_name": "last_name",
        "last name": "last_name",
        "first": "first_name",
        "first_name": "first_name",
        "first name": "first_name",
        "email": "email",
        "building": "building",
        "hall": "building",
        "residence hall": "building",
        "room": "room",
        "room #": "room",
    }
    return [mapping.get(h, h) for h in headers]
