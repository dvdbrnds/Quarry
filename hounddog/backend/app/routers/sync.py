import base64
import os
import uuid as uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.api_key import get_device
from ..config import settings
from ..database import get_db
from ..models.academic_season import AcademicSeason
from ..models.device import Device
from ..models.enforcement_settings import EnforcementSettings
from ..models.lot import ParkingLot
from ..models.lot_zone import LotZone
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..schemas.lot import LotZoneRead
from ..schemas.sync import (
    PushTokenRegister,
    SyncCalendarResponse,
    SyncLotsResponse,
    SyncLotWithZones,
    SyncPermitsResponse,
    SyncSettingsResponse,
    SyncStatusResponse,
    SyncViolationTypesResponse,
    TicketUpload,
    TicketUploadResponse,
)
from ..services.email import send_citation_email
from ..websocket import manager

router = APIRouter()


@router.get("/permits", response_model=SyncPermitsResponse)
async def sync_permits(
    since: datetime | None = Query(None),
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    full_sync = since is None
    query = select(Permit)

    if since:
        query = query.where(
            or_(Permit.updated_at > since, Permit.deleted_at > since)
        )
    else:
        query = query.where(Permit.deleted_at.is_(None))

    permits = (await db.execute(query.order_by(Permit.updated_at))).scalars().all()

    return SyncPermitsResponse(
        permits=permits,
        server_timestamp=datetime.now(timezone.utc),
        full_sync=full_sync,
    )


@router.get("/lots", response_model=SyncLotsResponse)
async def sync_lots(
    since: datetime | None = Query(None),
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    full_sync = since is None
    query = select(ParkingLot)

    if since:
        query = query.where(
            or_(ParkingLot.updated_at > since, ParkingLot.deleted_at > since)
        )
    else:
        query = query.where(ParkingLot.deleted_at.is_(None))

    lots = (await db.execute(query.order_by(ParkingLot.updated_at))).scalars().all()

    result_lots = []
    for lot in lots:
        zones_result = await db.execute(
            select(LotZone).where(LotZone.lot_id == lot.id)
        )
        zones = zones_result.scalars().all()
        lot_data = SyncLotWithZones.model_validate(lot)
        lot_data.zones = [LotZoneRead.model_validate(z) for z in zones]
        result_lots.append(lot_data)

    return SyncLotsResponse(
        lots=result_lots,
        server_timestamp=datetime.now(timezone.utc),
        full_sync=full_sync,
    )


@router.get("/violation-types", response_model=SyncViolationTypesResponse)
async def sync_violation_types(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ViolationType)
        .where(ViolationType.is_active.is_(True))
        .order_by(ViolationType.sort_order)
    )
    return SyncViolationTypesResponse(
        violation_types=result.scalars().all(),
        server_timestamp=datetime.now(timezone.utc),
    )


@router.get("/calendar", response_model=SyncCalendarResponse)
async def sync_calendar(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AcademicSeason).order_by(AcademicSeason.start_date)
    )
    seasons = result.scalars().all()

    today = date.today()
    active = None
    for s in seasons:
        if s.start_date <= today <= s.end_date:
            active = s
            break

    if not active:
        for s in seasons:
            if s.is_default:
                active = s
                break

    return SyncCalendarResponse(
        seasons=seasons,
        active_season=active,
        server_timestamp=datetime.now(timezone.utc),
    )


