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
    # Find ALL plates with 3+ unpaid tickets — this is the source of truth
    plate_rows = await db.execute(text("""
        SELECT
            UPPER(REPLACE(REPLACE(t.plate, ' ', ''), '-', '')) AS plate_norm,
            t.plate,
            COUNT(*) AS ticket_count,
            MIN(t.issued_at) AS first_ticket,
            MAX(t.issued_at) AS latest_ticket,
            t.owner_name
        FROM tickets t
        WHERE t.status NOT IN ('paid', 'voided', 'resolved_permit')
        GROUP BY plate_norm, t.plate, t.owner_name
        HAVING COUNT(*) >= 3
        ORDER BY MAX(t.issued_at) DESC
    """))

    cases = []
    for row in plate_rows.mappings():
        plate = row["plate"]
        plate_norm = row["plate_norm"]

        # Look up permit/tag for this plate
        permit_info = None
        student_id = ""
        student_name = row["owner_name"] or ""
        student_email = ""

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
                "lot_zone": permit.lot_assignment,
                "plates": permit.plates,
                "status": permit.status,
                "is_tag_only": permit.is_tag_only,
                "name": permit.name,
                "email": permit.email,
            }
            student_id = permit.student_id or ""
            student_name = permit.name or student_name
            student_email = permit.email or ""

        # Check if there's an escalation_log entry for this plate
        esc_result = await db.execute(text("""
            SELECT id, status, details, created_at, resolved_at, resolved_by
            FROM escalation_log
            WHERE escalation_type = 'conduct_referral'
              AND UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :plate
            ORDER BY created_at DESC LIMIT 1
        """), {"plate": plate_norm})
        esc = esc_result.mappings().first()

        esc_status = esc["status"] if esc else "sent"
        if status == "active" and esc and esc["resolved_at"]:
            continue
        if status == "resolved" and (not esc or not esc["resolved_at"]):
            continue

        cases.append({
            "id": str(esc["id"]) if esc else f"plate:{plate_norm}",
            "student_id": student_id,
            "student_name": student_name,
            "student_email": student_email,
            "plate": plate,
            "ticket_count": row["ticket_count"],
            "ticket_ids": [],
            "status": esc_status,
            "details": esc["details"] if esc else None,
            "created_at": (esc["created_at"].isoformat() if esc and esc["created_at"]
                           else row["first_ticket"].isoformat() if row["first_ticket"] else None),
            "resolved_at": esc["resolved_at"].isoformat() if esc and esc["resolved_at"] else None,
            "resolved_by": esc["resolved_by"] if esc else None,
            "permit": permit_info,
        })

    return cases


@router.get("/cases/{case_id}")
async def get_case(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_conduct),
):
  try:
    if case_id.startswith("plate:"):
        return await _get_case_by_plate(case_id[6:], db)
    return await _get_case_detail(uuid.UUID(case_id), db)
  except HTTPException:
    raise
  except Exception as e:
    _logger.error("Failed to load case %s: %s", case_id, e, exc_info=True)
    raise HTTPException(500, f"Internal error: {str(e)[:200]}")


async def _get_case_by_plate(plate_norm: str, db: AsyncSession):
    """Build a case detail from tickets for a plate that has no escalation_log entry."""
    # Get all tickets for this plate
    t_result = await db.execute(
        select(Ticket).where(
            text("UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :p")
        ).params(p=plate_norm).order_by(Ticket.issued_at.desc())
    )
    all_tickets = t_result.scalars().all()
    if not all_tickets:
        raise HTTPException(404, "No tickets found for this plate")

    plate = all_tickets[0].plate
    owner_name = next((t.owner_name for t in all_tickets if t.owner_name), None)
    notification_email = next((t.notification_email for t in all_tickets if t.notification_email), None)

    # Look up permit
    permit_info = None
    student_id = ""
    p_result = await db.execute(
        select(Permit).where(
            Permit.deleted_at.is_(None),
            Permit.status != "cancelled",
            Permit.plates.any(plate_norm),
        ).order_by(Permit.is_tag_only.asc())
    )
    permit = p_result.scalars().first()
    if permit:
        student_id = permit.student_id or ""
        owner_name = permit.name or owner_name
        notification_email = permit.email or notification_email
        permit_info = {
            "permit_id": str(permit.id),
            "permit_number": permit.permit_number,
            "permit_type": permit.permit_type,
            "lot_zone": permit.lot_assignment,
            "plates": permit.plates,
            "status": permit.status,
            "is_tag_only": permit.is_tag_only,
            "name": permit.name,
            "email": permit.email,
        }

    unpaid = [t for t in all_tickets if t.status not in ("paid", "voided", "resolved_permit")]
    tickets = []
    for t in all_tickets:
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
            "_tag": "referral" if t.status not in ("paid", "voided", "resolved_permit") else "history",
            "_prior_conduct": False,
        })

    return {
        "id": f"plate:{plate_norm}",
        "student_id": student_id,
        "student_name": owner_name or "",
        "student_email": notification_email or "",
        "plate": plate,
        "ticket_count": len(unpaid),
        "status": "sent",
        "details": None,
        "created_at": all_tickets[-1].issued_at.isoformat() if all_tickets[-1].issued_at else None,
        "resolved_at": None,
        "resolved_by": None,
        "permit": permit_info,
        "tickets": tickets,
    }


