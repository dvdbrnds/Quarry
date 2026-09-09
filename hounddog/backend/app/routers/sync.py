import base64
import logging
import os
import uuid as uuid_mod
from datetime import date, datetime, timezone
from decimal import Decimal
from ..services.timeutils import today_local, to_local
from ..services.plate_utils import normalize_plate

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
from ..models.plate_correction import PlateCorrection
from ..models.lot import ParkingLot
from ..models.lot_closure import LotClosure
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


class SyncDiversion(BaseModel):
    closed_lot_name: str
    divert_to_lot_name: str
    reason: str = ""


class SyncDiversionsResponse(BaseModel):
    diversions: list[SyncDiversion]
    server_timestamp: datetime


@router.get("/diversions", response_model=SyncDiversionsResponse)
async def sync_diversions(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import aliased
    DivertLot = aliased(ParkingLot)

    result = await db.execute(
        select(ParkingLot.name, DivertLot.name, LotClosure.reason)
        .join(ParkingLot, LotClosure.lot_id == ParkingLot.id)
        .join(DivertLot, LotClosure.divert_to_lot_id == DivertLot.id)
        .where(
            LotClosure.status == "active",
            LotClosure.divert_to_lot_id.isnot(None),
        )
    )
    rows = result.all()
    return SyncDiversionsResponse(
        diversions=[
            SyncDiversion(closed_lot_name=closed, divert_to_lot_name=target, reason=reason or "")
            for closed, target, reason in rows
        ],
        server_timestamp=datetime.now(timezone.utc),
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
    # Warnings always have $0 fine regardless of violation type
    if ticket.is_warning:
        fine_amount = Decimal("0.00")
    else:
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

            if not ticket.is_warning and ticket.fine_amount is None:
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

    # Additional photos (stored as list of base64 strings in JSON column)
    additional_photos_data: list[dict] | None = None
    additional_photo_count = 0
    if ticket.additional_photos_base64:
        additional_photos_data = []
        for b64 in ticket.additional_photos_base64:
            additional_photos_data.append({
                "data": b64,
                "mime": "image/jpeg",
            })
        additional_photo_count = len(additional_photos_data)

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

    # Look up permit by plate to link ticket (try exact then normalized)
    permit_id = None
    owner_name = ticket.owner_name
    permit_number = ticket.permit_number
    permit_type_label = ticket.permit_type_label
    permit_lot_zone = ticket.permit_lot_zone
    raw_plate = ticket.plate.upper()
    norm_plate = normalize_plate(ticket.plate)
    permit_result = await db.execute(
        select(Permit).where(
            or_(
                Permit.plates.contains([raw_plate]),
                Permit.plates.contains([norm_plate]),
            )
        ).order_by(Permit.end_date.desc()).limit(1)
    )
    permit = permit_result.scalar()
    if permit:
        permit_id = permit.id
        if not owner_name:
            owner_name = permit.name
        if not permit_number:
            permit_number = permit.permit_number or permit.student_id
        if not permit_type_label:
            permit_type_label = permit.permit_type
        if not permit_lot_zone:
            permit_lot_zone = permit.lot_assignment

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
        permit_type_label=permit_type_label,
        permit_lot_zone=permit_lot_zone,
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
        ocr_original_plate=ticket.ocr_original_plate,
        additional_photo_count=additional_photo_count,
        additional_photos=additional_photos_data,
        status="warning" if ticket.is_warning else "issued",
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

    # Resolve notification email with multiple fallback strategies:
    # 1. permit.email directly
    # 2. Other permits with the same student_id
    # 3. Other permits with the same plate (handles imports without student_id)
    # 4. customer_email from Stripe sessions for this plate
    recipient_email: str | None = None
    if permit:
        _raw_email = getattr(permit, "email", None) or ""
        if "@" in _raw_email:
            recipient_email = _raw_email

        if not recipient_email and getattr(permit, "student_id", None):
            fallback_result = await db.execute(
                select(Permit.email).where(
                    Permit.student_id == permit.student_id,
                    Permit.email.isnot(None),
                    Permit.email != "",
                    Permit.email.contains("@"),
                ).limit(1)
            )
            recipient_email = fallback_result.scalar()

    if not recipient_email:
        plate_email_result = await db.execute(
            select(Permit.email).where(
                or_(
                    Permit.plates.contains([raw_plate]),
                    Permit.plates.contains([norm_plate]),
                ),
                Permit.email.isnot(None),
                Permit.email != "",
                Permit.email.contains("@"),
                Permit.deleted_at.is_(None),
            ).order_by(Permit.updated_at.desc()).limit(1)
        )
        recipient_email = plate_email_result.scalar()

    try:
        if recipient_email:
            vtype_label = ticket.violation_type or "Parking Violation"
            if ticket.violation_type:
                vt_row = await db.execute(
                    select(ViolationType.label).where(ViolationType.code == ticket.violation_type)
                )
                vt_label_row = vt_row.scalar()
                if vt_label_row:
                    vtype_label = vt_label_row
            email_ok = await send_citation_email(
                recipient_email=recipient_email,
                plate=new_ticket.plate,
                lot=new_ticket.lot or "",
                violation_label=vtype_label,
                fine_amount=str(fine_amount),
                payment_url=payment_url,
                officer_name=new_ticket.officer_name,
                issued_at=to_local(new_ticket.issued_at).strftime("%b %d, %Y %I:%M %p %Z") if new_ticket.issued_at else "",
                ticket_id=str(new_ticket.id),
            )
            if email_ok:
                notification_sent = True
                notification_email = recipient_email
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
                student_email=recipient_email or getattr(permit, 'email', None),
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


# ── Plate Corrections (officer-reported OCR misreads, no citation) ──────────


class PlateCorrectionUpload(BaseModel):
    ocr_plate: str
    correct_plate: str
    plate_state: str = ""
    lot: str = ""
    officer_name: str = ""
    officer_email: str = ""
    device_name: str = ""
    notes: str = ""


class PlateCorrectionResponse(BaseModel):
    status: str
    id: str


@router.post("/plate-correction", response_model=PlateCorrectionResponse)
async def submit_plate_correction(
    data: PlateCorrectionUpload,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    correction = PlateCorrection(
        ocr_plate=data.ocr_plate.upper().strip(),
        correct_plate=data.correct_plate.upper().strip(),
        plate_state=data.plate_state.upper().strip(),
        lot=data.lot,
        officer_name=data.officer_name,
        officer_email=data.officer_email,
        device_name=data.device_name or device.name,
        notes=data.notes,
    )
    db.add(correction)
    await db.flush()
    await db.refresh(correction)
    logger.info(
        "[PlateCorrection] %s -> %s by %s in %s",
        correction.ocr_plate, correction.correct_plate,
        correction.officer_email or "unknown", correction.lot,
    )
    return PlateCorrectionResponse(status="saved", id=str(correction.id))


# ── Vehicle Tag creation (from BirdDog) ────────────────────────────

class VehicleTagUpload(BaseModel):
    plates: list[str]
    owner_name: str = ""
    owner_address: str = ""
    student_name: str = ""
    student_email: str = ""
    vehicle_make: str = ""
    vehicle_model: str = ""
    vehicle_color: str = ""
    vehicle_year: str = ""
    source: str = "officer"
    notes: str = ""
    officer_name: str = ""
    officer_email: str = ""


class VehicleTagUploadResponse(BaseModel):
    status: str
    tag_id: str
    plates: list[str]


@router.post("/vehicle-tags", status_code=201, response_model=VehicleTagUploadResponse)
async def create_vehicle_tag_from_device(
    data: VehicleTagUpload,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    """Create a vehicle tag from BirdDog (officer in the field)."""
    if not data.plates:
        raise HTTPException(400, "At least one plate is required")

    normalized = [p.strip().upper().replace(" ", "").replace("-", "") for p in data.plates]
    vehicle_parts = [p for p in [data.vehicle_year, data.vehicle_color, data.vehicle_make, data.vehicle_model] if p]
    vehicle_desc = " ".join(vehicle_parts) if vehicle_parts else ""

    officer_info = ""
    if data.officer_name:
        officer_info = f"Tagged by {data.officer_name}"
        if data.officer_email:
            officer_info += f" ({data.officer_email})"
    notes = "\n".join(filter(None, [data.notes, officer_info])).strip()

    meta_parts = []
    if data.owner_address:
        meta_parts.append(f"owner_address:{data.owner_address.strip()[:256]}")
    if data.student_name:
        meta_parts.append(f"student_name:{data.student_name.strip()[:128]}")

    tag = Permit(
        name=data.owner_name or f"Unknown — {', '.join(normalized)}",
        plates=normalized,
        email=data.student_email.strip()[:256] if data.student_email else "",
        phone="",
        student_id="|".join(meta_parts) if meta_parts else "",
        permit_type="vehicle_tag",
        status="active",
        lot_assignment="",
        is_tag_only=True,
        vehicle_make=data.vehicle_make or None,
        vehicle_model=data.vehicle_model or None,
        vehicle_color=data.vehicle_color or None,
        vehicle_year=data.vehicle_year or None,
        vehicle_description=vehicle_desc,
        tag_notes=notes or None,
        tag_source=data.source or "officer",
        start_date=today_local(),
        end_date=today_local(),
    )
    db.add(tag)
    await db.flush()
    await db.refresh(tag)

    logger.info(
        "[VehicleTag] Created from device %s: plates=%s officer=%s",
        device.name, normalized, data.officer_name,
    )

    return VehicleTagUploadResponse(
        status="created",
        tag_id=str(tag.id),
        plates=normalized,
    )


class PlateCorrectionRead(BaseModel):
    id: str
    ocr_plate: str
    correct_plate: str
    plate_state: str
    lot: str
    officer_name: str
    officer_email: str
    device_name: str
    notes: str
    created_at: datetime

    class Config:
        from_attributes = True


@diagnostic_router.get("/plate-corrections", response_model=list[PlateCorrectionRead])
async def list_plate_corrections(
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    result = await db.execute(
        select(PlateCorrection).order_by(PlateCorrection.created_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return [
        PlateCorrectionRead(
            id=str(r.id),
            ocr_plate=r.ocr_plate,
            correct_plate=r.correct_plate,
            plate_state=r.plate_state or "",
            lot=r.lot or "",
            officer_name=r.officer_name or "",
            officer_email=r.officer_email or "",
            device_name=r.device_name or "",
            notes=r.notes or "",
            created_at=r.created_at,
        )
        for r in rows
    ]
