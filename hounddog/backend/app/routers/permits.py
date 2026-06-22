import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, or_, desc, asc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user
from ..database import get_db
from ..models.audit_log import AuditLog
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.ticket import Ticket
from ..models.payment import Payment
from ..schemas.permit import (
    PermitCreate,
    PermitList,
    PermitRead,
    PermitUpdate,
    PermitImportPayload,
    PermitImportResult,
)
from ..services.permit_lifecycle import (
    compute_hold,
    find_duplicates,
    get_permit_stats,
)
from ..websocket import manager

router = APIRouter(dependencies=[Depends(get_current_user)])

SORTABLE_FIELDS = {
    "name": Permit.name,
    "student_id": Permit.student_id,
    "status": Permit.status,
    "permit_type": Permit.permit_type,
    "lot_assignment": Permit.lot_assignment,
    "start_date": Permit.start_date,
    "end_date": Permit.end_date,
    "created_at": Permit.created_at,
}


@router.get("/stats")
async def permit_stats(db: AsyncSession = Depends(get_db)):
    return await get_permit_stats(db)


@router.get("/duplicates")
async def list_duplicates(db: AsyncSession = Depends(get_db)):
    """Find all active permits that share a plate with another active permit."""
    result = await db.execute(
        select(Permit).where(Permit.status == "active", Permit.deleted_at.is_(None))
    )
    all_permits = result.scalars().all()

    plate_map: dict[str, list] = {}
    for p in all_permits:
        for plate in p.plates:
            plate_map.setdefault(plate.upper(), []).append(p)

    duplicates = []
    seen_ids = set()
    for plate, permits in plate_map.items():
        if len(permits) > 1:
            for p in permits:
                if p.id not in seen_ids:
                    seen_ids.add(p.id)
                    duplicates.append({
                        "id": str(p.id),
                        "name": p.name,
                        "plates": p.plates,
                        "conflicting_plate": plate,
                        "lot_assignment": p.lot_assignment,
                        "permit_type": p.permit_type,
                    })
    return duplicates


