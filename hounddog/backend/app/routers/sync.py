import base64
import logging
import os
import uuid as uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal
from ..services.timeutils import today_local

logger = logging.getLogger("quarry.sync")

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.api_key import get_device
from ..auth.okta import OktaUser, require_admin
from ..config import settings
from ..database import get_db
from ..models.academic_season import AcademicSeason
from ..models.device import Device
from ..models.enforcement_settings import EnforcementSettings
from ..models.lot import ParkingLot
from ..models.lot_zone import LotZone
from ..models.parking_spot import ParkingSpot
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..schemas.lot import LotZoneRead
from ..schemas.parking_spot import SpotRead
from ..models.resident_plate import ResidentPlate
from ..schemas.sync import (
    PushTokenRegister,
    SyncCalendarResponse,
    SyncLotsResponse,
    SyncLotWithZones,
    SyncPermitsResponse,
    SyncResidentPlatesResponse,
    SyncSettingsResponse,
    SyncStatusResponse,
    SyncViolationTypesResponse,
    TicketUpload,
    TicketUploadResponse,
)
from ..services.email import send_citation_email

router = APIRouter()
diagnostic_router = APIRouter()


@diagnostic_router.get("/ticket-test")
async def ticket_creation_test(
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_admin()),
):
    """Public endpoint that tests every step of ticket creation without actually creating one."""
    import traceback
    steps = {}

    # Step 1: Can we query ViolationType?
    try:
        vt_result = await db.execute(
            select(ViolationType).where(
                ViolationType.code == "no_permit",
                ViolationType.is_active.is_(True),
            )
        )
        vtype = vt_result.scalar()
        steps["violation_type_query"] = f"ok (found={'yes' if vtype else 'no'})"
    except Exception as e:
        steps["violation_type_query"] = f"FAILED: {e}"
        steps["violation_type_traceback"] = traceback.format_exc()

    # Step 2: Can we query EnforcementSettings?
    try:
        es_result = await db.execute(
            select(EnforcementSettings).where(EnforcementSettings.id == 1)
        )
        es = es_result.scalar()
        steps["enforcement_settings"] = f"ok (found={'yes' if es else 'no'})"
    except Exception as e:
        steps["enforcement_settings"] = f"FAILED: {e}"

    # Step 3: Can we query Permit?
    try:
        p_result = await db.execute(
            select(Permit).limit(1)
        )
        p = p_result.scalar()
        steps["permit_query"] = f"ok (has_permits={'yes' if p else 'no'})"
    except Exception as e:
        steps["permit_query"] = f"FAILED: {e}"
        steps["permit_traceback"] = traceback.format_exc()

    # Step 4: Can we query Ticket (count)?
    try:
        tc_result = await db.execute(
            select(func.count()).select_from(Ticket)
        )
        tc = tc_result.scalar()
        steps["ticket_count"] = f"ok (count={tc})"
    except Exception as e:
        steps["ticket_count"] = f"FAILED: {e}"
        steps["ticket_traceback"] = traceback.format_exc()

    # Step 5: Can we create and rollback a test ticket?
    try:
        test_ticket = Ticket(
            plate="DIAG_TEST",
            lot="test",
            violation_type="no_permit",
            fine_amount=Decimal("0.00"),
            officer_id="diagnostic",
            ticket_category="parking",
        )
        db.add(test_ticket)
        await db.flush()
        test_id = str(test_ticket.id)
        await db.rollback()
        steps["ticket_insert"] = f"ok (test_id={test_id})"
    except Exception as e:
        steps["ticket_insert"] = f"FAILED: {e}"
        steps["ticket_insert_traceback"] = traceback.format_exc()
        try:
            await db.rollback()
        except Exception:
            pass

    # Step 6: Check public_url and list actual tickets
    steps["public_url"] = settings.public_url
    try:
        tickets_result = await db.execute(
            select(
                Ticket.id, Ticket.plate, Ticket.status, Ticket.issued_at
            ).order_by(Ticket.issued_at.desc()).limit(5)
        )
        recent = []
        for row in tickets_result.fetchall():
            tid = str(row[0])
            recent.append({
                "id": tid,
                "plate": row[1],
                "status": row[2],
                "issued_at": str(row[3]),
                "payment_url": f"{settings.student_facing_url}/pay?ticket={tid}",
            })
        steps["recent_tickets"] = recent
    except Exception as e:
        steps["recent_tickets"] = f"FAILED: {e}"

    # Step 7: Check column existence on tickets table
    try:
        from sqlalchemy import text
        col_result = await db.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'tickets' ORDER BY ordinal_position"
        ))
        cols = [r[0] for r in col_result.fetchall()]
        steps["ticket_columns"] = cols
    except Exception as e:
        steps["ticket_columns"] = f"FAILED: {e}"

    return {"steps": steps}


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


