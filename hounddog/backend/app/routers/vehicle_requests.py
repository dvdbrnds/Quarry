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


class MultiVehicleSubmit(BaseModel):
    permit_id: uuid.UUID
    plate: str
    plate_state: str = ""
    reason: str = ""


class DenyBody(BaseModel):
    note: str = ""


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

    # Check plate not already on another active permit
    dupe = await db.execute(
        select(Permit).where(
            Permit.plates.any(new_plate),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    if dupe.scalar():
        raise HTTPException(409, f"Plate {new_plate} is already registered on an active permit")

    # Check no pending request already exists for this permit
    existing = await db.execute(
        select(VehicleRequest).where(
            VehicleRequest.permit_id == data.permit_id,
            VehicleRequest.status == "pending",
        )
    )
    if existing.scalar():
        raise HTTPException(409, "You already have a pending multi-vehicle request for this permit")

    req = VehicleRequest(
        permit_id=data.permit_id,
        student_sub=user.sub,
        student_email=user.email,
        student_name=getattr(user, "display_name", "") or user.email,
        plate=new_plate,
        plate_state=data.plate_state.upper().strip()[:2],
        reason=data.reason.strip()[:500],
        status="pending",
    )
    db.add(req)
    await db.flush()
    await db.refresh(req)

    # Notify the chief/admin
    try:
        from ..services.email import send_multi_vehicle_request_email
        notify_email = settings.vehicle_request_notify_email or settings.smtp_from_address
        if notify_email:
            await send_multi_vehicle_request_email(
                admin_email=notify_email,
                student_name=req.student_name,
                student_email=req.student_email,
                plate=new_plate,
                permit_number=permit.permit_number or str(permit.id)[:8],
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


# --- Admin endpoints ---


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

    # Batch-fetch permit info
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
    """Approve a multi-vehicle request: adds the plate to the permit."""
    req = await db.get(VehicleRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    permit = await db.get(Permit, req.permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(400, "Associated permit no longer exists")

    # Verify plate isn't already on another permit
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

    # Append plate to permit
    current_plates = list(permit.plates or [])
    if req.plate not in current_plates:
        current_plates.append(req.plate)
        permit.plates = current_plates

    req.status = "approved"
    req.decided_by = admin.email
    req.decided_at = datetime.now(timezone.utc)

    await db.flush()

    # Notify student
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
                request_id, admin.email, req.plate, permit.permit_number)

    return {"status": "approved", "message": f"Plate {req.plate} added to permit."}


@admin_router.post("/{request_id}/deny")
async def deny_vehicle_request(
    request_id: uuid.UUID,
    data: DenyBody,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Deny a multi-vehicle request with optional note."""
    req = await db.get(VehicleRequest, request_id)
    if not req:
        raise HTTPException(404, "Request not found")
    if req.status != "pending":
        raise HTTPException(400, f"Request is already {req.status}")

    req.status = "denied"
    req.decided_by = admin.email
    req.decision_note = data.note.strip()[:500] if data.note else None
    req.decided_at = datetime.now(timezone.utc)

    await db.flush()

    # Notify student
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

    logger.info("Vehicle request %s denied by %s", request_id, admin.email)

    return {"status": "denied", "message": "Request has been denied."}