async def _get_case_detail(case_id: uuid.UUID, db: AsyncSession):
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

    referral_ids = set(t.strip() for t in (case_row["ticket_ids"] or "").split(",") if t.strip())

    # Collect all ticket IDs previously referenced by resolved conduct cases for this student
    prior_resolved_ids: set[str] = set()
    if case_row["student_id"]:
        prior_result = await db.execute(text("""
            SELECT ticket_ids FROM escalation_log
            WHERE escalation_type = 'conduct_referral'
              AND student_id = :sid
              AND resolved_at IS NOT NULL
              AND id != :case_id
        """), {"sid": case_row["student_id"], "case_id": str(case_id)})
        for pr in prior_result.fetchall():
            for tid in (pr[0] or "").split(","):
                tid = tid.strip()
                if tid:
                    prior_resolved_ids.add(tid)

    # Fetch ALL tickets for this student via multiple strategies
    all_ids: set[str] = set(referral_ids)

    # Strategy 1: by student_id on permits
    if case_row["student_id"]:
        sid = case_row["student_id"]
        sid_result = await db.execute(text("""
            SELECT DISTINCT t.id::text FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(SELECT UPPER(unnest(p.plates)))
            WHERE p.student_id = :sid AND p.deleted_at IS NULL
        """), {"sid": sid})
        all_ids.update(r[0] for r in sid_result.fetchall())

        # Also try student_id as email (permits.student_id might be email-based)
        if "@" not in sid:
            email = case_row["student_email"]
            if email:
                email_result = await db.execute(text("""
                    SELECT DISTINCT t.id::text FROM tickets t
                    JOIN permits p ON UPPER(t.plate) = ANY(SELECT UPPER(unnest(p.plates)))
                    WHERE p.student_id = :sid AND p.deleted_at IS NULL
                """), {"sid": email})
                all_ids.update(r[0] for r in email_result.fetchall())

    # Strategy 2: by plate (always run, not just as fallback)
    if case_row["plate"]:
        plate_norm = case_row["plate"].upper().replace(" ", "").replace("-", "")
        plate_result = await db.execute(text("""
            SELECT DISTINCT t.id::text FROM tickets t
            WHERE UPPER(REPLACE(REPLACE(t.plate, ' ', ''), '-', '')) = :plate
        """), {"plate": plate_norm})
        all_ids.update(r[0] for r in plate_result.fetchall())

    tickets = []
    if all_ids:
        try:
            valid_ids = []
            for tid in all_ids:
                try:
                    valid_ids.append(uuid.UUID(tid))
                except (ValueError, AttributeError):
                    _logger.warning("Skipping invalid ticket id: %s", tid)
            all_uuids = valid_ids
            t_result = await db.execute(
                select(Ticket).where(Ticket.id.in_(all_uuids)).order_by(Ticket.issued_at.desc())
            )
            for t in t_result.scalars().all():
                tid_str = str(t.id)
                tag = "referral" if tid_str in referral_ids else "history"
                if tag == "history" and t.status not in ("paid", "voided", "resolved_permit"):
                    tag = "extra"  # unpaid ticket added after referral
                tickets.append({
                    "id": tid_str,
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
                    "_tag": tag,
                    "_prior_conduct": tid_str in prior_resolved_ids,
                })
        except Exception:
            _logger.warning("Failed to fetch tickets for case %s", case_id, exc_info=True)

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
                "lot_zone": permit.lot_assignment,
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
                "lot_zone": permit.lot_assignment,
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


async def _ensure_escalation_log(case_id: str, db: AsyncSession) -> str:
    """If case_id is plate:XXX, create an escalation_log entry and return the real UUID."""
    if not case_id.startswith("plate:"):
        return case_id
    plate_norm = case_id[6:]
    # Check if one already exists
    existing = await db.execute(text("""
        SELECT id FROM escalation_log
        WHERE escalation_type = 'conduct_referral'
          AND UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :plate
          AND resolved_at IS NULL
        LIMIT 1
    """), {"plate": plate_norm})
    row = existing.first()
    if row:
        return str(row[0])
    # Create one
    # Get ticket info
    t_result = await db.execute(text("""
        SELECT plate, owner_name, COUNT(*) as cnt,
               array_agg(id::text) as tids
        FROM tickets
        WHERE UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :plate
          AND status NOT IN ('paid', 'voided', 'resolved_permit')
        GROUP BY plate, owner_name LIMIT 1
    """), {"plate": plate_norm})
    t_row = t_result.mappings().first()
    plate_val = t_row["plate"] if t_row else ""
    name = t_row["owner_name"] if t_row else ""
    cnt = t_row["cnt"] if t_row else 0
    tids = ",".join(t_row["tids"]) if t_row and t_row["tids"] else ""
    # Look up permit for email/student_id
    p_result = await db.execute(
        select(Permit).where(
            Permit.deleted_at.is_(None),
            Permit.plates.any(plate_norm),
        ).order_by(Permit.is_tag_only.asc())
    )
    permit = p_result.scalars().first()
    sid = permit.student_id if permit else ""
    email = permit.email if permit else ""
    name = permit.name or name or ""
    new_id = str(uuid.uuid4())
    await db.execute(text("""
        INSERT INTO escalation_log (id, student_id, student_name, student_email, plate,
            escalation_type, ticket_count, ticket_ids, status)
        VALUES (:id, :sid, :name, :email, :plate, 'conduct_referral', :cnt, :tids, 'sent')
    """), {"id": new_id, "sid": sid, "name": name, "email": email,
           "plate": plate_val, "cnt": cnt, "tids": tids})
    return new_id


