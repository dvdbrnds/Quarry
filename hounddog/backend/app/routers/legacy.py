"""Legacy Omnigo records — plate history lookup and import-to-tag."""

import io
import re
import uuid
from datetime import date, datetime, timezone

import structlog

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from ..utils.safe_router import SafeRouter
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin, require_office
from ..database import get_db
from ..models.legacy_record import LegacyRecord
from ..models.permit import Permit

logger = structlog.get_logger("quarry")

router = SafeRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────


class LegacyRecordRead(BaseModel):
    id: uuid.UUID
    plate_normalized: str
    plate_raw: str
    plate_state: str
    owner_name: str
    permit_number: str
    permit_type: str
    permit_status: str
    lot_zone: str
    vehicle_color: str
    vehicle_make: str
    vehicle_model: str
    vehicle_year: str
    vehicle_description: str
    record_date: date | None
    expiration_date: date | None
    source: str
    imported_at: datetime | None
    created_at: datetime


class LegacyImportRow(BaseModel):
    plate_normalized: str
    plate_raw: str = ""
    plate_state: str = ""
    owner_name: str = ""
    permit_number: str = ""
    permit_type: str = ""
    permit_status: str = ""
    lot_zone: str = ""
    vehicle_color: str = ""
    vehicle_make: str = ""
    vehicle_model: str = ""
    vehicle_year: str = ""
    vehicle_description: str = ""
    record_date: str | None = None
    expiration_date: str | None = None
    source: str = "omnigo"


class LegacyImportPayload(BaseModel):
    records: list[LegacyImportRow]


class LegacyImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int


