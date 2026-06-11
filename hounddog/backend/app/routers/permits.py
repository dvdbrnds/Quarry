import csv
import io
import uuid
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.permit import Permit
from ..schemas.permit import (
    PermitCreate,
    PermitList,
    PermitRead,
    PermitUpdate,
    PermitImportPayload,
    PermitImportResult,
)

router = APIRouter()


@router.get("", response_model=PermitList)
async def list_permits(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Permit).where(Permit.deleted_at.is_(None))

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                Permit.name.ilike(like),
                Permit.student_id.ilike(like),
                Permit.plates.any(search.upper()),
            )
        )
    if status:
        query = query.where(Permit.status == status)
    if lot:
        query = query.where(Permit.lot_assignment == lot)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(Permit.name).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    return PermitList(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=PermitRead, status_code=201)
async def create_permit(data: PermitCreate, db: AsyncSession = Depends(get_db)):
    permit = Permit(**data.model_dump())
    db.add(permit)
    await db.flush()
    await db.refresh(permit)
    return permit


@router.get("/{permit_id}", response_model=PermitRead)
async def get_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    return permit


@router.put("/{permit_id}", response_model=PermitRead)
async def update_permit(
    permit_id: uuid.UUID, data: PermitUpdate, db: AsyncSession = Depends(get_db)
):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(permit, field, value)

    await db.flush()
    await db.refresh(permit)
    return permit


@router.delete("/{permit_id}", status_code=204)
async def delete_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    permit.deleted_at = datetime.now(timezone.utc)
    await db.flush()


@router.post("/import", response_model=PermitImportResult)
async def import_permits(
    payload: PermitImportPayload, db: AsyncSession = Depends(get_db)
):
    inserted = 0
    updated = 0
    skipped = 0

    for row in payload.permits:
        plate = row.plate_normalized.upper().strip()
        if not plate:
            skipped += 1
            continue

        existing = (
            await db.execute(
                select(Permit).where(
                    Permit.plates.any(plate), Permit.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if existing:
            if row.owner_name and row.owner_name != existing.name:
                existing.name = row.owner_name
            if row.lot_zone:
                existing.lot_assignment = row.lot_zone
            if row.permit_type:
                existing.permit_type = row.permit_type
            if row.permit_status:
                existing.status = row.permit_status
            updated += 1
        else:
            start = None
            if row.issued_date:
                try:
                    start = date.fromisoformat(row.issued_date)
                except ValueError:
                    start = None

            end = None
            if row.expiration_date:
                try:
                    end = date.fromisoformat(row.expiration_date)
                except ValueError:
                    end = None

            permit = Permit(
                name=row.owner_name or plate,
                plates=[plate],
                lot_assignment=row.lot_zone,
                permit_type=row.permit_type,
                status=row.permit_status,
                student_id=row.permit_number,
                start_date=start or date.today(),
                end_date=end,
            )
            db.add(permit)
            inserted += 1

    await db.flush()
    return PermitImportResult(inserted=inserted, updated=updated, skipped=skipped)


@router.post("/import-csv", response_model=PermitImportResult)
async def import_permits_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    inserted = 0
    updated = 0
    skipped = 0

    for row in reader:
        plate = (row.get("plate_normalized") or row.get("plate", "")).upper().strip()
        if not plate:
            skipped += 1
            continue

        existing = (
            await db.execute(
                select(Permit).where(
                    Permit.plates.any(plate), Permit.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if existing:
            updated += 1
        else:
            end = None
            exp_str = row.get("expiration_date", "")
            if exp_str:
                try:
                    end = date.fromisoformat(exp_str)
                except ValueError:
                    end = None

            permit = Permit(
                name=row.get("owner_name", plate),
                plates=[plate],
                lot_assignment=row.get("lot_zone", ""),
                permit_type=row.get("permit_type", "student"),
                status=row.get("permit_status", "active"),
                student_id=row.get("permit_number", ""),
                start_date=date.today(),
                end_date=end,
            )
            db.add(permit)
            inserted += 1

    await db.flush()
    return PermitImportResult(inserted=inserted, updated=updated, skipped=skipped)


@router.get("/export/csv")
async def export_permits(db: AsyncSession = Depends(get_db)):
    permits = (
        await db.execute(
            select(Permit).where(Permit.deleted_at.is_(None)).order_by(Permit.name)
        )
    ).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "student_id", "name", "plates", "lot_assignment",
        "permit_type", "status", "start_date", "end_date",
    ])
    for p in permits:
        writer.writerow([
            str(p.id), p.student_id, p.name, ";".join(p.plates),
            p.lot_assignment, p.permit_type, p.status,
            p.start_date.isoformat() if p.start_date else "",
            p.end_date.isoformat() if p.end_date else "",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=permits.csv"},
    )
