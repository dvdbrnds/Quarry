"""Conduct officer portal — view escalated students, their permits/tags, and tickets."""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from app import error_reporting
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser, require_admin
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.ticket import Ticket
from ..utils.safe_router import SafeRouter

_logger = logging.getLogger("quarry.conduct")


def _extract_moravian_id_from_profile(profile: dict) -> str | None:
    """Extract the numeric Moravian/Jenzabar ID from an Okta profile."""
    for field in ("altId", "studentId", "employeeNumber", "moravianId"):
        val = profile.get(field)
        if val:
            candidate = str(val).split("@")[0].strip()
            if candidate.isdigit():
                return candidate
    return None


async def _lookup_okta_user(identifier: str) -> dict | None:
    """Look up a user in Okta by email or sub. Returns profile dict or None."""
    if not settings.okta_domain or not settings.okta_api_token or not identifier:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"https://{settings.okta_domain}/api/v1/users/{identifier}",
                headers={"Authorization": f"SSWS {settings.okta_api_token}"},
            )
            if res.status_code == 200:
                data = res.json()
                profile = data.get("profile", {})
                return {
                    "sub": data.get("id", ""),
                    "email": profile.get("email", ""),
                    "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
                    "moravian_id": _extract_moravian_id_from_profile(profile),
                }
    except Exception as e:
        _logger.debug("Okta lookup failed for %s: %s", identifier, e)
    return None


async def _enrich_student_fields(
    moravian_id: str, student_email: str, student_name: str,
    okta_sub: str = "",
) -> tuple[str, str, str]:
    """Fill in missing moravian_id, email, or name via Okta lookup.

    moravian_id: the 6-digit Jenzabar student ID (what we display).
    okta_sub: the Okta sub (used for lookup only, never displayed).
    """
    if moravian_id and student_email and student_name:
        return moravian_id, student_email, student_name

    lookup_key = okta_sub or student_email
    if not lookup_key:
        return moravian_id, student_email, student_name

    okta = await _lookup_okta_user(lookup_key)
    if okta:
        if not moravian_id and okta["moravian_id"]:
            moravian_id = okta["moravian_id"]
        if not student_email:
            student_email = okta["email"]
        if not student_name:
            student_name = okta["name"]

    return moravian_id, student_email, student_name

router = SafeRouter()