@router.get("", response_model=PermitList)
async def list_permits(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    permit_type: str | None = None,
    sort: str | None = None,
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
        if status == "expiring_soon":
            today = date.today()
            soon = today + timedelta(days=30)
            query = query.where(
                Permit.status == "active",
                Permit.end_date.isnot(None),
                Permit.end_date <= soon,
                Permit.end_date >= today,
            )
        else:
            query = query.where(Permit.status == status)
    if lot:
        query = query.where(Permit.lot_assignment == lot)
    if permit_type:
        query = query.where(Permit.permit_type == permit_type)

    order_col = Permit.name
    order_dir = asc
    if sort:
        if sort.startswith("-"):
            order_dir = desc
            sort_field = sort[1:]
        else:
            sort_field = sort
        if sort_field in SORTABLE_FIELDS:
            order_col = SORTABLE_FIELDS[sort_field]

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(order_dir(order_col)).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    return PermitList(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=PermitRead, status_code=201)
async def create_permit(data: PermitCreate, db: AsyncSession = Depends(get_db)):
    permit = Permit(**data.model_dump())
    db.add(permit)
    await db.flush()
    await db.refresh(permit)
    await _notify_permit_change("created", 1)
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
    await _notify_permit_change("updated", 1)
    return permit


@router.delete("/{permit_id}", status_code=204)
async def delete_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    permit.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await _notify_permit_change("deleted", 1)


class BulkStatusRequest(BaseModel):
    ids: list[str]
    status: str


@router.post("/bulk-status")
async def bulk_status(
    data: BulkStatusRequest, db: AsyncSession = Depends(get_db)
):
    valid_statuses = {"active", "expired", "revoked", "suspended"}
    if data.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    updated = 0
    for permit_id in data.ids:
        try:
            permit = await db.get(Permit, uuid.UUID(permit_id))
        except ValueError:
            continue
        if permit and not permit.deleted_at:
            permit.status = data.status
            updated += 1

    await db.flush()
    if updated:
        await _notify_permit_change("bulk_status", updated)
    return {"updated": updated, "status": data.status}


@router.post("/{permit_id}/renew", response_model=PermitRead)
async def renew_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    old = await db.get(Permit, permit_id)
    if not old or old.deleted_at:
        raise HTTPException(404, "Permit not found")

    old.status = "renewed"

    valid_days = 365
    if old.permit_type:
        pt_result = await db.execute(
            select(PermitType).where(PermitType.code == old.permit_type)
        )
        pt = pt_result.scalar()
        if pt and pt.valid_days:
            valid_days = pt.valid_days

    new_start = date.today()
    new_end = new_start + timedelta(days=valid_days)

    renewed = Permit(
        name=old.name,
        student_id=old.student_id,
        plates=list(old.plates),
        lot_assignment=old.lot_assignment,
        permit_type=old.permit_type,
        beacon_id=old.beacon_id,
        start_date=new_start,
        end_date=new_end,
        status="active",
    )
    db.add(renewed)
    await db.flush()
    await db.refresh(renewed)
    await _notify_permit_change("renewed", 1)
    return renewed


@router.get("/{permit_id}/history")
async def permit_history(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    has_hold, unpaid_amount = await compute_hold(db, permit)

    tickets_result = await db.execute(
        select(Ticket).where(
            Ticket.plate.in_(permit.plates)
        ).order_by(desc(Ticket.issued_at)).limit(50)
    )
    tickets = tickets_result.scalars().all()

    payments_result = await db.execute(
        select(Payment).where(
            Payment.ticket_id.in_([t.id for t in tickets])
        ).order_by(desc(Payment.created_at))
    )
    payments = payments_result.scalars().all()

    audit_result = await db.execute(
        select(AuditLog).where(
            AuditLog.resource_type == "permits",
            AuditLog.resource_id == str(permit_id),
        ).order_by(desc(AuditLog.timestamp)).limit(50)
    )
    audit_entries = audit_result.scalars().all()

    prior_result = await db.execute(
        select(Permit).where(
            Permit.id != permit_id,
            Permit.deleted_at.is_(None),
            or_(
                Permit.student_id == permit.student_id,
                *[Permit.plates.any(p) for p in permit.plates]
            ) if permit.student_id else
            or_(*[Permit.plates.any(p) for p in permit.plates])
        ).order_by(desc(Permit.created_at)).limit(20)
    )
    prior_permits = prior_result.scalars().all()

    duplicates = await find_duplicates(db, permit.plates, exclude_id=permit.id)

    return {
        "permit": permit,
        "has_hold": has_hold,
        "unpaid_amount": str(unpaid_amount),
        "tickets": [
            {
                "id": str(t.id),
                "plate": t.plate,
                "lot": t.lot,
                "violation_type": t.violation_type,
                "fine_amount": str(t.fine_amount),
                "status": t.status,
                "issued_at": t.issued_at.isoformat() if t.issued_at else None,
            }
            for t in tickets
        ],
        "payments": [
            {
                "id": str(p.id),
                "ticket_id": str(p.ticket_id),
                "amount": str(p.amount),
                "method": p.method,
                "status": "paid",
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ],
        "audit_log": [
            {
                "id": str(a.id),
                "timestamp": a.timestamp.isoformat(),
                "user_email": a.user_email,
                "action": a.action,
                "summary": a.summary,
                "changes": a.changes,
            }
            for a in audit_entries
        ],
        "prior_permits": [
            {
                "id": str(p.id),
                "name": p.name,
                "permit_type": p.permit_type,
                "status": p.status,
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "end_date": p.end_date.isoformat() if p.end_date else None,
            }
            for p in prior_permits
        ],
        "duplicates": duplicates,
    }


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
            if row.email:
                existing.email = row.email
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
                email=row.email or None,
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
    if inserted + updated > 0:
        await _notify_permit_change("imported", inserted + updated)
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
                email=row.get("email") or None,
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
    if inserted + updated > 0:
        await _notify_permit_change("imported", inserted + updated)
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
        "id", "student_id", "name", "email", "plates", "lot_assignment",
        "permit_type", "status", "start_date", "end_date",
    ])
    for p in permits:
        writer.writerow([
            str(p.id), p.student_id, p.name, p.email or "",
            ";".join(p.plates), p.lot_assignment, p.permit_type, p.status,
            p.start_date.isoformat() if p.start_date else "",
            p.end_date.isoformat() if p.end_date else "",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=permits.csv"},
    )


@router.get("/duplicates")
async def list_duplicate_permits(db: AsyncSession = Depends(get_db)):
    """Return groups of active permits that share at least one plate."""
    result = await db.execute(
        select(Permit).where(Permit.status == "active", Permit.deleted_at.is_(None))
    )
    active = result.scalars().all()

    plate_map: dict[str, list[Permit]] = {}
    for permit in active:
        for plate in permit.plates:
            key = plate.upper().strip()
            if key:
                plate_map.setdefault(key, []).append(permit)

    groups: list[dict] = []
    seen_ids: set = set()
    for plate, permits_for_plate in plate_map.items():
        if len(permits_for_plate) < 2:
            continue
        ids = tuple(sorted(str(p.id) for p in permits_for_plate))
        if ids in seen_ids:
            continue
        seen_ids.add(ids)
        groups.append({
            "shared_plate": plate,
            "permits": [
                {
                    "id": str(p.id),
                    "name": p.name,
                    "student_id": p.student_id,
                    "plates": p.plates,
                    "lot_assignment": p.lot_assignment,
                    "permit_type": p.permit_type,
                    "status": p.status,
                }
                for p in permits_for_plate
            ],
        })

    return {"duplicate_groups": groups, "total": len(groups)}


async def _notify_permit_change(action: str, count: int):
    """Broadcast permit change to WebSocket clients and send APNs push to devices."""
    await manager.broadcast("permit_changed", {"action": action, "count": count})
    from ..services.apns import send_permit_push
    await send_permit_push(action, count)
