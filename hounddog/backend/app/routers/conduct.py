"""Conduct officer portal — view escalated students, their permits/tags, and tickets."""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser
from ..database import get_db
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..utils.safe_router import SafeRouter

_logger = logging.getLogger("quarry.conduct")

router = SafeRouter()


async def _get_conduct_emails(db: AsyncSession) -> list[str]:
    """Load conduct officer emails from enforcement_settings."""
    try:
        result = await db.execute(
            text("SELECT conduct_officer_emails FROM enforcement_settings WHERE id = 1")
        )
        raw = result.scalar() or ""
    except Exception:
        await db.rollback()
        raw = ""
    return [e.strip().lower() for e in raw.split(",") if e.strip()]


async def require_conduct(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OktaUser:
    """Allow admins or designated conduct officers."""
    if user.is_admin:
        return user
    allowed = await _get_conduct_emails(db)
    if user.email.lower() in allowed:
        return user
    raise HTTPException(403, "Access restricted to conduct officers")


class ResolveRequest(BaseModel):
    note: str = ""


@router.get("/cases")
async def list_cases(
    status: str = Query("all", regex="^(active|resolved|all)$"),
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_conduct),
):
    where_clause = "WHERE e.escalation_type = 'conduct_referral'"
    if status == "active":
        where_clause += " AND e.resolved_at IS NULL"
    elif status == "resolved":
        where_clause += " AND e.resolved_at IS NOT NULL"

    rows = await db.execute(text(f"""
        SELECT e.id, e.student_id, e.student_name, e.student_email, e.plate,
               e.ticket_count, e.ticket_ids, e.status, e.details,
               e.created_at, e.resolved_at, e.resolved_by
        FROM escalation_log e
        {where_clause}
        ORDER BY e.created_at DESC
    """))

    cases = []
    for row in rows.mappings():
        ticket_ids = [t.strip() for t in (row["ticket_ids"] or "").split(",") if t.strip()]

        # Get permit/tag for this student
        permit_info = None
        if row["student_id"]:
            p_result = await db.execute(
                select(Permit).where(
                    Permit.student_id == row["student_id"],
                    Permit.deleted_at.is_(None),
                    Permit.status != "cancelled",
                ).order_by(Permit.is_tag_only.asc())
            )
            permit = p_result.scalars().first()
            if permit:
                permit_info = {
                    "permit_id": str(permit.id),
                    "permit_number": permit.permit_number,
                    "permit_type": permit.permit_type,
                    "lot_zone": permit.lot_zone,
                    "plates": permit.plates,
                    "status": permit.status,
                    "is_tag_only": permit.is_tag_only,
                    "name": permit.name,
                    "email": permit.email,
                }

        # If no permit found by student_id, try by plate
        if not permit_info and row["plate"]:
            plate_norm = row["plate"].upper().replace(" ", "").replace("-", "")
            p_result = await db.execute(
                select(Permit).where(
                    Permit.deleted_at.is_(None),
                    Permit.status != "cancelled",
                    Permit.plates.any(plate_norm),
                ).order_by(Permit.is_tag_only.asc())
            )
            permit = p_result.scalars().first()
            if permit:
                permit_info = {
                    "permit_id": str(permit.id),
                    "permit_number": permit.permit_number,
                    "permit_type": permit.permit_type,
                    "lot_zone": permit.lot_zone,
                    "plates": permit.plates,
                    "status": permit.status,
                    "is_tag_only": permit.is_tag_only,
                    "name": permit.name,
                    "email": permit.email,
                }

        cases.append({
            "id": str(row["id"]),
            "student_id": row["student_id"],
            "student_name": row["student_name"],
            "student_email": row["student_email"],
            "plate": row["plate"],
            "ticket_count": row["ticket_count"],
            "ticket_ids": ticket_ids,
            "status": row["status"],
            "details": row["details"],
            "created_at": row["created_at"].isoformat() if row["created_at"] else None,
            "resolved_at": row["resolved_at"].isoformat() if row["resolved_at"] else None,
            "resolved_by": row["resolved_by"],
            "permit": permit_info,
        })

    return cases