def _permit_info(permit: Permit) -> dict:
    return {
        "permit_id": str(permit.id),
        "permit_number": permit.permit_number,
        "permit_type": permit.permit_type,
        "lot_zone": permit.lot_assignment,
        "plates": permit.plates,
        "status": permit.status,
        "is_tag_only": permit.is_tag_only,
        "name": permit.name,
        "email": permit.email,
        "owner_verified_at": permit.owner_verified_at.isoformat() if permit.owner_verified_at else None,
        "owner_verified_by": permit.owner_verified_by,
    }


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
    # Find ALL plates with 3+ unpaid tickets — this is the source of truth.
    # Don't group by owner_name — officer name typos cause duplicate rows.
    plate_rows = await db.execute(text("""
        SELECT
            UPPER(REPLACE(REPLACE(t.plate, ' ', ''), '-', '')) AS plate_norm,
            t.plate,
            COUNT(*) AS ticket_count,
            MIN(t.issued_at) AS first_ticket,
            MAX(t.issued_at) AS latest_ticket,
            MAX(t.owner_name) AS owner_name,
            COALESCE(SUM(t.fine_amount), 0) AS unpaid_amount
        FROM tickets t
        WHERE t.status NOT IN ('paid', 'voided', 'resolved_permit', 'warning')
          AND COALESCE(t.fine_amount, 0) > 0
        GROUP BY plate_norm, t.plate
        HAVING COUNT(*) >= 3
        ORDER BY MAX(t.issued_at) DESC
    """))

    # Registration holds are tracked separately from conduct referrals and are
    # only lifted by payment — a resolved conduct case can still carry a hold.
    hold_rows = await db.execute(text("""
        SELECT student_id,
               UPPER(REPLACE(REPLACE(COALESCE(plate, ''), ' ', ''), '-', '')) AS plate_norm
        FROM escalation_log
        WHERE escalation_type = 'registration_hold' AND resolved_at IS NULL
    """))
    held_student_ids: set[str] = set()
    held_plates: set[str] = set()
    for h in hold_rows.mappings():
        if h["student_id"]:
            held_student_ids.add(h["student_id"])
        if h["plate_norm"]:
            held_plates.add(h["plate_norm"])

    # Build one case per plate, then deduplicate by student identity
    plate_cases: list[dict] = []
    for row in plate_rows.mappings():
        plate = row["plate"]
        plate_norm = row["plate_norm"]

        # Look up permit/tag for this plate
        permit_info = None
        moravian_id = ""
        okta_sub = ""
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
            permit_info = _permit_info(permit)
            moravian_id = permit.moravian_id or ""
            okta_sub = permit.student_id or ""
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

        moravian_id, student_email, student_name = await _enrich_student_fields(
            moravian_id, student_email, student_name, okta_sub=okta_sub
        )

        plate_cases.append({
            "id": str(esc["id"]) if esc else f"plate:{plate_norm}",
            "student_id": moravian_id,
            "student_name": student_name,
            "student_email": student_email,
            "plate": plate,
            "plate_norm": plate_norm,
            "ticket_count": row["ticket_count"],
            "unpaid_amount": float(row["unpaid_amount"] or 0),
            "hold_active": plate_norm in held_plates or bool(okta_sub and okta_sub in held_student_ids),
            "ticket_ids": [],
            "status": esc_status,
            "details": esc["details"] if esc else None,
            "created_at": (esc["created_at"].isoformat() if esc and esc["created_at"]
                           else row["first_ticket"].isoformat() if row["first_ticket"] else None),
            "resolved_at": esc["resolved_at"].isoformat() if esc and esc["resolved_at"] else None,
            "resolved_by": esc["resolved_by"] if esc else None,
            "permit": permit_info,
        })

    # Deduplicate: merge cases that share the same student identity.
    # A student with two plates (e.g. switched cars) should appear once with
    # combined ticket counts and plates shown.
    cases: list[dict] = []
    seen_students: dict[str, int] = {}  # identity key → index in cases

    for c in plate_cases:
        # Build a stable identity key from email or student_id (Okta sub)
        identity = (c["student_email"] or "").strip().lower()
        if not identity:
            identity = (c["student_id"] or "").strip()

        if identity and identity in seen_students:
            # Merge into existing case
            idx = seen_students[identity]
            existing = cases[idx]
            existing["ticket_count"] += c["ticket_count"]
            existing["unpaid_amount"] += c["unpaid_amount"]
            existing["hold_active"] = existing["hold_active"] or c["hold_active"]
            # Keep the plate with more tickets as primary; list others
            other_plates = existing.get("other_plates", [])
            other_plates.append(c["plate"])
            existing["other_plates"] = other_plates
            # Use the most recent created_at
            if c["created_at"] and (not existing["created_at"] or c["created_at"] > existing["created_at"]):
                existing["created_at"] = c["created_at"]
            # Prefer non-resolved status
            if existing["status"] == "resolved" and c["status"] != "resolved":
                existing["status"] = c["status"]
        else:
            c["other_plates"] = []
            cases.append(c)
            if identity:
                seen_students[identity] = len(cases) - 1

    # Strip internal fields before returning
    for c in cases:
        c.pop("plate_norm", None)

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
    """Build a case detail from tickets for a plate that has no escalation_log entry.

    Also pulls in tickets from other plates belonging to the same student
    (via permit student_id or email) so multi-vehicle students aren't fragmented.
    """
    # Get all tickets for this plate
    t_result = await db.execute(
        select(Ticket).where(
            text("UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :p")
        ).params(p=plate_norm).order_by(Ticket.issued_at.desc())
    )
    all_tickets = list(t_result.scalars().all())
    if not all_tickets:
        raise HTTPException(404, "No tickets found for this plate")

    plate = all_tickets[0].plate
    owner_name = next((t.owner_name for t in all_tickets if t.owner_name), None)
    notification_email = next((t.notification_email for t in all_tickets if t.notification_email), None)

    # Look up permit
    permit_info = None
    moravian_id = ""
    okta_sub = ""
    other_plates: list[str] = []
    p_result = await db.execute(
        select(Permit).where(
            Permit.deleted_at.is_(None),
            Permit.status != "cancelled",
            Permit.plates.any(plate_norm),
        ).order_by(Permit.is_tag_only.asc())
    )
    permit = p_result.scalars().first()
    if permit:
        moravian_id = permit.moravian_id or ""
        okta_sub = permit.student_id or ""
        owner_name = permit.name or owner_name
        notification_email = permit.email or notification_email
        permit_info = _permit_info(permit)

        # Find tickets on other plates belonging to this same student
        seen_ids = {t.id for t in all_tickets}
        if okta_sub:
            other_p_result = await db.execute(
                select(Permit).where(
                    Permit.student_id == okta_sub,
                    Permit.deleted_at.is_(None),
                    Permit.is_tag_only.is_(False),
                )
            )
            for op in other_p_result.scalars().all():
                for op_plate in (op.plates or []):
                    op_norm = op_plate.upper().replace(" ", "").replace("-", "")
                    if op_norm == plate_norm:
                        continue
                    extra_result = await db.execute(
                        select(Ticket).where(
                            text("UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :p")
                        ).params(p=op_norm).order_by(Ticket.issued_at.desc())
                    )
                    for et in extra_result.scalars().all():
                        if et.id not in seen_ids:
                            all_tickets.append(et)
                            seen_ids.add(et.id)
                            if op_plate not in other_plates:
                                other_plates.append(op_plate)

    unpaid = [t for t in all_tickets if t.status not in ("paid", "voided", "resolved_permit", "warning")]
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
            "_tag": "referral" if t.status not in ("paid", "voided", "resolved_permit", "warning") else "history",
            "_prior_conduct": False,
        })

    mid, semail, sname = await _enrich_student_fields(
        moravian_id, notification_email or "", owner_name or "",
        okta_sub=okta_sub,
    )

    hold_status = await _hold_status(db, mid, okta_sub, plate_norm)

    return {
        "id": f"plate:{plate_norm}",
        "student_id": mid,
        "student_name": sname,
        "student_email": semail,
        "plate": plate,
        "other_plates": other_plates,
        "ticket_count": len(unpaid),
        "status": "sent",
        "details": None,
        "created_at": all_tickets[-1].issued_at.isoformat() if all_tickets[-1].issued_at else None,
        "resolved_at": None,
        "resolved_by": None,
        "permit": permit_info,
        "tickets": tickets,
        "hold_status": hold_status,
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

    # Fetch ALL tickets for this student via live strategies only.
    # Do NOT seed with stored referral_ids — those may be contaminated
    # from the old tag cross-reference bug.
    all_ids: set[str] = set()

    # Strategy 1: by student_id on real permits (exclude vehicle tags)
    if case_row["student_id"]:
        sid = case_row["student_id"]
        sid_result = await db.execute(text("""
            SELECT DISTINCT t.id::text FROM tickets t
            JOIN permits p ON UPPER(t.plate) = ANY(SELECT UPPER(unnest(p.plates)))
            WHERE p.student_id = :sid AND p.deleted_at IS NULL
              AND p.is_tag_only = false
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
                      AND p.is_tag_only = false
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
                if tag == "history" and t.status not in ("paid", "voided", "resolved_permit", "warning"):
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

    # Get permit/tag and resolve moravian_id
    permit_info = None
    permit = None
    if case_row["student_id"]:
        p_result = await db.execute(
            select(Permit).where(
                Permit.student_id == case_row["student_id"],
                Permit.deleted_at.is_(None),
                Permit.status != "cancelled",
            ).order_by(Permit.is_tag_only.asc())
        )
        permit = p_result.scalars().first()

    if not permit and case_row["plate"]:
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
        permit_info = _permit_info(permit)

    moravian_id = (permit.moravian_id or "") if permit else ""
    okta_sub = case_row["student_id"] or ((permit.student_id or "") if permit else "")

    mid, semail, sname = await _enrich_student_fields(
        moravian_id,
        case_row["student_email"] or "",
        case_row["student_name"] or "",
        okta_sub=okta_sub,
    )

    # Use live ticket count instead of the stale snapshot stored at creation
    unpaid_tickets = [t for t in tickets if t["status"] not in ("paid", "voided", "resolved_permit", "warning")]
    live_count = len(unpaid_tickets) if tickets else case_row["ticket_count"]

    hold_status = await _hold_status(
        db, mid, case_row["student_id"] or okta_sub,
        (case_row["plate"] or "").upper().replace(" ", "").replace("-", ""),
    )

    return {
        "id": str(case_row["id"]),
        "student_id": mid,
        "student_name": sname,
        "student_email": semail,
        "plate": case_row["plate"],
        "ticket_count": live_count,
        "status": case_row["status"],
        "details": case_row["details"],
        "created_at": case_row["created_at"].isoformat() if case_row["created_at"] else None,
        "resolved_at": case_row["resolved_at"].isoformat() if case_row["resolved_at"] else None,
        "resolved_by": case_row["resolved_by"],
        "permit": permit_info,
        "tickets": tickets,
        "hold_status": hold_status,
    }


async def _hold_status(db: AsyncSession, moravian_id: str, student_id: str, plate_norm: str) -> dict:
    """Registration hold state in Quarry and (live) in Jenzabar.

    Independent of the conduct case — the hold stays until tickets are paid.
    """
    jenzabar_hold_active = None
    if moravian_id and moravian_id.strip().isdigit():
        from ..services.sis_hold_service import check_jenzabar_hold
        jenzabar_hold_active = await check_jenzabar_hold(moravian_id)

    quarry_hold_result = await db.execute(text("""
        SELECT 1 FROM escalation_log
        WHERE escalation_type = 'registration_hold' AND resolved_at IS NULL
          AND ((:sid <> '' AND student_id = :sid)
               OR (:plate <> '' AND UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :plate))
        LIMIT 1
    """), {"sid": student_id or "", "plate": plate_norm or ""})
    quarry_hold_active = quarry_hold_result.scalar() is not None

    return {
        "quarry": quarry_hold_active,
        "jenzabar": jenzabar_hold_active,
        "synced": jenzabar_hold_active == quarry_hold_active if jenzabar_hold_active is not None else None,
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
          AND status NOT IN ('paid', 'voided', 'resolved_permit', 'warning')
          AND COALESCE(fine_amount, 0) > 0
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
    name = (permit.name if permit else None) or name or ""
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


class VerifyOwnerRequest(BaseModel):
    email: str = ""


async def _case_plate_norm(case_id: str, db: AsyncSession) -> str:
    if case_id.startswith("plate:"):
        return case_id[6:]
    row = await db.execute(text("""
        SELECT plate FROM escalation_log
        WHERE id = :case_id AND escalation_type = 'conduct_referral'
    """), {"case_id": case_id})
    plate = row.scalar()
    if not plate:
        raise HTTPException(404, "Case not found")
    return plate.upper().replace(" ", "").replace("-", "")


@router.post("/cases/{case_id}/verify-owner")
async def verify_tag_owner(
    case_id: str,
    body: VerifyOwnerRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_conduct),
):
    """Confirm who owns a tagged vehicle so its tickets count toward a registration hold.

    Admin-only: this can place an academic hold in Jenzabar.
    """
    if not user.is_admin:
        raise HTTPException(403, "Only parking admins can verify vehicle owners")

    plate_norm = await _case_plate_norm(case_id, db)
    tags = list((await db.execute(
        select(Permit).where(
            Permit.is_tag_only.is_(True),
            Permit.deleted_at.is_(None),
            Permit.plates.any(plate_norm),
        )
    )).scalars().all())
    if not tags:
        raise HTTPException(400, "No vehicle tag on this plate — permit holders are already covered by holds")

    email = (body.email or next((t.email for t in tags if t.email and "@" in t.email), "")).strip().lower()
    if not email or "@" not in email:
        raise HTTPException(400, "No email to verify — enter the student's university email")

    okta = await _lookup_okta_user(email)
    if not okta or not okta.get("sub"):
        raise HTTPException(400, f"{email} was not found in Okta — can't verify this owner")

    now = datetime.now(timezone.utc)
    for tag in tags:
        tag.owner_student_id = okta["sub"]
        tag.owner_verified_at = now
        tag.owner_verified_by = user.email
        tag.email = okta["email"] or email
        if okta.get("moravian_id"):
            tag.moravian_id = okta["moravian_id"]
    await db.flush()

    await db.execute(text("""
        UPDATE escalation_log SET student_id = :sid
        WHERE escalation_type = 'conduct_referral'
          AND COALESCE(student_id, '') = ''
          AND UPPER(REPLACE(REPLACE(plate, ' ', ''), '-', '')) = :plate
    """), {"sid": okta["sub"], "plate": plate_norm})

    from ..services.escalation import apply_registration_hold_if_needed
    try:
        actions = await apply_registration_hold_if_needed(
            db, okta["sub"], okta["name"] or tags[0].name, okta["email"] or email, tags[0].plates[0] if tags[0].plates else plate_norm,
        )
    except Exception as e:
        error_reporting.capture_exception(e)
        _logger.error("Hold check failed after verifying owner of %s: %s", plate_norm, e, exc_info=True)
        raise HTTPException(500, "Hold check failed, so the verification was not saved — try again")

    _logger.info(
        "Tag owner verified: plate=%s email=%s moravian_id=%s by=%s actions=%s",
        plate_norm, email, okta.get("moravian_id"), user.email, actions,
    )
    return {
        "ok": True,
        "email": okta["email"] or email,
        "moravian_id": okta.get("moravian_id"),
        "unpaid_count": actions.get("unpaid_count"),
        "hold_applied": bool(actions.get("registration_hold")),
        "already_held": bool(actions.get("already_held")),
        "jenzabar_hold_set": actions.get("jenzabar_hold_set"),
    }


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
            if body.student_email.strip().lower() != (tag.email or "").strip().lower():
                from ..services.escalation import clear_tag_verification
                await clear_tag_verification(db, tag, user.email)
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


# ── Jenzabar hold lookup / manual removal ────────────────────────────

async def _jenzabar_hold_summary(db: AsyncSession, moravian_id: str) -> dict:
    from ..services.escalation import _count_unpaid_tickets_for_student, is_person_student_id
    from ..services.sis_hold_service import check_jenzabar_hold

    sid_rows = await db.execute(
        select(Permit.student_id, Permit.name, Permit.email).where(
            Permit.moravian_id == moravian_id, Permit.deleted_at.is_(None),
        ).order_by(Permit.created_at.desc())
    )
    rows = sid_rows.all()
    student_ids = sorted({r[0] for r in rows if is_person_student_id(r[0])})
    unpaid = 0
    for sid in student_ids:
        unpaid = max(unpaid, await _count_unpaid_tickets_for_student(db, sid))
    quarry_hold = (await db.execute(text("""
        SELECT 1 FROM escalation_log
        WHERE escalation_type = 'registration_hold' AND resolved_at IS NULL
          AND student_id = ANY(:sids)
        LIMIT 1
    """), {"sids": student_ids + [moravian_id]})).scalar() is not None
    return {
        "moravian_id": moravian_id,
        "name": rows[0][1] if rows else None,
        "email": rows[0][2] if rows else None,
        "unpaid_tickets": unpaid,
        "hold_threshold": settings.registration_hold_threshold,
        "quarry_hold_active": quarry_hold,
        "jenzabar_hold_active": await check_jenzabar_hold(moravian_id),
        "student_ids": student_ids,
    }


@router.get("/jenzabar-hold/{moravian_id}")
async def jenzabar_hold_lookup(
    moravian_id: str,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_conduct),
):
    moravian_id = moravian_id.strip()
    if not moravian_id.isdigit():
        raise HTTPException(400, "Enter the numeric Moravian ID")
    return await _jenzabar_hold_summary(db, moravian_id)


@router.post("/jenzabar-hold/{moravian_id}/release")
async def jenzabar_hold_release(
    moravian_id: str,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    """Send the removal flag (N) to Jenzabar and close any open Quarry hold record."""
    from ..services.escalation import resolve_escalation
    from ..services.sis_hold_service import set_jenzabar_hold

    moravian_id = moravian_id.strip()
    if not moravian_id.isdigit():
        raise HTTPException(400, "Enter the numeric Moravian ID")
    before = await _jenzabar_hold_summary(db, moravian_id)
    ok = await set_jenzabar_hold(moravian_id, apply=False)
    if not ok:
        error_reporting.capture_message(
            f"Manual Jenzabar hold removal FAILED for moravian_id={moravian_id} by {user.email}", level="error",
        )
        raise HTTPException(502, "Jenzabar did not accept the removal. Check the logs or contact Paul Edinger.")
    for sid in before["student_ids"] + [moravian_id]:
        await resolve_escalation(db, sid, "registration_hold", f"manual:{user.email}")
    await db.flush()
    _logger.info(
        "Manual Jenzabar hold removal for moravian_id=%s by %s (unpaid=%d, quarry_hold=%s, jenzabar_before=%s)",
        moravian_id, user.email, before["unpaid_tickets"], before["quarry_hold_active"], before["jenzabar_hold_active"],
    )
    return {"sent": True, "before": before}
