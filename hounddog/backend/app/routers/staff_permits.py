"""Staff/faculty self-service vehicle enrollment — no lottery, no cost."""

import asyncio
import logging
import uuid
from datetime import date, datetime, timezone

import sentry_sdk
from fastapi import APIRouter, Depends, HTTPException
from ..utils.safe_router import SafeRouter
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, get_current_user_or_impersonated, FACULTY_STAFF_OKTA_GROUPS

logger = logging.getLogger(__name__)
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..services.permit_numbering import next_permit_number
from ..services.timeutils import today_local


router = SafeRouter()


STAFF_PERMIT_CODE = "faculty_staff"


class VehicleEnroll(BaseModel):
    name: str
    plate: str
    plate_state: str = ""


class VehicleRead(BaseModel):
    id: str
    permit_number: str | None
    name: str
    email: str | None
    plate: str
    lot_assignment: str
    status: str
    start_date: str
    end_date: str | None
    permit_type: str = ""
    permit_type_label: str = ""


class AvailableStaffPermit(BaseModel):
    id: str
    code: str
    label: str
    eligible: str
    lot_assignments: list[str]
    valid_days: int


@router.get("/available", response_model=list[AvailableStaffPermit])
async def available_staff_permits(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Return the faculty/staff permit type(s) available for enrollment."""
    result = await db.execute(
        select(PermitType).where(
            PermitType.is_active.is_(True),
            PermitType.code == STAFF_PERMIT_CODE,
        )
    )
    types = result.scalars().all()
    return [
        AvailableStaffPermit(
            id=str(pt.id),
            code=pt.code,
            label=pt.label,
            eligible=pt.eligible,
            lot_assignments=pt.lot_assignments,
            valid_days=pt.valid_days,
        )
        for pt in types
    ]


async def _employee_basis(user: OktaUser, db: AsyncSession) -> str | None:
    """Why this person counts as an employee, or None. Okta groups are missing for some
    real employees (e.g. IT/admin accounts), so fall back to what the office already knows."""
    if user.is_staff or user.is_office:
        return "okta_group"
    email = (user.email or "").lower()
    if email:
        from .housing_overrides import get_classification_override_by_email, override_is_faculty_staff
        override = await get_classification_override_by_email(email, db)
        if override and override_is_faculty_staff(override):
            return "classification_override"
        has_staff_permit = (await db.execute(
            select(Permit.id).where(
                func.lower(Permit.email) == email,
                Permit.permit_type == STAFF_PERMIT_CODE,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            ).limit(1)
        )).first()
        if has_staff_permit:
            return "existing_staff_permit"
    from .student_permits import _extract_moravian_id
    moravian_id = _extract_moravian_id(user)
    if moravian_id and settings.sis_mssql_host:
        try:
            from ..services.sis_student_data import lookup_student_parking_data
            sis = await asyncio.wait_for(lookup_student_parking_data(moravian_id), timeout=8)
            # Current resident/commuter students stay students even if SIS flags them as employees (RAs, work-study).
            if sis and sis.employee and sis.housing_status not in ("R", "C"):
                return "sis_employee"
        except Exception as e:
            sentry_sdk.capture_exception(e)
    return None


@router.post("/enroll", response_model=VehicleRead, status_code=201)
async def enroll_vehicle(
    data: VehicleEnroll,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Register a vehicle — creates a permit immediately (no lottery, no cost)."""
    basis = await _employee_basis(user, db)
    if basis and basis != "okta_group":
        logger.info("Staff permit allowed for %s via %s (Okta groups: %s)", user.email, basis, user.groups)
    if not basis:
        logger.warning(
            "Staff permit denied for %s (sub=%s) — groups: %s | matched faculty/staff: %s",
            user.email, user.sub, user.groups,
            set(user.groups) & FACULTY_STAFF_OKTA_GROUPS,
        )
        raise HTTPException(
            403,
            "Faculty/staff permits are only available to Moravian employees. "
            "Students should apply for a permit through the student parking portal."
        )

    pt_result = await db.execute(
        select(PermitType).where(
            PermitType.code == STAFF_PERMIT_CODE,
            PermitType.is_active.is_(True),
        )
    )
    pt = pt_result.scalar()
    if not pt:
        raise HTTPException(404, "Staff/faculty permit type not configured")

    plate = data.plate.upper().strip()
    if not plate:
        raise HTTPException(400, "License plate is required")

    # Check if this plate is already on an active faculty/staff permit
    plate_exists = await db.execute(
        select(Permit).where(
            Permit.plates.any(plate),
            Permit.permit_type == STAFF_PERMIT_CODE,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    if plate_exists.scalar():
        raise HTTPException(409, f"Plate {plate} is already registered for a faculty/staff permit")

    # Check if this user already has an active faculty/staff permit —
    # if so, add the plate to it instead of creating a new permit
    from sqlalchemy import or_
    existing_permit_result = await db.execute(
        select(Permit).where(
            or_(Permit.student_id == user.sub, Permit.email == user.email),
            Permit.permit_type == STAFF_PERMIT_CODE,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        ).order_by(Permit.created_at.asc()).limit(1)
    )
    existing_permit = existing_permit_result.scalar()

    if existing_permit:
        # Add plate to existing permit
        existing_permit.plates = [*existing_permit.plates, plate]
        existing_permit.last_plate_change = datetime.now(timezone.utc)
        await db.flush()
        await db.refresh(existing_permit)
        from ..services.tag_upgrade import retire_tags_for_plates
        await retire_tags_for_plates(db, [plate])

        logger.info(
            "Added plate %s to existing permit %s for %s (now %d plates)",
            plate, existing_permit.permit_number, user.email, len(existing_permit.plates),
        )

        return VehicleRead(
            id=str(existing_permit.id),
            permit_number=existing_permit.permit_number,
            name=existing_permit.name,
            email=existing_permit.email,
            plate=plate,
            lot_assignment=existing_permit.lot_assignment,
            status=existing_permit.status,
            start_date=existing_permit.start_date.isoformat(),
            end_date=existing_permit.end_date.isoformat() if existing_permit.end_date else None,
            permit_type=existing_permit.permit_type or "",
            permit_type_label=pt.label,
        )

    # No existing permit — create a new one
    new_start = today_local()
    target = date(new_start.year, 6, 30)
    if target <= new_start:
        target = date(new_start.year + 1, 6, 30)

    _profile = getattr(user, "profile", None) or {}
    _mid = None
    for _f in ("altId", "studentId", "employeeNumber", "moravianId"):
        _v = _profile.get(_f)
        if _v:
            _mid = str(_v).split("@")[0].strip()
            break

    permit = Permit(
        permit_number=await next_permit_number(db),
        name=data.name.strip(),
        email=user.email,
        student_id=user.sub,
        moravian_id=_mid,
        plates=[plate],
        lot_assignment=", ".join(pt.lot_assignments) if pt.lot_assignments else "",
        permit_type=STAFF_PERMIT_CODE,
        start_date=new_start,
        end_date=target,
        status="active",
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)
    from ..services.tag_upgrade import retire_tags_for_plates
    await retire_tags_for_plates(db, permit.plates)

    return VehicleRead(
        id=str(permit.id),
        permit_number=permit.permit_number,
        name=permit.name,
        email=permit.email,
        plate=plate,
        lot_assignment=permit.lot_assignment,
        status=permit.status,
        start_date=permit.start_date.isoformat(),
        end_date=permit.end_date.isoformat() if permit.end_date else None,
        permit_type=permit.permit_type or "",
        permit_type_label=pt.label,
    )


@router.get("/my-vehicles", response_model=list[VehicleRead])
async def my_vehicles(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """List all of the current user's permits (including legacy/imported)."""
    from sqlalchemy import or_

    result = await db.execute(
        select(Permit).where(
            or_(Permit.student_id == user.sub, Permit.email == user.email),
            Permit.deleted_at.is_(None),
        ).order_by(Permit.created_at.desc())
    )
    permits = result.scalars().all()

    # Backfill missing email/student_id on any permits belonging to this user
    if user.email and "@" in user.email:
        for p in permits:
            changed = False
            if not p.email or "@" not in (p.email or ""):
                p.email = user.email
                changed = True
            if not p.student_id and user.sub:
                p.student_id = user.sub
                changed = True
            if changed:
                await db.flush()

    pt_codes = {p.permit_type for p in permits if p.permit_type}
    label_map: dict[str, str] = {}
    if pt_codes:
        pt_result = await db.execute(
            select(PermitType.code, PermitType.label).where(PermitType.code.in_(pt_codes))
        )
        label_map = {row.code: row.label for row in pt_result}

    # Return one entry per plate so the frontend shows each vehicle separately
    vehicles: list[VehicleRead] = []
    for p in permits:
        plates = p.plates or [""]
        for plate in plates:
            vehicles.append(VehicleRead(
                id=str(p.id),
                permit_number=p.permit_number,
                name=p.name,
                email=p.email,
                plate=plate,
                lot_assignment=p.lot_assignment,
                status=p.status,
                start_date=p.start_date.isoformat(),
                end_date=p.end_date.isoformat() if p.end_date else None,
                permit_type=p.permit_type or "",
                permit_type_label=label_map.get(p.permit_type or "", p.permit_type or ""),
            ))
    return vehicles


@router.delete("/{permit_id}", status_code=204)
async def remove_vehicle(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Remove a vehicle registration."""
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Vehicle registration not found")
    if permit.student_id != user.sub:
        raise HTTPException(403, "Not your vehicle registration")
    if permit.permit_type != STAFF_PERMIT_CODE:
        raise HTTPException(400, "This is not a staff/faculty vehicle registration")

    permit.deleted_at = datetime.now(timezone.utc)
    await db.flush()


# ── Admin: merge duplicate staff permits ──────────────────────────────

from ..auth.okta import require_admin


class MergePreview(BaseModel):
    email: str
    name: str
    primary_permit_id: str
    primary_permit_number: str | None
    primary_plates: list[str]
    duplicate_permit_ids: list[str]
    duplicate_plates: list[str]
    tickets_to_reassign: int


class MergeResult(BaseModel):
    merged: int
    plates_consolidated: int
    tickets_reassigned: int
    details: list[MergePreview]


@router.get("/admin/duplicate-staff-permits", response_model=list[MergePreview])
async def list_duplicate_staff_permits(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Find faculty/staff members with multiple active permits (should be merged)."""
    from sqlalchemy import or_, text
    from ..models.ticket import Ticket

    # Find emails/student_ids with more than one active staff permit
    result = await db.execute(
        select(Permit).where(
            Permit.permit_type == STAFF_PERMIT_CODE,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        ).order_by(Permit.email, Permit.created_at.asc())
    )
    all_permits = result.scalars().all()

    # Group by email (normalized)
    from collections import defaultdict
    by_email: dict[str, list[Permit]] = defaultdict(list)
    for p in all_permits:
        key = (p.email or "").lower().strip()
        if key:
            by_email[key].append(p)

    previews: list[MergePreview] = []
    for email, permits in by_email.items():
        if len(permits) < 2:
            continue

        primary = permits[0]  # oldest
        duplicates = permits[1:]
        dup_ids = [p.id for p in duplicates]

        # Count tickets on duplicate permits that would be reassigned
        ticket_count_result = await db.execute(
            select(func.count()).select_from(Ticket).where(
                Ticket.permit_id.in_(dup_ids),
            )
        )
        ticket_count = ticket_count_result.scalar() or 0

        dup_plates = []
        for d in duplicates:
            for plate in (d.plates or []):
                if plate not in (primary.plates or []) and plate not in dup_plates:
                    dup_plates.append(plate)

        previews.append(MergePreview(
            email=email,
            name=primary.name,
            primary_permit_id=str(primary.id),
            primary_permit_number=primary.permit_number,
            primary_plates=primary.plates or [],
            duplicate_permit_ids=[str(d.id) for d in duplicates],
            duplicate_plates=dup_plates,
            tickets_to_reassign=ticket_count,
        ))

    return previews


@router.post("/admin/merge-staff-permits", response_model=MergeResult)
async def merge_duplicate_staff_permits(
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Merge all duplicate faculty/staff permits into single permits per person.

    For each person with multiple active staff permits:
    1. Keep the oldest permit as the primary
    2. Move all plates from duplicates to the primary
    3. Reassign all tickets from duplicates to the primary
    4. Soft-delete the duplicate permits
    """
    from ..models.ticket import Ticket
    from ..models.payment import Payment
    from collections import defaultdict

    result = await db.execute(
        select(Permit).where(
            Permit.permit_type == STAFF_PERMIT_CODE,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        ).order_by(Permit.email, Permit.created_at.asc())
    )
    all_permits = result.scalars().all()

    by_email: dict[str, list[Permit]] = defaultdict(list)
    for p in all_permits:
        key = (p.email or "").lower().strip()
        if key:
            by_email[key].append(p)

    total_merged = 0
    total_plates = 0
    total_tickets = 0
    details: list[MergePreview] = []

    for email, permits in by_email.items():
        if len(permits) < 2:
            continue

        primary = permits[0]
        duplicates = permits[1:]
        merged_plates: list[str] = list(primary.plates or [])
        dup_plates: list[str] = []

        for dup in duplicates:
            for plate in (dup.plates or []):
                if plate not in merged_plates:
                    merged_plates.append(plate)
                    dup_plates.append(plate)

            # Reassign tickets from duplicate to primary
            ticket_result = await db.execute(
                select(Ticket).where(Ticket.permit_id == dup.id)
            )
            tickets = ticket_result.scalars().all()
            for t in tickets:
                t.permit_id = primary.id
                total_tickets += 1

            # Reassign payments from duplicate to primary
            # (payments don't have permit_id but ticket_id handles the link)

            # Soft-delete the duplicate
            dup.status = "cancelled"
            dup.cancel_reason = "merged"
            dup.cancel_notes = f"Merged into {primary.permit_number} by {admin.email}"
            dup.cancelled_at = datetime.now(timezone.utc)
            dup.cancelled_by = admin.email
            dup.deleted_at = datetime.now(timezone.utc)
            total_merged += 1

        # Update primary with all plates
        if len(merged_plates) > len(primary.plates or []):
            primary.plates = merged_plates
            total_plates += len(dup_plates)

        details.append(MergePreview(
            email=email,
            name=primary.name,
            primary_permit_id=str(primary.id),
            primary_permit_number=primary.permit_number,
            primary_plates=merged_plates,
            duplicate_permit_ids=[str(d.id) for d in duplicates],
            duplicate_plates=dup_plates,
            tickets_to_reassign=sum(1 for d in duplicates for _ in (d.plates or [])),
        ))

    await db.flush()

    logger.info(
        "Admin %s merged %d duplicate staff permits: %d plates consolidated, %d tickets reassigned",
        admin.email, total_merged, total_plates, total_tickets,
    )

    return MergeResult(
        merged=total_merged,
        plates_consolidated=total_plates,
        tickets_reassigned=total_tickets,
        details=details,
    )
