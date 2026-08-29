import secrets
import uuid
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.vehicle_request import VehicleRequest
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..config import settings

logger = logging.getLogger("quarry.vehicle_requests")

COMMUTER_CODES = {"commuter_undergrad", "commuter_grad", "premium_commuter"}

student_router = APIRouter(prefix="/api/student/permits", dependencies=[Depends(get_current_user)])
admin_router = APIRouter(prefix="/api/admin/vehicle-requests", dependencies=[Depends(require_admin())])
public_router = APIRouter(prefix="/api/vehicle-requests")


class MultiVehicleSubmit(BaseModel):
    permit_id: uuid.UUID
    plate: str
    plate_state: str = ""
    reason: str = ""


class DenyBody(BaseModel):
    note: str = ""


class PublicDecision(BaseModel):
    decision: str  # "approved" or "denied"


# ---------------------------------------------------------------------------
# Shared helper: apply approval to a request
# ---------------------------------------------------------------------------

async def _apply_approval(req: VehicleRequest, db: AsyncSession, decided_by: str):
    """Approve a vehicle request: append plate to permit, email student."""
    permit = await db.get(Permit, req.permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(400, "Associated permit no longer exists")

    dupe = await db.execute(
        select(Permit).where(
            Permit.plates.any(req.plate),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
            Permit.id != permit.id,
        )
    )
    if dupe.scalar():
        raise HTTPException(409, f"Plate {req.plate} is now registered on another active permit")

    current_plates = list(permit.plates or [])
    if req.plate not in current_plates:
        current_plates.append(req.plate)
        permit.plates = current_plates

    req.status = "approved"
    req.decided_by = decided_by
    req.decided_at = datetime.now(timezone.utc)
    await db.flush()

    try:
        from ..services.email import send_multi_vehicle_decision_email
        await send_multi_vehicle_decision_email(
            student_email=req.student_email,
            student_name=req.student_name,
            plate=req.plate,
            approved=True,
            note=None,
        )
    except Exception as e:
        logger.warning("Failed to send approval email: %s", e)

    logger.info("Vehicle request %s approved by %s — plate %s added to permit %s",
                req.id, decided_by, req.plate, permit.permit_number)


async def _apply_denial(req: VehicleRequest, db: AsyncSession, decided_by: str, note: str = ""):
    """Deny a vehicle request, email student."""
    req.status = "denied"
    req.decided_by = decided_by
    req.decision_note = note.strip()[:500] if note else None
    req.decided_at = datetime.now(timezone.utc)
    await db.flush()

    try:
        from ..services.email import send_multi_vehicle_decision_email
        await send_multi_vehicle_decision_email(
            student_email=req.student_email,
            student_name=req.student_name,
            plate=req.plate,
            approved=False,
            note=req.decision_note,
        )
    except Exception as e:
        logger.warning("Failed to send denial email: %s", e)

    logger.info("Vehicle request %s denied by %s", req.id, decided_by)


# ---------------------------------------------------------------------------
# Student endpoints
# ---------------------------------------------------------------------------

@student_router.post("/multi-vehicle-request")
async def submit_multi_vehicle_request(
    data: MultiVehicleSubmit,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Student submits a request to add a second vehicle to their commuter permit."""
    permit = await db.get(Permit, data.permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    if permit.status != "active":
        raise HTTPException(400, "Only active permits can have additional vehicles")

    is_owner = (permit.student_id == user.sub) or (permit.email and permit.email == user.email)
    if not is_owner:
        raise HTTPException(403, "Not your permit")

    if permit.permit_type not in COMMUTER_CODES:
        raise HTTPException(400, "Multi-vehicle requests are only available for commuter permits")

    new_plate = data.plate.upper().strip()
    if not new_plate:
        raise HTTPException(400, "License plate is required")

    dupe = await db.execute(
        select(Permit).where(
            Permit.plates.any(new_plate),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    if dupe.scalar():
        raise HTTPException(409, f"Plate {new_plate} is already registered on an active permit")

    existing = await db.execute(
        select(VehicleRequest).where(
            VehicleRequest.permit_id == data.permit_id,
            VehicleRequest.status == "pending",
        )
    )
    if existing.scalar():
        raise HTTPException(409, "You already have a pending multi-vehicle request for this permit")

    token = secrets.token_urlsafe(48)

    req = VehicleRequest(
        permit_id=data.permit_id,
        student_sub=user.sub,
        student_email=user.email,
        student_name=getattr(user, "display_name", "") or user.email,
        plate=new_plate,
        plate_state=data.plate_state.upper().strip()[:2],
        reason=data.reason.strip()[:500],
        status="pending",
        approval_token=token,
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)

    # Email the chief with one-click approve/deny links
    try:
        from ..services.email import send_multi_vehicle_request_email
        from ..models.branding_settings import BrandingSettings
        bs = (await db.execute(select(BrandingSettings))).scalar()
        notify_email = (
            (bs.vehicle_request_notify_email if bs else "")
            or settings.vehicle_request_notify_email
            or settings.smtp_from_address
        )
        base_url = settings.student_facing_url or settings.public_url or ""
        approval_url = f"{base_url.rstrip('/')}/vehicle-approve/{token}"
        if notify_email:
            await send_multi_vehicle_request_email(
                admin_email=notify_email,
                student_name=req.student_name,
                student_email=req.student_email,
                plate=new_plate,
                permit_number=permit.permit_number or str(permit.id)[:8],
                approval_url=approval_url,
            )
    except Exception as e:
        logger.warning("Failed to send vehicle request notification: %s", e)

    return {
        "id": str(req.id),
        "status": "pending",
        "message": "Your request has been submitted for review.",
    }


@student_router.get("/multi-vehicle-requests")
async def list_my_vehicle_requests(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """List the current student's multi-vehicle requests."""
    result = await db.execute(
        select(VehicleRequest)
        .where(VehicleRequest.student_sub == user.sub)
        .order_by(VehicleRequest.created_at.desc())
    )
    requests = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "permit_id": str(r.permit_id),
            "plate": r.plate,
            "plate_state": r.plate_state,
            "reason": r.reason,
            "status": r.status,
            "decision_note": r.decision_note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
        }
        for r in requests
    ]