@router.get("/cases/{case_id}")
async def get_case(
    case_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_conduct),
):
    row = await db.execute(text("""
        SELECT e.id, e.student_id, e.student_name, e.student_email, e.plate,
               e.ticket_count, e.ticket_ids, e.status, e.details,
               e.created_at, e.resolved_at, e.resolved_by
        FROM escalation_log e
        WHERE e.id = :case_id AND e.escalation_type = 'conduct_referral'
    """), {"case_id": str(case_id)})

    case_row = row.mappings().first()
    if not case_row:
        raise HTTPException(404, "Case not found")

    ticket_ids = [t.strip() for t in (case_row["ticket_ids"] or "").split(",") if t.strip()]

    # Fetch full ticket details
    tickets = []
    if ticket_ids:
        try:
            ticket_uuids = [uuid.UUID(tid) for tid in ticket_ids]
            t_result = await db.execute(
                select(Ticket).where(Ticket.id.in_(ticket_uuids)).order_by(Ticket.issued_at.desc())
            )
            for t in t_result.scalars().all():
                tickets.append({
                    "id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "plate": t.plate,
                    "lot": t.lot,
                    "violation_type": t.violation_type,
                    "fine_amount": str(t.fine_amount),
                    "status": t.status,
                    "issued_at": t.issued_at.isoformat() if t.issued_at else None,
                    "officer_name": t.officer_name,
                    "officer_notes": t.officer_notes,
                    "vehicle_description": t.vehicle_description,
                    "photo_url": t.photo_url,
                    "appeal_decision": getattr(t, "appeal_decision", None),
                    "appeal_note": getattr(t, "appeal_note", None),
                    "owner_name": t.owner_name,
                    "notification_email": t.notification_email,
                    "location_text": getattr(t, "location_text", None),
                    "location_lat": getattr(t, "location_lat", None),
                    "location_lng": getattr(t, "location_lng", None),
                })
        except Exception:
            _logger.warning("Failed to parse ticket_ids for case %s", case_id)

    # Also fetch any OTHER unpaid tickets for this student not in the original list
    if case_row["student_id"]:
        extra_result = await db.execute(text("""
            SELECT t.id::text FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(SELECT UPPER(unnest(p.plates)))
            WHERE p.student_id = :sid
              AND t.status NOT IN ('paid', 'voided', 'resolved_permit')
              AND t.id::text NOT IN (SELECT unnest(string_to_array(:tids, ',')))
            ORDER BY t.issued_at DESC
        """), {"sid": case_row["student_id"], "tids": ",".join(ticket_ids) if ticket_ids else ""})
        extra_ids = [r[0] for r in extra_result.fetchall()]
        if extra_ids:
            extra_uuids = [uuid.UUID(eid) for eid in extra_ids]
            et_result = await db.execute(
                select(Ticket).where(Ticket.id.in_(extra_uuids)).order_by(Ticket.issued_at.desc())
            )
            for t in et_result.scalars().all():
                tickets.append({
                    "id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "plate": t.plate,
                    "lot": t.lot,
                    "violation_type": t.violation_type,
                    "fine_amount": str(t.fine_amount),
                    "status": t.status,
                    "issued_at": t.issued_at.isoformat() if t.issued_at else None,
                    "officer_name": t.officer_name,
                    "officer_notes": t.officer_notes,
                    "vehicle_description": t.vehicle_description,
                    "photo_url": t.photo_url,
                    "appeal_decision": getattr(t, "appeal_decision", None),
                    "appeal_note": getattr(t, "appeal_note", None),
                    "owner_name": t.owner_name,
                    "notification_email": t.notification_email,
                    "location_text": getattr(t, "location_text", None),
                    "location_lat": getattr(t, "location_lat", None),
                    "location_lng": getattr(t, "location_lng", None),
                    "_extra": True,
                })

    # Get permit/tag
    permit_info = None
    if case_row["student_id"]:
        p_result = await db.execute(
            select(Permit).where(
                Permit.student_id == case_row["student_id"],
                Permit.deleted_at.is_(None),
                Permit.status != "cancelled",
            ).order_by(Permit.is_tag_only.asc())
        )
        permit = p_result.scalars().first()
        if permit:
            permit_info = {
                "permit_id": str(permit.id),
                "permit_number": permit.permit_number,
                "permit_type": permit.permit_type,
                "lot_zone": permit.lot_zone,
                "plates": permit.plates,
                "status": permit.status,
                "is_tag_only": permit.is_tag_only,
                "name": permit.name,
                "email": permit.email,
            }

    if not permit_info and case_row["plate"]:
        plate_norm = case_row["plate"].upper().replace(" ", "").replace("-", "")
        p_result = await db.execute(
            select(Permit).where(
                Permit.deleted_at.is_(None),
                Permit.status != "cancelled",
                Permit.plates.any(plate_norm),
            ).order_by(Permit.is_tag_only.asc())
        )
        permit = p_result.scalars().first()
        if permit:
            permit_info = {
                "permit_id": str(permit.id),
                "permit_number": permit.permit_number,
                "permit_type": permit.permit_type,
                "lot_zone": permit.lot_zone,
                "plates": permit.plates,
                "status": permit.status,
                "is_tag_only": permit.is_tag_only,
                "name": permit.name,
                "email": permit.email,
            }

    return {
        "id": str(case_row["id"]),
        "student_id": case_row["student_id"],
        "student_name": case_row["student_name"],
        "student_email": case_row["student_email"],
        "plate": case_row["plate"],
        "ticket_count": case_row["ticket_count"],
        "status": case_row["status"],
        "details": case_row["details"],
        "created_at": case_row["created_at"].isoformat() if case_row["created_at"] else None,
        "resolved_at": case_row["resolved_at"].isoformat() if case_row["resolved_at"] else None,
        "resolved_by": case_row["resolved_by"],
        "permit": permit_info,
        "tickets": tickets,
    }


@router.put("/cases/{case_id}/resolve")
async def resolve_case(
    case_id: uuid.UUID,
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_conduct),
):
    row = await db.execute(text("""
        SELECT id, resolved_at, details FROM escalation_log
        WHERE id = :case_id AND escalation_type = 'conduct_referral'
    """), {"case_id": str(case_id)})
    case_row = row.mappings().first()
    if not case_row:
        raise HTTPException(404, "Case not found")
    if case_row["resolved_at"]:
        raise HTTPException(400, "Case is already resolved")

    note_text = body.note.strip() if body.note else ""
    existing_details = case_row["details"] or ""
    new_details = f"{existing_details}\n[Resolved by {user.email}] {note_text}".strip()

    await db.execute(text("""
        UPDATE escalation_log
        SET resolved_at = NOW(), resolved_by = :resolved_by,
            status = 'resolved', details = :details
        WHERE id = :case_id
    """), {
        "case_id": str(case_id),
        "resolved_by": user.email,
        "details": new_details,
    })

    _logger.info("Conduct case %s resolved by %s", case_id, user.email)
    return {"resolved": True, "resolved_by": user.email}