def _normalize_plate(raw: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", raw.upper().strip())


def _parse_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    val = str(val).strip()
    val = val.strip(",").strip()
    if not val or val in ("-", "N/A", "n/a"):
        return None
    # Take only the first value if comma-separated
    if "," in val:
        val = val.split(",")[0].strip()
    # Strip fractional seconds (e.g. ".03", ".953") before parsing
    cleaned = re.sub(r"\.\d+$", "", val)
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


# ── Lookup (no auth — used by public ticket pages too) ───────────────────────


@router.get("/lookup")
async def legacy_lookup(
    plate: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    normalized = _normalize_plate(plate)
    if not normalized:
        return None

    result = await db.execute(
        select(LegacyRecord).where(LegacyRecord.plate_normalized == normalized)
    )
    record = result.scalar_one_or_none()
    if not record:
        return None

    return LegacyRecordRead(
        id=record.id,
        plate_normalized=record.plate_normalized,
        plate_raw=record.plate_raw,
        plate_state=record.plate_state,
        owner_name=record.owner_name,
        permit_number=record.permit_number,
        permit_type=record.permit_type,
        permit_status=record.permit_status,
        lot_zone=record.lot_zone,
        vehicle_color=record.vehicle_color,
        vehicle_make=record.vehicle_make,
        vehicle_model=record.vehicle_model,
        vehicle_year=record.vehicle_year,
        vehicle_description=record.vehicle_description,
        record_date=record.record_date,
        expiration_date=record.expiration_date,
        source=record.source,
        imported_at=record.imported_at,
        created_at=record.created_at,
    )


# ── Count ─────────────────────────────────────────────────────────────────────


@router.get("/count")
async def legacy_count(
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user),
):
    result = await db.execute(select(func.count(LegacyRecord.id)))
    return {"count": result.scalar_one()}


# ── Import as Vehicle Tag ────────────────────────────────────────────────────


@router.post("/{record_id}/import-tag")
async def import_as_tag(
    record_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_office()),
):
    record = await db.get(LegacyRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Legacy record not found")

    # Check if a tag or permit already exists for this plate
    existing = (
        await db.execute(
            select(Permit).where(
                Permit.plates.any(record.plate_normalized),
                Permit.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A permit/tag already exists for plate {record.plate_normalized} (#{existing.permit_number or existing.id})",
        )

    # Build vehicle description from individual fields if not set
    desc = record.vehicle_description
    if not desc:
        parts = [record.vehicle_color, record.vehicle_year, record.vehicle_make, record.vehicle_model]
        desc = " ".join(p for p in parts if p).strip()

    tag = Permit(
        name=record.owner_name,
        plates=[record.plate_normalized],
        permit_type="vehicle_tag",
        status="active",
        is_tag_only=True,
        lot_assignment=record.lot_zone,
        vehicle_make=record.vehicle_make or None,
        vehicle_model=record.vehicle_model or None,
        vehicle_color=record.vehicle_color or None,
        vehicle_year=record.vehicle_year or None,
        vehicle_description=desc or None,
        tag_source="omnigo_import",
        tag_notes=f"Imported from Omnigo legacy record (permit #{record.permit_number}, {record.permit_type})",
    )
    if record.plate_state:
        tag.student_id = f"plate_state:{record.plate_state}"

    db.add(tag)

    # Mark the legacy record as imported
    record.imported_at = datetime.now(timezone.utc)

    await db.commit()

    logger.info(
        "legacy_record_imported_as_tag",
        legacy_id=str(record.id),
        plate=record.plate_normalized,
        tag_id=str(tag.id),
        by=user.email,
    )

    return {"tag_id": str(tag.id), "plate": record.plate_normalized}


# ── Bulk Import (JSON) ───────────────────────────────────────────────────────


@router.post("/import", response_model=LegacyImportResult)
async def bulk_import(
    payload: LegacyImportPayload,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_admin),
):
    inserted = 0
    updated = 0
    skipped = 0

    for row in payload.records:
        plate = _normalize_plate(row.plate_normalized)
        if not plate:
            skipped += 1
            continue

        existing = (
            await db.execute(
                select(LegacyRecord).where(LegacyRecord.plate_normalized == plate)
            )
        ).scalar_one_or_none()

        if existing:
            existing.plate_raw = row.plate_raw or existing.plate_raw
            existing.plate_state = row.plate_state or existing.plate_state
            existing.owner_name = row.owner_name or existing.owner_name
            existing.permit_number = row.permit_number or existing.permit_number
            existing.permit_type = row.permit_type or existing.permit_type
            existing.permit_status = row.permit_status or existing.permit_status
            existing.lot_zone = row.lot_zone or existing.lot_zone
            existing.vehicle_color = row.vehicle_color or existing.vehicle_color
            existing.vehicle_make = row.vehicle_make or existing.vehicle_make
            existing.vehicle_model = row.vehicle_model or existing.vehicle_model
            existing.vehicle_year = row.vehicle_year or existing.vehicle_year
            existing.vehicle_description = row.vehicle_description or existing.vehicle_description
            existing.record_date = _parse_date(row.record_date) or existing.record_date
            existing.expiration_date = _parse_date(row.expiration_date) or existing.expiration_date
            existing.source = row.source or existing.source
            updated += 1
        else:
            record = LegacyRecord(
                plate_normalized=plate,
                plate_raw=row.plate_raw,
                plate_state=row.plate_state,
                owner_name=row.owner_name,
                permit_number=row.permit_number,
                permit_type=row.permit_type,
                permit_status=row.permit_status,
                lot_zone=row.lot_zone,
                vehicle_color=row.vehicle_color,
                vehicle_make=row.vehicle_make,
                vehicle_model=row.vehicle_model,
                vehicle_year=row.vehicle_year,
                vehicle_description=row.vehicle_description,
                record_date=_parse_date(row.record_date),
                expiration_date=_parse_date(row.expiration_date),
                source=row.source,
            )
            db.add(record)
            inserted += 1

    await db.commit()
    logger.info("legacy_bulk_import", inserted=inserted, updated=updated, skipped=skipped)
    return LegacyImportResult(inserted=inserted, updated=updated, skipped=skipped)


# ── XLSX Upload ──────────────────────────────────────────────────────────────


@router.post("/import-xlsx", response_model=LegacyImportResult)
async def import_xlsx(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_admin),
):
    import openpyxl

    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return LegacyImportResult(inserted=0, updated=0, skipped=0)

    headers = [str(h).strip() if h else "" for h in rows[0]]

    COLUMN_MAP = {
        "Permit Number": "permit_number",
        "Record Date": "record_date",
        "Location": "location",
        "Status": "status",
        "First Name": "first_name",
        "Last Name": "last_name",
        "Contact Type": "contact_type",
        "Vehicle Color": "vehicle_color",
        "Vehicle Make": "vehicle_make",
        "Vehicle Model": "vehicle_model",
        "Plate": "plate",
        "Plate State": "plate_state",
        "Vehicle Year": "vehicle_year",
        "Expiration Date": "expiration_date",
        "Owner": "owner",
    }

    inserted = 0
    updated = 0
    skipped = 0

    for row in rows[1:]:
        raw = dict(zip(headers, row))
        rec = {}
        for xlsx_col, key in COLUMN_MAP.items():
            rec[key] = raw.get(xlsx_col) or ""
            if rec[key] is None:
                rec[key] = ""

        plate_raw = str(rec.get("plate", ""))
        plate = _normalize_plate(plate_raw)
        if not plate:
            skipped += 1
            continue

        # Build fields
        owner = str(rec.get("owner", "")).strip()
        if not owner:
            first = str(rec.get("first_name", "")).strip()
            last = str(rec.get("last_name", "")).strip()
            owner = f"{first} {last}".strip() or plate

        color = str(rec.get("vehicle_color", "")).strip()
        make = str(rec.get("vehicle_make", "")).strip()
        model = str(rec.get("vehicle_model", "")).strip()
        year = str(rec.get("vehicle_year", "")).strip()
        vehicle_desc = " ".join(p for p in [color, year, make, model] if p and p != "UNKNOWN")

        # Clean location
        loc = str(rec.get("location", "")).strip()
        for prefix in ("_PARKING LOTS : ", "_PARKING LOTS", "PARKING LOTS : ", "PARKING LOTS"):
            if loc.upper().startswith(prefix):
                loc = loc[len(prefix):].strip()
                break
        loc = loc or "GENERAL"

        # Map contact type to permit type
        ct = str(rec.get("contact_type", "")).strip().lower()
        if "faculty" in ct or "staff" in ct:
            permit_type = "faculty"
        elif "visitor" in ct:
            permit_type = "visitor"
        else:
            permit_type = "student"

        # Map status
        raw_status = str(rec.get("status", "")).strip().lower()
        if raw_status in ("valid", "active"):
            status = "active"
        elif raw_status == "expired":
            status = "expired"
        elif raw_status in ("revoked", "suspended"):
            status = "revoked"
        else:
            status = "active"

        record_date = _parse_date(rec.get("record_date"))
        exp_date = _parse_date(rec.get("expiration_date"))

        existing = (
            await db.execute(
                select(LegacyRecord).where(LegacyRecord.plate_normalized == plate)
            )
        ).scalar_one_or_none()

        if existing:
            existing.plate_raw = plate_raw or existing.plate_raw
            existing.plate_state = str(rec.get("plate_state", "")).strip() or existing.plate_state
            existing.owner_name = owner or existing.owner_name
            existing.permit_number = str(rec.get("permit_number", "")).strip() or existing.permit_number
            existing.permit_type = permit_type
            existing.permit_status = status
            existing.lot_zone = loc
            existing.vehicle_color = color or existing.vehicle_color
            existing.vehicle_make = make or existing.vehicle_make
            existing.vehicle_model = model or existing.vehicle_model
            existing.vehicle_year = year or existing.vehicle_year
            existing.vehicle_description = vehicle_desc or existing.vehicle_description
            existing.record_date = record_date or existing.record_date
            existing.expiration_date = exp_date or existing.expiration_date
            updated += 1
        else:
            record = LegacyRecord(
                plate_normalized=plate,
                plate_raw=plate_raw,
                plate_state=str(rec.get("plate_state", "")).strip() or "PA",
                owner_name=owner,
                permit_number=str(rec.get("permit_number", "")).strip(),
                permit_type=permit_type,
                permit_status=status,
                lot_zone=loc,
                vehicle_color=color,
                vehicle_make=make,
                vehicle_model=model,
                vehicle_year=year,
                vehicle_description=vehicle_desc,
                record_date=record_date,
                expiration_date=exp_date,
                source="omnigo",
            )
            db.add(record)
            inserted += 1

    await db.commit()
    logger.info("legacy_xlsx_import", inserted=inserted, updated=updated, skipped=skipped)
    return LegacyImportResult(inserted=inserted, updated=updated, skipped=skipped)