# ---------------------------------------------------------------------------
# Public token-based approval (no auth required, like visitor approvals)
# ---------------------------------------------------------------------------

@public_router.get("/approve/{token}")
async def get_vehicle_request_info(token: str, db: AsyncSession = Depends(get_db)):
    """Load vehicle request details for the approval page (chief views this via email link)."""
    result = await db.execute(
        select(VehicleRequest).where(VehicleRequest.approval_token == token)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Request not found or link is invalid")

    permit = await db.get(Permit, req.permit_id)
    permit_number = permit.permit_number if permit else None
    current_plates = list(permit.plates) if permit else []
    permit_type = permit.permit_type if permit else None

    return {
        "id": str(req.id),
        "student_name": req.student_name,
        "student_email": req.student_email,
        "plate": req.plate,
        "plate_state": req.plate_state,
        "reason": req.reason,
        "status": req.status,
        "permit_number": permit_number,
        "current_plates": current_plates,
        "permit_type": permit_type,
        "already_decided": req.status != "pending",
        "decision": req.status if req.status != "pending" else None,
        "created_at": req.created_at.isoformat() if req.created_at else None,
    }


@public_router.post("/approve/{token}")
async def decide_vehicle_request_by_token(
    token: str,
    body: PublicDecision,
    db: AsyncSession = Depends(get_db),
):
    """Chief approves or denies via one-click email link (no login required)."""
    result = await db.execute(
        select(VehicleRequest).where(VehicleRequest.approval_token == token)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise HTTPException(404, "Request not found or link is invalid")
    if req.status != "pending":
        raise HTTPException(400, f"This request has already been {req.status}")

    if body.decision not in ("approved", "denied"):
        raise HTTPException(400, "Decision must be 'approved' or 'denied'")

    if body.decision == "approved":
        await _apply_approval(req, db, decided_by="email-link")
        return {"status": "approved", "message": f"Plate {req.plate} has been added to the permit."}
    else:
        await _apply_denial(req, db, decided_by="email-link")
        return {"status": "denied", "message": "Request has been denied."}


# ---------------------------------------------------------------------------
# Admin endpoints (panel-based, require login)
# ---------------------------------------------------------------------------

@admin_router.get("")
async def list_vehicle_requests(
    status: str = Query(None),
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """List all vehicle requests, optionally filtered by status."""
    query = select(VehicleRequest).order_by(VehicleRequest.created_at.desc())
    if status:
        query = query.where(VehicleRequest.status == status)

    result = await db.execute(query)
    requests = result.scalars().all()

    permit_ids = {r.permit_id for r in requests}
    permits_result = await db.execute(
        select(Permit).where(Permit.id.in_(permit_ids))
    ) if permit_ids else None
    permit_map = {p.id: p for p in (permits_result.scalars().all() if permits_result else [])}

    return [
        {
            "id": str(r.id),
            "permit_id": str(r.permit_id),
            "student_sub": r.student_sub,
            "student_email": r.student_email,
            "student_name": r.student_name,
            "plate": r.plate,
            "plate_state": r.plate_state,
            "reason": r.reason,
            "status": r.status,
            "decided_by": r.decided_by,
            "decision_note": r.decision_note,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "decided_at": r.decided_at.isoformat() if r.decided_at else None,
            "permit_number": permit_map[r.permit_id].permit_number if r.permit_id in permit_map else None,
            "current_plates": permit_map[r.permit_id].plates if r.permit_id in permit_map else [],
            "permit_type": permit_map[r.permit_id].permit_type if r.permit_id in permit_map else None,
        }
        for r in requests
    ]


@admin_router.get("/pending-count")
async def pending_vehicle_request_count(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Return count of pending vehicle requests for dashboard display."""
    count = (await db.execute(
        select(func.count()).select_from(VehicleRequest).where(VehicleRequest.status == "pending")
    )).scalar() or 0
    return {"pending_count": count}


@admin_router.post("/{request_id}/approve")
async def approve_vehicle_request(
    request_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Approve a multi-vehicle request from the admin panel."""
    req = await db.get(VehicleRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    await _apply_approval(req, db, decided_by=admin.email)
    return {"status": "approved", "message": f"Plate {req.plate} added to permit."}


@admin_router.post("/{request_id}/deny")
async def deny_vehicle_request(
    request_id: uuid.UUID,
    data: DenyBody,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Deny a multi-vehicle request from the admin panel."""
    req = await db.get(VehicleRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    await _apply_denial(req, db, decided_by=admin.email, note=data.note)
    return {"status": "denied", "message": "Request has been denied."}
