"""Public visitor/vendor parking permit portal — no authentication required."""

import re
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_office
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.visitor_approval_token import VisitorApprovalToken
from ..models.visitor_preset import VisitorPreset
from ..services.permit_numbering import next_permit_number
from ..services.timeutils import today_local


def _slugify(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


router = APIRouter()


# ── Request / Response schemas ──


class VisitorPermitCreate(BaseModel):
    visitor_type: str = "visitor"
    name: str
    plate: str
    plate_state: str = ""
    email: str = ""
    phone: str = ""
    company_name: str = ""
    duration: str = "single_day"
    start_date: date | None = None
    end_date: date | None = None
    sponsor_name: str = ""
    sponsor_email: str = ""
    sponsor_department: str = ""
    work_description: str = ""
    student_name: str = ""
    preset_id: str | None = None


class VisitorPermitResponse(BaseModel):
    id: str
    permit_number: str | None
    visitor_type: str
    name: str
    plate: str
    status: str
    start_date: str
    end_date: str | None
    requires_approval: bool = False
    message: str = ""


class VisitorPermitStatus(BaseModel):
    id: str
    permit_number: str | None
    name: str
    plate: str
    status: str
    visitor_type: str
    start_date: str
    end_date: str | None
    company_name: str = ""
    sponsor_name: str = ""
    sponsor_department: str = ""


class ApprovalInfo(BaseModel):
    permit_id: str
    permit_number: str | None
    name: str
    company_name: str
    plate: str
    work_description: str
    sponsor_department: str
    start_date: str
    end_date: str | None
    status: str
    already_decided: bool = False
    decision: str | None = None


class ApprovalDecision(BaseModel):
    decision: str  # "approved" or "denied"
    notes: str = ""


class PresetCreate(BaseModel):
    label: str
    company_name: str = ""
    sponsor_name: str = ""
    sponsor_email: str = ""
    sponsor_department: str = ""
    default_duration: str = "semester"
    permit_type_code: str | None = None
    allowed_lots: list[str] = []
    require_student_name: bool = False
    student_name_label: str = "Student name"
    sort_order: int = 0


class PresetUpdate(BaseModel):
    label: str | None = None
    company_name: str | None = None
    sponsor_name: str | None = None
    sponsor_email: str | None = None
    sponsor_department: str | None = None
    default_duration: str | None = None
    permit_type_code: str | None = None
    allowed_lots: list[str] | None = None
    require_student_name: bool | None = None
    student_name_label: str | None = None
    active: bool | None = None
    sort_order: int | None = None


# ── Endpoints ──


@router.get("/presets")
async def list_presets(db: AsyncSession = Depends(get_db)):
    """Public: list active visitor presets for the portal dropdown."""
    rows = (
        await db.execute(
            select(VisitorPreset)
            .where(VisitorPreset.active.is_(True))
            .order_by(VisitorPreset.sort_order, VisitorPreset.label)
        )
    ).scalars().all()
    base = settings.student_facing_url.rstrip("/")
    return [
        {
            "id": str(p.id),
            "label": p.label,
            "slug": _slugify(p.label),
            "direct_link": f"{base}/visitor?preset={_slugify(p.label)}",
            "company_name": p.company_name,
            "sponsor_name": p.sponsor_name,
            "sponsor_email": p.sponsor_email,
            "sponsor_department": p.sponsor_department,
            "default_duration": p.default_duration,
            "permit_type_code": p.permit_type_code,
            "allowed_lots": p.allowed_lots or [],
            "require_student_name": p.require_student_name,
            "student_name_label": p.student_name_label,
        }
        for p in rows
    ]


@router.get("/presets/all", tags=["admin"])
async def list_all_presets(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: list all presets including inactive."""
    rows = (
        await db.execute(
            select(VisitorPreset).order_by(VisitorPreset.sort_order, VisitorPreset.label)
        )
    ).scalars().all()
    base = settings.student_facing_url.rstrip("/")
    return [
        {
            "id": str(p.id),
            "label": p.label,
            "slug": _slugify(p.label),
            "direct_link": f"{base}/visitor?preset={_slugify(p.label)}",
            "company_name": p.company_name,
            "sponsor_name": p.sponsor_name,
            "sponsor_email": p.sponsor_email,
            "sponsor_department": p.sponsor_department,
            "default_duration": p.default_duration,
            "permit_type_code": p.permit_type_code,
            "allowed_lots": p.allowed_lots or [],
            "require_student_name": p.require_student_name,
            "student_name_label": p.student_name_label,
            "active": p.active,
            "sort_order": p.sort_order,
        }
        for p in rows
    ]


@router.post("/presets", tags=["admin"], status_code=201)
async def create_preset(
    data: PresetCreate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: create a visitor preset."""
    preset = VisitorPreset(
        label=data.label.strip(),
        company_name=data.company_name.strip(),
        sponsor_name=data.sponsor_name.strip(),
        sponsor_email=data.sponsor_email.strip(),
        sponsor_department=data.sponsor_department.strip(),
        default_duration=data.default_duration,
        permit_type_code=data.permit_type_code or None,
        allowed_lots=data.allowed_lots or [],
        require_student_name=data.require_student_name,
        student_name_label=data.student_name_label.strip() if data.student_name_label else "Student name",
        sort_order=data.sort_order,
    )
    db.add(preset)
    await db.flush()
    await db.refresh(preset)
    return {"id": str(preset.id), "label": preset.label}


@router.put("/presets/{preset_id}", tags=["admin"])
async def update_preset(
    preset_id: uuid.UUID,
    data: PresetUpdate,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: update a visitor preset."""
    preset = await db.get(VisitorPreset, preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(preset, field, value.strip() if isinstance(value, str) else value)
    return {"id": str(preset.id), "label": preset.label}


@router.post("/presets/{preset_id}/remove", tags=["admin"])
async def delete_preset(
    preset_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: delete a visitor preset."""
    preset = await db.get(VisitorPreset, preset_id)
    if not preset:
        raise HTTPException(404, "Preset not found")
    await db.delete(preset)
    return {"deleted": True}


@router.get("/admin/pending", tags=["admin"])
async def list_pending_visitor_permits(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: list all visitor permits awaiting sponsor approval."""
    rows = (
        await db.execute(
            select(Permit)
            .where(Permit.status == "pending_approval")
            .where(Permit.deleted_at.is_(None))
            .order_by(Permit.created_at.desc())
        )
    ).scalars().all()

    results = []
    for p in rows:
        token_row = (
            await db.execute(
                select(VisitorApprovalToken)
                .where(VisitorApprovalToken.permit_id == p.id)
                .order_by(VisitorApprovalToken.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

        results.append({
            "id": str(p.id),
            "permit_number": p.permit_number,
            "name": p.name,
            "plates": p.plates,
            "company_name": _extract_metadata(p, "company_name") or p.student_id or "",
            "sponsor_email": token_row.sponsor_email if token_row else "",
            "sponsor_name": token_row.sponsor_name if token_row else "",
            "created_at": p.created_at.isoformat() if p.created_at else "",
            "start_date": p.start_date.isoformat() if p.start_date else "",
            "end_date": p.end_date.isoformat() if p.end_date else "",
            "token_expired": token_row.expires_at < datetime.now(timezone.utc) if token_row else True,
        })
    return results


@router.post("", response_model=VisitorPermitResponse, status_code=201)
async def create_visitor_permit(data: VisitorPermitCreate, db: AsyncSession = Depends(get_db)):
    """Create a visitor or vendor temporary parking permit (public, no auth)."""
    plate = data.plate.upper().strip()
    if not plate:
        raise HTTPException(400, "License plate is required")
    if not data.name.strip():
        raise HTTPException(400, "Name is required")

    try:
        return await _create_visitor(data, plate, db)
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logging.getLogger("quarry.visitor_permits").exception("Permit creation failed")
        raise HTTPException(500, f"Permit creation error: {type(e).__name__}: {e}")


@router.get("/{permit_id}", response_model=VisitorPermitStatus)
async def get_visitor_permit_status(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Check the status of a visitor permit."""
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    if permit.permit_type not in ("visitor_day", "visitor_vendor", "visitor_vendor_longterm", "visitor_contracted_staff"):
        raise HTTPException(404, "Permit not found")

    return VisitorPermitStatus(
        id=str(permit.id),
        permit_number=permit.permit_number,
        name=permit.name,
        plate=permit.plates[0] if permit.plates else "",
        status=permit.status,
        visitor_type=permit.permit_type,
        start_date=permit.start_date.isoformat() if permit.start_date else "",
        end_date=permit.end_date.isoformat() if permit.end_date else None,
    )


@router.get("/approve/{token}", response_model=ApprovalInfo)
async def get_approval_info(token: str, db: AsyncSession = Depends(get_db)):
    """Get permit details for the approval page (staff sponsor views this)."""
    approval = await _get_valid_token(token, db, check_used=False)
    permit = await db.get(Permit, approval.permit_id)
    if not permit:
        raise HTTPException(404, "Permit not found")

    return ApprovalInfo(
        permit_id=str(permit.id),
        permit_number=permit.permit_number,
        name=permit.name,
        company_name=_extract_metadata(permit, "company_name") or permit.student_id or "",
        plate=permit.plates[0] if permit.plates else "",
        work_description=_extract_metadata(permit, "work_description"),
        sponsor_department=_extract_metadata(permit, "sponsor_department"),
        start_date=permit.start_date.isoformat() if permit.start_date else "",
        end_date=permit.end_date.isoformat() if permit.end_date else None,
        status=permit.status,
        already_decided=approval.used_at is not None,
        decision=approval.decision,
    )


@router.post("/resend-sponsor-email/{permit_id}", tags=["admin"])
async def resend_sponsor_email(
    permit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_office()),
):
    """Admin: resend the sponsor approval email for a pending visitor permit."""
    permit = await db.get(Permit, permit_id)
    if not permit:
        raise HTTPException(404, "Permit not found")
    if permit.status != "pending_approval":
        raise HTTPException(400, f"Permit is '{permit.status}', not pending_approval")

    approval = (
        await db.execute(
            select(VisitorApprovalToken)
            .where(VisitorApprovalToken.permit_id == permit_id)
            .order_by(VisitorApprovalToken.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if not approval:
        raise HTTPException(404, "No approval token found for this permit")

    sent = await _send_sponsor_approval_email(
        sponsor_email=approval.sponsor_email,
        sponsor_name=approval.sponsor_name,
        visitor_name=permit.name,
        company_name=_extract_metadata(permit, "company_name") or permit.student_id or "Visitor",
        plate=permit.plates[0] if permit.plates else "",
        work_description=_extract_metadata(permit, "work_description") or "",
        start_date=permit.start_date.isoformat() if permit.start_date else "",
        end_date=permit.end_date.isoformat() if permit.end_date else "",
        token=approval.token,
        student_name=_extract_metadata(permit, "student_name"),
    )
    if sent:
        return {"status": "sent", "message": f"Approval email resent to {approval.sponsor_email}"}
    raise HTTPException(500, f"Failed to send email to {approval.sponsor_email} — check server logs")


@router.post("/approve/{token}")
async def approve_or_deny(token: str, body: ApprovalDecision, db: AsyncSession = Depends(get_db)):
    """Staff sponsor approves or denies a long-term vendor permit."""
    approval = await _get_valid_token(token, db, check_used=True)
    permit = await db.get(Permit, approval.permit_id)
    if not permit:
        raise HTTPException(404, "Permit not found")

    if body.decision not in ("approved", "denied"):
        raise HTTPException(400, "Decision must be 'approved' or 'denied'")

    approval.used_at = datetime.now(timezone.utc)
    approval.decision = body.decision

    if body.decision == "approved":
        permit.status = "active"
        await db.flush()
        await _notify_permit_change("created", 1)
        # Send confirmation email to the visitor
        if permit.email:
            await _send_visitor_confirmation(permit)
        return {"status": "approved", "message": "Permit has been approved and is now active."}
    else:
        permit.status = "denied"
        permit.deleted_at = datetime.now(timezone.utc)
        await db.flush()
        return {"status": "denied", "message": "Permit has been denied."}


# ── Private helpers ──


async def _create_visitor(data: VisitorPermitCreate, plate: str, db: AsyncSession) -> VisitorPermitResponse:
    preset = None
    if data.preset_id:
        preset = await db.get(VisitorPreset, uuid.UUID(data.preset_id))
        if not preset or not preset.active:
            raise HTTPException(400, "Invalid or inactive preset")
        data.company_name = data.company_name or preset.company_name
        data.sponsor_name = preset.sponsor_name
        data.sponsor_email = preset.sponsor_email
        data.sponsor_department = preset.sponsor_department
        if preset.default_duration and data.duration == "single_day":
            data.duration = preset.default_duration

    if not data.sponsor_name.strip():
        raise HTTPException(400, "A campus sponsor name is required")
    if not data.sponsor_email.strip():
        raise HTTPException(400, "A campus sponsor email is required")

    start = data.start_date or today_local()
    end = data.end_date or start

    lot_assignment = "Visitor"

    # If the preset specifies a permit type, use it with its lot assignments
    if preset and preset.permit_type_code:
        pt_result = await db.execute(
            select(PermitType).where(PermitType.code == preset.permit_type_code)
        )
        pt_row = pt_result.scalars().first()
        if pt_row:
            permit_type = pt_row.code
            if pt_row.lot_assignments:
                lot_assignment = ", ".join(pt_row.lot_assignments)
            if end == start and data.duration == "semester":
                end = start + timedelta(days=120)
            elif end == start and data.duration == "yearly":
                end = start + timedelta(days=365)
        else:
            permit_type = "visitor_contracted_staff"
            if end == start:
                end = start + timedelta(days=120)
    elif preset and preset.allowed_lots:
        lot_assignment = ", ".join(preset.allowed_lots)
        days = (end - start).days
        if data.duration == "yearly":
            permit_type = "visitor_contracted_staff"
            if end == start:
                end = start + timedelta(days=365)
        elif data.duration == "semester":
            permit_type = "visitor_contracted_staff"
            if end == start:
                end = start + timedelta(days=120)
        elif days > 0:
            permit_type = "visitor_vendor_longterm"
        else:
            permit_type = "visitor_day"
    else:
        days = (end - start).days
        if data.duration == "yearly":
            permit_type = "visitor_contracted_staff"
            if end == start:
                end = start + timedelta(days=365)
        elif data.duration == "semester":
            permit_type = "visitor_contracted_staff"
            if end == start:
                end = start + timedelta(days=120)
        elif days > 0:
            permit_type = "visitor_vendor_longterm"
        else:
            permit_type = "visitor_day"

    permit = Permit(
        permit_number=await next_permit_number(db),
        name=data.name.strip(),
        email=data.email or None,
        phone=data.phone or "",
        plates=[plate],
        lot_assignment=lot_assignment,
        permit_type=permit_type,
        start_date=start,
        end_date=end,
        status="pending_approval",
        student_id=_build_metadata(data),
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)

    token = secrets.token_urlsafe(48)
    approval = VisitorApprovalToken(
        token=token,
        permit_id=permit.id,
        sponsor_email=data.sponsor_email.strip(),
        sponsor_name=data.sponsor_name.strip(),
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )
    db.add(approval)
    await db.flush()

    email_sent = await _send_sponsor_approval_email(
        sponsor_email=data.sponsor_email.strip(),
        sponsor_name=data.sponsor_name.strip(),
        visitor_name=data.name.strip(),
        company_name=data.company_name.strip() if data.company_name else "Visitor",
        plate=plate,
        work_description=data.work_description.strip() if data.work_description else "",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        token=token,
        student_name=data.student_name.strip(),
    )
    if email_sent:
        msg = (
            "Your permit request has been submitted and is pending approval from "
            f"{data.sponsor_name.strip()}. You will receive confirmation once approved."
        )
    else:
        msg = (
            "Your permit request has been submitted, but we could not send the approval "
            f"email to {data.sponsor_email.strip()}. Please contact them directly or "
            "reach out to the parking office for assistance."
        )

    return VisitorPermitResponse(
        id=str(permit.id),
        permit_number=permit.permit_number,
        visitor_type=permit_type,
        name=permit.name,
        plate=plate,
        status="pending_approval",
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        requires_approval=True,
        message=msg,
    )


async def _get_valid_token(token: str, db: AsyncSession, check_used: bool) -> VisitorApprovalToken:
    result = await db.execute(
        select(VisitorApprovalToken).where(VisitorApprovalToken.token == token)
    )
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(404, "Invalid or expired approval link")

    if check_used and approval.used_at:
        raise HTTPException(400, "This approval link has already been used")

    if approval.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "This approval link has expired")

    return approval


def _build_metadata(data: VisitorPermitCreate) -> str:
    parts = []
    if data.company_name.strip():
        parts.append(f"company_name:{data.company_name.strip()}")
    if data.work_description.strip():
        parts.append(f"work_description:{data.work_description.strip()}")
    if data.sponsor_department.strip():
        parts.append(f"sponsor_department:{data.sponsor_department.strip()}")
    if data.student_name.strip():
        parts.append(f"student_name:{data.student_name.strip()}")
    return "|".join(parts) if parts else data.company_name.strip()[:64]


def _extract_metadata(permit: Permit, key: str) -> str:
    """Extract a metadata value from the student_id field (pipe-separated key:value pairs)."""
    if not permit.student_id:
        return ""
    for part in permit.student_id.split("|"):
        if part.startswith(f"{key}:"):
            return part[len(key) + 1:]
    return ""


async def _notify_permit_change(action: str, count: int):
    """Send APNs push to devices on permit change."""
    from ..services.apns import send_permit_push
    await send_permit_push(action, count)


async def _send_visitor_confirmation(permit: Permit):
    """Send a confirmation email to the visitor. Never raises."""
    if not permit.email:
        return
    try:
        from ..services.email import send_visitor_confirmation_email
        end_str = permit.end_date.strftime("%B %d, %Y") if permit.end_date else "N/A"
        start_str = permit.start_date.strftime("%B %d, %Y") if permit.start_date else "Today"
        plate = permit.plates[0] if permit.plates else "N/A"
        await send_visitor_confirmation_email(
            recipient_email=permit.email,
            visitor_name=permit.name,
            permit_number=permit.permit_number or "",
            plate=plate,
            start_date=start_str,
            end_date=end_str,
        )
    except Exception:
        import logging
        logging.getLogger("quarry.visitor_permits").exception("Visitor confirmation email failed")


async def _send_sponsor_approval_email(
    sponsor_email: str,
    sponsor_name: str,
    visitor_name: str,
    company_name: str,
    plate: str,
    work_description: str,
    start_date: str,
    end_date: str,
    token: str,
) -> bool:
    """Send an approval request email to the department sponsor. Never raises."""
    try:
        from ..services.email import send_sponsor_approval_email
        approval_url = f"{settings.student_facing_url}/visitor/approve/{token}"
        return await send_sponsor_approval_email(
            sponsor_email=sponsor_email,
            sponsor_name=sponsor_name,
            visitor_name=visitor_name,
            company_name=company_name,
            plate=plate,
            work_description=work_description,
            start_date=start_date,
            end_date=end_date,
            approval_url=approval_url,
        )
    except Exception:
        import logging
        logging.getLogger("quarry.visitor_permits").exception("Sponsor approval email failed")
        return False