@router.get("/resident-plates", response_model=SyncResidentPlatesResponse)
async def sync_resident_plates(
    since: datetime | None = Query(None),
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    full_sync = since is None
    query = select(ResidentPlate)
    if since:
        query = query.where(ResidentPlate.created_at > since)
    plates = (await db.execute(query.order_by(ResidentPlate.created_at))).scalars().all()
    return SyncResidentPlatesResponse(
        resident_plates=plates,
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

        spots_result = await db.execute(
            select(ParkingSpot).where(ParkingSpot.lot_id == lot.id).order_by(ParkingSpot.number)
        )
        spots = spots_result.scalars().all()

        lot_data = SyncLotWithZones.model_validate(lot)
        lot_data.zones = [LotZoneRead.model_validate(z) for z in zones]
        lot_data.spots = [SpotRead.model_validate(s) for s in spots]
        result_lots.append(lot_data)

    return SyncLotsResponse(
        lots=result_lots,
        server_timestamp=datetime.now(timezone.utc),
        full_sync=full_sync,
    )


class OccupancyReport(BaseModel):
    sensor_id: str
    type: str = "occupancy"
    payload: str  # "occupied" or "vacant"
    rssi: int | None = None
    timestamp: str | None = None


class OccupancyResponse(BaseModel):
    accepted: int = 0
    unknown: list[str] = []


@router.post("/occupancy", response_model=OccupancyResponse)
async def report_occupancy(
    reports: list[OccupancyReport],
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    """Gateway POSTs batched occupancy readings from SheepDog pucks."""
    accepted = 0
    unknown = []

    for report in reports:
        result = await db.execute(
            select(ParkingSpot).where(ParkingSpot.sensor_id == report.sensor_id)
        )
        spot = result.scalar_one_or_none()
        if not spot:
            unknown.append(report.sensor_id)
            continue
        accepted += 1

    await db.flush()
    logger.info("[SheepDog] Occupancy from %s: %d accepted, %d unknown", device.name, accepted, len(unknown))
    return OccupancyResponse(accepted=accepted, unknown=unknown)


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

    today = today_local()
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
        student_facing_url=settings.student_facing_url,
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


@router.post("/tickets", status_code=202)
async def upload_ticket(
    ticket: TicketUpload,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
) -> TicketUploadResponse:
    import logging as _logging
    import traceback as _tb
    _log = _logging.getLogger("quarry.sync")
    try:
        return await _upload_ticket_impl(ticket, device, db)
    except Exception as exc:
        _log.error("upload_ticket FAILED: %s\n%s", exc, _tb.format_exc())
        raise HTTPException(status_code=500, detail=f"Ticket creation failed: {exc}")


async def _upload_ticket_impl(
    ticket: TicketUpload,
    device: Device,
    db: AsyncSession,
) -> TicketUploadResponse:
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

            today = today_local()
            if (today.month > year_start_month) or (today.month == year_start_month and today.day >= year_start_day):
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

    # Handle photo upload — store in DB
    photo_url = None
    photo_data = None
    photo_mime = None
    if ticket.photo_base64:
        photo_data = base64.b64decode(ticket.photo_base64)
        photo_mime = "image/jpeg"

    officer_id = ticket.officer_email or ticket.officer_name or device.name

    # Duplicate ticket prevention: reject if same plate has an open ticket
    # in the same lot within the last 4 hours (they haven't moved)
    from datetime import timedelta as _td
    dupe_cutoff = datetime.now(timezone.utc) - _td(hours=4)
    dupe_result = await db.execute(
        select(Ticket).where(
            Ticket.plate == ticket.plate.upper(),
            Ticket.lot == ticket.lot,
            Ticket.issued_at >= dupe_cutoff,
            Ticket.status.notin_(["voided", "paid"]),
        ).limit(1)
    )
    existing_ticket = dupe_result.scalar()
    if existing_ticket:
        payment_url = f"{settings.student_facing_url}/pay?ticket={existing_ticket.id}" if settings.student_facing_url else ""
        return TicketUploadResponse(
            status="duplicate",
            ticket_id=existing_ticket.id,
            payment_url=payment_url,
            fine_amount=existing_ticket.fine_amount or Decimal("0"),
            offense_number=existing_ticket.offense_number or 1,
            notification_sent=False,
            notification_email=None,
        )

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
            permit_number = permit.permit_number or permit.student_id

    from ..services.ticket_numbering import next_ticket_number
    ticket_kwargs: dict = dict(
        ticket_number=await next_ticket_number(db),
        plate=ticket.plate.upper(),
        permit_id=permit_id,
        lot=ticket.lot,
        zone=ticket.zone,
        violation_type=ticket.violation_type or "unknown",
        violation_type_id=violation_type_id,
        fine_amount=fine_amount,
        photo_url=None,
        photo_data=photo_data,
        photo_mime=photo_mime,
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
    if ticket.client_ticket_id:
        ticket_kwargs["id"] = ticket.client_ticket_id
    new_ticket = Ticket(**ticket_kwargs)
    db.add(new_ticket)
    await db.flush()
    await db.refresh(new_ticket)

    if photo_data:
        new_ticket.photo_url = f"/api/tickets/{new_ticket.id}/photo"
        await db.flush()

    payment_url = f"{settings.student_facing_url}/pay?ticket={new_ticket.id}"

    notification_sent = False
    notification_email: str | None = None

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
            email_ok = await send_citation_email(
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
            if email_ok:
                notification_sent = True
                notification_email = permit.email
    except Exception as e:
        import logging
        logging.getLogger("quarry.sync").warning("Citation email failed (non-fatal): %s", e)

    try:
        if permit and getattr(permit, 'student_id', None):
            from ..services.escalation import check_and_escalate
            await check_and_escalate(
                db=db,
                plate=new_ticket.plate,
                student_id=permit.student_id,
                student_name=permit.name,
                student_email=getattr(permit, 'email', None),
            )
    except Exception as e:
        logger.warning("Escalation check failed (non-fatal): %s", e)

    return TicketUploadResponse(
        status="accepted",
        ticket_id=new_ticket.id,
        payment_url=payment_url,
        fine_amount=fine_amount,
        offense_number=offense_number,
        notification_sent=notification_sent,
        notification_email=notification_email,
    )
