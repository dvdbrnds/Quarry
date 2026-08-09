"""Public visitor/vendor parking permit portal — no authentication required."""

import logging
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

logger = logging.getLogger("quarry.visitor_permits")

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.visitor_approval_token import VisitorApprovalToken
from ..services.permit_numbering import next_permit_number
from ..services.timeutils import today_local


router = APIRouter()


# ── Request / Response schemas ──


class VisitorPermitCreate(BaseModel):
    visitor_type: str  # "day_guest" or "vendor"
    # Common fields
    name: str
    plate: str
    plate_state: str = ""
    email: str = ""
    phone: str = ""
    # Day guest fields
    visit_date: date | None = None
    visiting_person: str = ""
    visiting_event: str = ""
    # Vendor fields
    company_name: str = ""
    duration: str = "single_day"  # "single_day", "multi_day", "long_term_30", "long_term_60", "long_term_90", "semester"
    start_date: date | None = None
    end_date: date | None = None
    sponsor_name: str = ""
    sponsor_email: str = ""
    sponsor_department: str = ""
    work_description: str = ""


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


# ── Endpoints ──


@router.post("", response_model=VisitorPermitResponse, status_code=201)
async def create_visitor_permit(data: VisitorPermitCreate, db: AsyncSession = Depends(get_db)):
    """Create a visitor or vendor temporary parking permit (public, no auth)."""
    plate = data.plate.upper().strip()
    if not plate:
        raise HTTPException(400, "License plate is required")
    if not data.name.strip():
        raise HTTPException(400, "Name is required")

    if data.visitor_type == "day_guest":
        return await _create_day_guest(data, plate, db)
    elif data.visitor_type == "vendor":
        return await _create_vendor(data, plate, db)
    else:
        raise HTTPException(400, "visitor_type must be 'day_guest' or 'vendor'")


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
        company_name=_extract_metadata(permit, "company_name"),
        plate=permit.plates[0] if permit.plates else "",
        work_description=_extract_metadata(permit, "work_description"),
        sponsor_department=_extract_metadata(permit, "sponsor_department"),
        start_date=permit.start_date.isoformat() if permit.start_date else "",
        end_date=permit.end_date.isoformat() if permit.end_date else None,
        status=permit.status,
        already_decided=approval.used_at is not None,
        decision=approval.decision,
    )


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


async def _create_day_guest(data: VisitorPermitCreate, plate: str, db: AsyncSession) -> VisitorPermitResponse:
    visit_date = data.visit_date or today_local()

    notes_parts = []
    if data.visiting_person:
        notes_parts.append(f"Visiting: {data.visiting_person}")
    if data.visiting_event:
        notes_parts.append(f"Event: {data.visiting_event}")

    permit = Permit(
        permit_number=await next_permit_number(db),
        name=data.name.strip(),
        email=data.email or None,
        phone=data.phone or "",
        plates=[plate],
        lot_assignment="Visitor",
        permit_type="visitor_day",
        start_date=visit_date,
        end_date=visit_date,
        status="active",
        student_id="|".join(notes_parts),
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)
    await _notify_permit_change("created", 1)

    if data.email:
        await _send_visitor_confirmation(permit)

    return VisitorPermitResponse(
        id=str(permit.id),
        permit_number=permit.permit_number,
        visitor_type="visitor_day",
        name=permit.name,
        plate=plate,
        status="active",
        start_date=visit_date.isoformat(),
        end_date=visit_date.isoformat(),
        message="Your day pass is active. Please display your confirmation on your dashboard.",
    )