@router.put("/cases/{case_id}/resolve")
async def resolve_case(
    case_id: str,
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_conduct),
):
    real_id = await _ensure_escalation_log(case_id, db)
    row = await db.execute(text("""
        SELECT id, resolved_at, details FROM escalation_log
        WHERE id = :case_id AND escalation_type = 'conduct_referral'
    """), {"case_id": real_id})
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
        "case_id": real_id,
        "resolved_by": user.email,
        "details": new_details,
    })

    _logger.info("Conduct case %s resolved by %s", real_id, user.email)
    return {"ok": True}


class NoteRequest(BaseModel):
    note: str


@router.put("/cases/{case_id}/note")
async def add_note(
    case_id: str,
    body: NoteRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_conduct),
):
    real_id = await _ensure_escalation_log(case_id, db)
    row = await db.execute(text("""
        SELECT id, details FROM escalation_log
        WHERE id = :case_id AND escalation_type = 'conduct_referral'
    """), {"case_id": real_id})
    case_row = row.mappings().first()
    if not case_row:
        raise HTTPException(404, "Case not found")

    note_text = body.note.strip()
    if not note_text:
        raise HTTPException(400, "Note cannot be empty")

    ts = datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p")
    existing = case_row["details"] or ""
    new_details = f"{existing}\n[{ts} — {user.email}] {note_text}".strip()

    await db.execute(text("""
        UPDATE escalation_log SET details = :details WHERE id = :case_id
    """), {"case_id": real_id, "details": new_details})

    _logger.info("Note added to conduct case %s by %s", real_id, user.email)
    return {"ok": True, "details": new_details}


class UpdateStudentRequest(BaseModel):
    student_name: str | None = None
    student_email: str | None = None
    plate: str | None = None


@router.put("/cases/{case_id}/update-student")
async def update_student_info(
    case_id: str,
    body: UpdateStudentRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_conduct),
):
    """Update owner name/email on all tickets for this case's plate."""
    # Resolve the plate — either from escalation_log or from the plate: prefix
    if case_id.startswith("plate:"):
        plate_norm = case_id[6:]
        # Get actual plate from tickets
        p_row = await db.execute(text("""
            SELECT plate FROM tickets
            WHERE UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :p
            LIMIT 1
        """), {"p": plate_norm})
        plate_val = p_row.scalar()
        if not plate_val:
            raise HTTPException(404, "No tickets found for this plate")
    else:
        real_id = case_id
        row = await db.execute(text("""
            SELECT plate FROM escalation_log
            WHERE id = :case_id AND escalation_type = 'conduct_referral'
        """), {"case_id": real_id})
        esc = row.mappings().first()
        if not esc:
            raise HTTPException(404, "Case not found")
        plate_val = esc["plate"]

    if not plate_val:
        raise HTTPException(400, "No plate associated with this case")

    plate_norm = plate_val.upper().replace(" ", "").replace("-", "")
    updates: dict = {}
    if body.student_name is not None:
        updates["owner_name"] = body.student_name
    if body.student_email is not None:
        updates["notification_email"] = body.student_email

    if not updates:
        raise HTTPException(400, "Nothing to update")

    # Update all tickets for this plate
    set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
    updates["plate"] = plate_val
    await db.execute(text(f"""
        UPDATE tickets SET {set_clauses} WHERE plate = :plate
    """), updates)

    # Also update the vehicle tag if one exists
    tag_result = await db.execute(
        select(Permit).where(
            Permit.is_tag_only.is_(True),
            Permit.deleted_at.is_(None),
            Permit.plates.any(plate_norm),
        )
    )
    tag = tag_result.scalars().first()
    if tag:
        if body.student_name is not None:
            tag.name = body.student_name
        if body.student_email is not None:
            tag.email = body.student_email
        await db.flush()

    # Update the escalation_log entry too
    esc_updates = {}
    if body.student_name is not None:
        esc_updates["student_name"] = body.student_name
    if body.student_email is not None:
        esc_updates["student_email"] = body.student_email
    if esc_updates and not case_id.startswith("plate:"):
        set_esc = ", ".join(f"{k} = :{k}" for k in esc_updates)
        esc_updates["case_id"] = case_id
        await db.execute(text(f"""
            UPDATE escalation_log SET {set_esc} WHERE id = :case_id
        """), esc_updates)

    _logger.info("Student info updated for plate %s by %s: %s", plate_val, user.email, updates)
    return {"ok": True}