@router.get("/settings", response_model=SyncSettingsResponse)
async def sync_settings(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = result.scalar()
    if not es:
        es = EnforcementSettings(id=1)
        db.add(es)
        await db.flush()
        await db.refresh(es)

    return SyncSettingsResponse(
        settings=es,
        server_timestamp=datetime.now(timezone.utc),
    )


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    permit_count = (
        await db.execute(
            select(func.count()).select_from(Permit).where(Permit.deleted_at.is_(None))
        )
    ).scalar() or 0

    lot_count = (
        await db.execute(
            select(func.count())
            .select_from(ParkingLot)
            .where(ParkingLot.deleted_at.is_(None))
        )
    ).scalar() or 0

    device_count = (
        await db.execute(select(func.count()).select_from(Device))
    ).scalar() or 0

    return SyncStatusResponse(
        server_time=datetime.now(timezone.utc),
        permit_count=permit_count,
        lot_count=lot_count,
        device_count=device_count,
    )


@router.post("/register-push", status_code=204)
async def register_push_token(
    body: PushTokenRegister,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    device.push_token = body.token
    await db.flush()


@router.post("/tickets", response_model=TicketUploadResponse, status_code=202)
async def upload_ticket(
    ticket: TicketUpload,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    # Look up violation type to determine fine
    fine_amount = ticket.fine_amount or Decimal("50.00")
    violation_type_id = None
    offense_number = 1

    if ticket.violation_type:
        vtype_result = await db.execute(
            select(ViolationType).where(
                ViolationType.code == ticket.violation_type,
                ViolationType.is_active.is_(True),
            )
        )
        vtype = vtype_result.scalar()

        if vtype:
            violation_type_id = vtype.id

            # Count prior offenses for escalation
            es_result = await db.execute(
                select(EnforcementSettings).where(EnforcementSettings.id == 1)
            )
            es = es_result.scalar()
            year_start_month = es.academic_year_start_month if es else 8
            year_start_day = es.academic_year_start_day if es else 1

            today = date.today()
            if today.month >= year_start_month and today.day >= year_start_day:
                academic_year_start = date(today.year, year_start_month, year_start_day)
            else:
                academic_year_start = date(today.year - 1, year_start_month, year_start_day)

            prior_count_result = await db.execute(
                select(func.count()).select_from(Ticket).where(
                    Ticket.plate == ticket.plate.upper(),
                    Ticket.violation_type == ticket.violation_type,
                    Ticket.issued_at >= datetime(
                        academic_year_start.year,
                        academic_year_start.month,
                        academic_year_start.day,
                        tzinfo=timezone.utc,
                    ),
                    Ticket.status.notin_(["voided"]),
                )
            )
            prior_count = prior_count_result.scalar() or 0
            offense_number = prior_count + 1

            if ticket.fine_amount is None:
                if offense_number >= 3 and vtype.fine_third_plus:
                    fine_amount = vtype.fine_third_plus
                elif offense_number == 2 and vtype.fine_second:
                    fine_amount = vtype.fine_second
                else:
                    fine_amount = vtype.fine_first

    # Handle photo upload
    photo_url = None
    if ticket.photo_base64:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "photos")
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"{uuid_mod.uuid4()}.jpg"
        filepath = os.path.join(upload_dir, filename)
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(ticket.photo_base64))
        photo_url = f"/uploads/photos/{filename}"

    officer_id = ticket.officer_email or ticket.officer_name or device.name

    # Look up permit by plate to link ticket
    permit_id = None
    owner_name = ticket.owner_name
    permit_number = ticket.permit_number
    permit_result = await db.execute(
        select(Permit).where(
            Permit.plates.contains([ticket.plate.upper()])
        ).order_by(Permit.end_date.desc()).limit(1)
    )
    permit = permit_result.scalar()
    if permit:
        permit_id = permit.id
        if not owner_name:
            owner_name = permit.name
        if not permit_number:
            permit_number = permit.student_id

    new_ticket = Ticket(
        plate=ticket.plate.upper(),
        permit_id=permit_id,
        lot=ticket.lot,
        zone=ticket.zone,
        violation_type=ticket.violation_type or "unknown",
        violation_type_id=violation_type_id,
        fine_amount=fine_amount,
        photo_url=photo_url,
        officer_id=officer_id,
        officer_name=ticket.officer_name,
        officer_email=ticket.officer_email,
        owner_name=owner_name,
        permit_number=permit_number,
        issued_at=ticket.timestamp,
        ticket_category=ticket.ticket_category,
        offense_number=offense_number,
        location_lat=ticket.location_lat,
        location_lng=ticket.location_lng,
        location_text=ticket.location_text,
        vehicle_description=ticket.vehicle_description,
        officer_notes=ticket.officer_notes,
        driver_name=ticket.driver_name,
        driver_license=ticket.driver_license,
    )
    db.add(new_ticket)
    await db.flush()
    await db.refresh(new_ticket)

    await manager.broadcast("ticket_created", {
        "id": str(new_ticket.id),
        "plate": new_ticket.plate,
        "lot": new_ticket.lot,
        "status": new_ticket.status,
        "violation_type": new_ticket.violation_type,
        "ticket_category": new_ticket.ticket_category,
    })

    payment_url = f"{settings.public_url}/pay?ticket={new_ticket.id}"

    try:
        if permit and getattr(permit, "email", None):
            vtype_label = ticket.violation_type or "Parking Violation"
            if ticket.violation_type:
                vt_row = await db.execute(
                    select(ViolationType.label).where(ViolationType.code == ticket.violation_type)
                )
                vt_label_row = vt_row.scalar()
                if vt_label_row:
                    vtype_label = vt_label_row
            await send_citation_email(
                recipient_email=permit.email,
                plate=new_ticket.plate,
                lot=new_ticket.lot or "",
                violation_label=vtype_label,
                fine_amount=str(fine_amount),
                payment_url=payment_url,
                officer_name=new_ticket.officer_name,
                issued_at=new_ticket.issued_at.strftime("%b %d, %Y %I:%M %p") if new_ticket.issued_at else "",
                ticket_id=str(new_ticket.id),
            )
    except Exception as e:
        import logging
        logging.getLogger("quarry.sync").warning("Citation email failed (non-fatal): %s", e)

    return TicketUploadResponse(
        status="accepted",
        ticket_id=new_ticket.id,
        payment_url=payment_url,
        fine_amount=fine_amount,
        offense_number=offense_number,
    )