async def _create_vendor(data: VisitorPermitCreate, plate: str, db: AsyncSession) -> VisitorPermitResponse:
    if not data.company_name.strip():
        raise HTTPException(400, "Company name is required for vendor permits")
    if not data.sponsor_name.strip():
        raise HTTPException(400, "Sponsor/contact name is required for vendor permits")
    if not data.sponsor_email.strip():
        raise HTTPException(400, "Sponsor email is required for vendor permits")

    start = data.start_date or today_local()
    is_long_term = data.duration in ("multi_day", "long_term_30", "long_term_60", "long_term_90", "semester")

    if data.duration == "single_day":
        end = start
    elif data.duration == "multi_day":
        end = data.end_date or (start + timedelta(days=7))
    elif data.duration == "long_term_30":
        end = start + timedelta(days=30)
    elif data.duration == "long_term_60":
        end = start + timedelta(days=60)
    elif data.duration == "long_term_90":
        end = start + timedelta(days=90)
    elif data.duration == "semester":
        end = start + timedelta(days=120)
    else:
        end = start

    permit_type = "visitor_contracted_staff" if data.duration == "semester" else (
        "visitor_vendor_longterm" if is_long_term else "visitor_vendor"
    )
    status = "pending_approval" if is_long_term else "active"

    metadata_parts = [
        f"company_name:{data.company_name.strip()}",
        f"sponsor_department:{data.sponsor_department.strip()}",
        f"work_description:{data.work_description.strip()}",
    ]

    permit = Permit(
        permit_number=await next_permit_number(db),
        name=data.name.strip(),
        email=data.email or None,
        phone=data.phone or "",
        plates=[plate],
        lot_assignment="Vendor",
        permit_type=permit_type,
        start_date=start,
        end_date=end,
        status=status,
        student_id="|".join(metadata_parts),
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)

    requires_approval = is_long_term
    message = ""

    if is_long_term:
        # Generate approval token and email sponsor
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
            company_name=data.company_name.strip(),
            plate=plate,
            work_description=data.work_description.strip(),
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            token=token,
        )
        if email_sent:
            message = (
                "Your permit request has been submitted and is pending approval from "
                f"{data.sponsor_name.strip()}. You will receive confirmation once approved."
            )
        else:
            message = (
                "Your permit request has been submitted, but we could not send the approval "
                f"email to {data.sponsor_email.strip()}. Please contact them directly or "
                "reach out to the parking office for assistance."
            )
    else:
        await _notify_permit_change("created", 1)
        if data.email:
            await _send_visitor_confirmation(permit)
        message = "Your vendor day pass is active."

    return VisitorPermitResponse(
        id=str(permit.id),
        permit_number=permit.permit_number,
        visitor_type=permit_type,
        name=permit.name,
        plate=plate,
        status=status,
        start_date=start.isoformat(),
        end_date=end.isoformat(),
        requires_approval=requires_approval,
        message=message,
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
    """Send a confirmation email to the visitor."""
    if not permit.email:
        return
    try:
        from ..services.email import send_email, branded_email_shell
        school = settings.school_name or "Campus"

        end_str = permit.end_date.strftime("%B %d, %Y") if permit.end_date else "N/A"
        start_str = permit.start_date.strftime("%B %d, %Y") if permit.start_date else "Today"
        plate = permit.plates[0] if permit.plates else "N/A"

        inner = (
            f'<h2 style="color:#1a2744;margin:0 0 16px;">Visitor Parking Permit Confirmed</h2>'
            f'<p>Hello {permit.name},</p>'
            f'<p>Your temporary parking permit has been issued:</p>'
            f'<table style="width:100%;border-collapse:collapse;margin:16px 0;">'
            f'<tr><td style="padding:8px 0;color:#666;">Permit #</td><td style="padding:8px 0;font-weight:600;">{permit.permit_number or "—"}</td></tr>'
            f'<tr><td style="padding:8px 0;color:#666;">Vehicle</td><td style="padding:8px 0;font-weight:600;">{plate}</td></tr>'
            f'<tr><td style="padding:8px 0;color:#666;">Valid</td><td style="padding:8px 0;font-weight:600;">{start_str} — {end_str}</td></tr>'
            f'</table>'
            f'<p style="color:#666;font-size:14px;">No physical permit is required. Your license plate has been registered in our system.</p>'
        )
        body_html = await branded_email_shell(school, inner)
        await send_email([permit.email], f"Visitor Parking Permit — {plate}", body_html)
    except Exception:
        pass


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
    """Send an approval request email to the department sponsor. Returns True if sent."""
    try:
        from ..services.email import send_email, branded_email_shell
        school = settings.school_name or "Campus"
        approval_url = f"{settings.student_facing_url}/visitor/approve/{token}"

        inner = (
            f'<h2 style="color:#1a2744;margin:0 0 16px;">Vendor Parking Permit — Approval Required</h2>'
            f'<p>Hello {sponsor_name},</p>'
            f'<p>A vendor has requested a long-term parking permit and listed you as their campus sponsor. '
            f'Please review the details below and approve or deny the request.</p>'
            f'<table style="width:100%;border-collapse:collapse;margin:16px 0;background:#f9f9f9;border-radius:8px;">'
            f'<tr><td style="padding:10px 16px;color:#666;">Vendor</td><td style="padding:10px 16px;font-weight:600;">{visitor_name}</td></tr>'
            f'<tr><td style="padding:10px 16px;color:#666;">Company</td><td style="padding:10px 16px;font-weight:600;">{company_name}</td></tr>'
            f'<tr><td style="padding:10px 16px;color:#666;">Vehicle</td><td style="padding:10px 16px;font-weight:600;">{plate}</td></tr>'
            f'<tr><td style="padding:10px 16px;color:#666;">Work</td><td style="padding:10px 16px;">{work_description or "Not specified"}</td></tr>'
            f'<tr><td style="padding:10px 16px;color:#666;">Duration</td><td style="padding:10px 16px;font-weight:600;">{start_date} to {end_date}</td></tr>'
            f'</table>'
            f'<div style="text-align:center;margin:24px 0;">'
            f'<a href="{approval_url}" style="display:inline-block;background:#1a2744;color:#ffffff;'
            f'padding:12px 32px;border-radius:6px;text-decoration:none;font-weight:600;">Review &amp; Approve</a>'
            f'</div>'
            f'<p style="color:#999;font-size:13px;">This link expires in 7 days. If you did not expect this request, you can ignore this email.</p>'
        )
        body_html = await branded_email_shell(school, inner)
        sent = await send_email(
            [sponsor_email],
            f"Vendor Parking Permit Approval — {company_name}",
            body_html,
        )
        if not sent:
            logger.error(
                "Sponsor approval email FAILED to send to %s for visitor %s",
                sponsor_email, visitor_name,
            )
        return sent
    except Exception as e:
        logger.error("Sponsor approval email error: %s", e, exc_info=True)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass
        return False
