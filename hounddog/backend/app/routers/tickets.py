import uuid
from app import error_reporting
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from ..utils.safe_router import SafeRouter
from sqlalchemy import select, func, or_, cast, Date, String, text, bindparam
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..auth.okta import get_current_user, OktaUser, require_admin, require_office, require_role
from ..config import settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.legacy_record import LegacyRecord
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..services.timeutils import campus_tz, today_local, to_local
from ..services.email import send_citation_email, send_plate_correction_dismissal_email
from ..schemas.ticket import (
    ActionItem,
    ActivityEvent,
    AppealDecision,
    AppealRequest,
    DashboardData,
    IssuedCount,
    NeedsAction,
    ResolutionRate,
    Revenue,
    TicketCreate,
    TicketList,
    TicketPipeline,
    TicketRead,
    TicketUpdate,
    TrendDay,
    VoidRequest,
)

router = SafeRouter(dependencies=[Depends(get_current_user)])
public_router = SafeRouter()

VALID_STATUSES = {"issued", "warning", "pending_payment", "paid", "appealed", "escalated", "voided", "resolved_permit", "overdue", "past_due"}

VISITOR_PERMIT_TYPES = {"visitor_day", "visitor_vendor", "visitor_vendor_longterm", "visitor_contracted_staff", "contracted_staff"}


@router.get("/enforcement-audit")
async def enforcement_audit(
    days: int = Query(7, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_office()),
):
    """Return tickets from the last N days where the cited plate had an active permit
    that likely authorized parking in that lot — potential false citations."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    tickets_result = await db.execute(
        select(Ticket).where(
            Ticket.issued_at >= cutoff,
            Ticket.status.notin_(["voided", "warning"]),
        ).order_by(Ticket.issued_at.desc())
    )
    tickets = tickets_result.scalars().all()

    flagged = []
    for t in tickets:
        if not t.plate:
            continue
        # Find active permits for this plate at time of ticketing
        raw_plate = t.plate.upper()
        norm_plate = raw_plate.replace(" ", "").replace("-", "")
        permit_result = await db.execute(
            select(Permit).where(
                or_(
                    Permit.plates.contains([raw_plate]),
                    Permit.plates.contains([norm_plate]),
                ),
                Permit.status == "active",
                Permit.deleted_at.is_(None),
                Permit.start_date <= t.issued_at,
                or_(Permit.end_date.is_(None), Permit.end_date >= t.issued_at),
            )
        )
        permits = permit_result.scalars().all()
        if not permits:
            continue

        for p in permits:
            pt = (p.permit_type or "").lower()
            lot = (t.lot or "").strip().upper()
            assigned = {l.strip().upper() for l in (p.lot_assignment or "").split(",") if l.strip()}

            reason = None
            if pt in VISITOR_PERMIT_TYPES:
                reason = f"Active {pt.replace('_', ' ')} permit — authorized in all lots"
            elif lot and lot in assigned:
                reason = f"Active {pt.replace('_', ' ')} permit assigned to lot {lot}"

            if reason:
                flagged.append({
                    "ticket_id": str(t.id),
                    "ticket_number": t.ticket_number,
                    "plate": t.plate,
                    "lot": t.lot,
                    "violation_type": t.violation_type,
                    "fine_amount": str(t.fine_amount) if t.fine_amount else "0.00",
                    "issued_at": t.issued_at.isoformat() if t.issued_at else None,
                    "status": t.status,
                    "officer_name": t.officer_name,
                    "permit_name": p.name,
                    "permit_type": p.permit_type,
                    "permit_lot_assignment": p.lot_assignment,
                    "reason": reason,
                    "enforcement_warning": t.enforcement_warning,
                    "override_reason": t.override_reason,
                })
                break

    return {"flagged": flagged, "total_tickets": len(tickets), "total_flagged": len(flagged)}


@router.get("")
async def list_tickets(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    category: str | None = None,
    violation_type: str | None = None,
    officer_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = Query(None),
    sort_order: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    query = select(Ticket)

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                Ticket.plate.ilike(like),
                Ticket.officer_id.ilike(like),
                Ticket.ticket_number.ilike(like),
                Ticket.officer_name.ilike(like),
                Ticket.owner_name.ilike(like),
                Ticket.location_text.ilike(like),
                Ticket.vehicle_description.ilike(like),
                cast(Ticket.id, String).ilike(like),
            )
        )
    if status:
        query = query.where(Ticket.status == status)
    if lot:
        query = query.where(Ticket.lot == lot)
    if category:
        query = query.where(Ticket.ticket_category == category)
    if violation_type:
        query = query.where(Ticket.violation_type == violation_type)
    if officer_email:
        query = query.where(Ticket.officer_email == officer_email)
    if date_from:
        try:
            from datetime import datetime as _dt
            dt_from = _dt.fromisoformat(date_from)
            query = query.where(Ticket.issued_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime as _dt, timedelta as _td
            dt_to = _dt.fromisoformat(date_to) + _td(days=1)
            query = query.where(Ticket.issued_at < dt_to)
        except ValueError:
            pass

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Server-side sorting
    TICKET_SORT_FIELDS = {
        "ticket_number": Ticket.ticket_number,
        "plate": Ticket.plate,
        "owner_name": Ticket.owner_name,
        "lot": Ticket.lot,
        "violation_type": Ticket.violation_type,
        "fine_amount": Ticket.fine_amount,
        "status": Ticket.status,
        "officer_name": Ticket.officer_name,
        "issued_at": Ticket.issued_at,
    }
    sort_col = TICKET_SORT_FIELDS.get(sort_by or "", Ticket.issued_at)
    order_clause = sort_col.asc() if sort_order == "ascend" else sort_col.desc()

    items = (
        await db.execute(
            query.order_by(order_clause)
            .options(defer(Ticket.photo_data))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    # Batch-check which plates have legacy Omnigo records
    plates = list({t.plate.upper().replace(" ", "").replace("-", "") for t in items if t.plate})
    legacy_plates: set[str] = set()
    if plates:
        legacy_result = await db.execute(
            select(LegacyRecord.plate_normalized).where(
                LegacyRecord.plate_normalized.in_(plates)
            )
        )
        legacy_plates = {r[0] for r in legacy_result}

    # Batch-check which tickets have conduct escalations
    ticket_ids_str = [str(t.id) for t in items]
    conduct_tickets: dict[str, dict] = {}
    if ticket_ids_str:
        try:
            # Fetch ALL escalations (including resolved) so we can show the full picture:
            # - Active registration hold even if conduct referral was resolved
            # - "Conduct resolved" badge so admin knows meeting was scheduled
            esc_result = await db.execute(
                text("""
                    SELECT id, ticket_ids, escalation_type, status, student_name,
                           created_at, resolved_at, resolved_by
                    FROM escalation_log
                    ORDER BY created_at DESC
                """)
            )
            # Group by ticket: prefer active (unresolved) holds, then active conduct,
            # then resolved conduct. Also track if a hold exists separately.
            ticket_holds: dict[str, dict] = {}
            for row in esc_result.mappings().all():
                tids = (row["ticket_ids"] or "").split(",")
                for tid in tids:
                    tid = tid.strip()
                    if tid not in ticket_ids_str:
                        continue
                    entry = {
                        "escalation_type": row["escalation_type"],
                        "escalation_status": row["status"],
                        "escalation_student": row["student_name"],
                        "resolved": row["resolved_at"] is not None,
                        "resolved_by": row["resolved_by"],
                    }
                    if row["escalation_type"] == "registration_hold" and not row["resolved_at"]:
                        # Active hold always takes priority
                        ticket_holds[tid] = entry
                    elif tid not in ticket_holds:
                        conduct_tickets[tid] = entry
                    elif tid in conduct_tickets and conduct_tickets[tid].get("resolved") and not entry.get("resolved"):
                        # Replace resolved entry with active one
                        conduct_tickets[tid] = entry

            # Merge: active holds override conduct entries
            for tid, hold in ticket_holds.items():
                existing = conduct_tickets.get(tid)
                if existing and existing["escalation_type"] == "conduct_referral":
                    # Keep both: show hold as primary, note conduct was resolved
                    hold["conduct_resolved"] = existing.get("resolved", False)
                conduct_tickets[tid] = hold
        except Exception:
            await db.rollback()

    enriched = []
    for t in items:
        d = TicketRead.model_validate(t).model_dump()
        norm = t.plate.upper().replace(" ", "").replace("-", "") if t.plate else ""
        d["has_legacy"] = norm in legacy_plates
        esc = conduct_tickets.get(str(t.id))
        d["conduct_escalation"] = esc  # None or {escalation_type, escalation_status, ...}
        enriched.append(d)

    return {"items": enriched, "total": total, "page": page, "page_size": page_size}


@router.get("/export/csv")
async def export_tickets_csv(
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    category: str | None = None,
    violation_type: str | None = None,
    officer_email: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort_by: str | None = Query(None),
    sort_order: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    """Export filtered tickets as CSV. Same filters as the list endpoint."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    query = select(Ticket)

    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                Ticket.plate.ilike(like),
                Ticket.officer_id.ilike(like),
                Ticket.ticket_number.ilike(like),
                Ticket.officer_name.ilike(like),
                Ticket.owner_name.ilike(like),
                Ticket.location_text.ilike(like),
                Ticket.vehicle_description.ilike(like),
                cast(Ticket.id, String).ilike(like),
            )
        )
    if status:
        query = query.where(Ticket.status == status)
    if lot:
        query = query.where(Ticket.lot == lot)
    if category:
        query = query.where(Ticket.ticket_category == category)
    if violation_type:
        query = query.where(Ticket.violation_type == violation_type)
    if officer_email:
        query = query.where(Ticket.officer_email == officer_email)
    if date_from:
        try:
            from datetime import datetime as _dt
            dt_from = _dt.fromisoformat(date_from)
            query = query.where(Ticket.issued_at >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            from datetime import datetime as _dt, timedelta as _td
            dt_to = _dt.fromisoformat(date_to) + _td(days=1)
            query = query.where(Ticket.issued_at < dt_to)
        except ValueError:
            pass

    TICKET_SORT_FIELDS = {
        "ticket_number": Ticket.ticket_number,
        "plate": Ticket.plate,
        "owner_name": Ticket.owner_name,
        "lot": Ticket.lot,
        "violation_type": Ticket.violation_type,
        "fine_amount": Ticket.fine_amount,
        "status": Ticket.status,
        "officer_name": Ticket.officer_name,
        "issued_at": Ticket.issued_at,
    }
    sort_col = TICKET_SORT_FIELDS.get(sort_by or "", Ticket.issued_at)
    order_clause = sort_col.asc() if sort_order == "ascend" else sort_col.desc()

    tickets = (
        await db.execute(
            query.order_by(order_clause)
            .options(defer(Ticket.photo_data))
            .limit(10000)
        )
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Ticket #", "Plate", "Owner Name", "Email", "Lot", "Zone",
        "Violation", "Fine", "Status", "Appeal", "Officer", "Issued",
        "Category", "Vehicle", "Permit #", "Permit Type",
    ])
    for t in tickets:
        writer.writerow([
            t.ticket_number or "",
            t.plate or "",
            t.owner_name or "",
            t.notification_email or "",
            t.lot or "",
            t.zone or "",
            (t.violation_type or "").replace("_", " "),
            f"{float(t.fine_amount):.2f}" if t.fine_amount else "",
            t.status or "",
            t.appeal_decision or "",
            t.officer_name or "",
            t.issued_at.strftime("%Y-%m-%d %H:%M") if t.issued_at else "",
            t.ticket_category or "parking",
            t.vehicle_description or "",
            t.permit_number or "",
            t.permit_type_label or "",
        ])

    buf.seek(0)
    now_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"tickets_{now_str}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _resolve_range(range_key: str, now: datetime) -> datetime | None:
    """Return the cutoff datetime for a given range key, or None for all-time."""
    if range_key == "24h":
        return now - timedelta(hours=24)
    if range_key == "7d":
        return (now - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "30d":
        return (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "90d":
        return (now - timedelta(days=90)).replace(hour=0, minute=0, second=0, microsecond=0)
    if range_key == "ytd":
        return now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return None  # "all"


def _timeline_days(cutoff: datetime | None, now: datetime) -> int:
    """Number of day-buckets for the daily activity timeline."""
    if cutoff is None:
        # All-time: show last 90 days of timeline
        return 90
    delta = (now - cutoff).days
    return max(delta, 1)


async def _officer_stats_for_email(email: str, db: AsyncSession, now: datetime, cutoff: datetime | None = None) -> dict:
    """Compute full stats for a single officer email. Shared by my-stats and officer-report.

    When *cutoff* is set, all aggregate queries are scoped to tickets issued on or after that datetime.
    """
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Base filters
    base = select(func.count()).where(Ticket.officer_email == email)
    scoped = base.where(Ticket.issued_at >= cutoff) if cutoff else base

    range_total = (await db.execute(scoped)).scalar() or 0
    this_week = (await db.execute(base.where(Ticket.issued_at >= week_start))).scalar() or 0
    this_month = (await db.execute(base.where(Ticket.issued_at >= month_start))).scalar() or 0

    time_filter = [Ticket.officer_email == email]
    if cutoff:
        time_filter.append(Ticket.issued_at >= cutoff)

    # By violation
    by_violation_rows = (await db.execute(
        select(Ticket.violation_type, func.count().label("cnt"))
        .where(*time_filter)
        .group_by(Ticket.violation_type).order_by(func.count().desc())
    )).all()

    vt_codes = [r[0] for r in by_violation_rows]
    label_map: dict[str, str] = {}
    if vt_codes:
        vt_result = await db.execute(
            select(ViolationType.code, ViolationType.label).where(ViolationType.code.in_(vt_codes))
        )
        label_map = {r[0]: r[1] for r in vt_result.all()}
    by_violation = [{"violation_type": r[0], "label": label_map.get(r[0], r[0]), "count": r[1]} for r in by_violation_rows]

    # By status
    by_status = [{"status": r[0], "count": r[1]} for r in (await db.execute(
        select(Ticket.status, func.count().label("cnt"))
        .where(*time_filter)
        .group_by(Ticket.status).order_by(func.count().desc())
    )).all()]

    # Daily activity timeline
    timeline_days = _timeline_days(cutoff, now)
    timeline_start = (now - timedelta(days=timeline_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_q = (
        select(cast(Ticket.issued_at, Date).label("day"), func.count().label("cnt"))
        .where(Ticket.officer_email == email, Ticket.issued_at >= timeline_start)
        .group_by("day").order_by("day")
    )
    daily_rows = (await db.execute(daily_q)).all()
    daily_map = {str(r[0]): r[1] for r in daily_rows}
    daily_activity = []
    for i in range(timeline_days):
        d = (timeline_start + timedelta(days=i)).strftime("%Y-%m-%d")
        daily_activity.append({"date": d, "count": daily_map.get(d, 0)})

    # By lot
    by_lot = [{"lot": r[0] or "Unknown", "count": r[1]} for r in (await db.execute(
        select(Ticket.lot, func.count().label("cnt"))
        .where(*time_filter)
        .group_by(Ticket.lot).order_by(func.count().desc())
    )).all()]

    # By hour
    by_hour_rows = (await db.execute(
        select(func.extract("hour", Ticket.issued_at).label("hr"), func.count().label("cnt"))
        .where(*time_filter)
        .group_by("hr").order_by("hr")
    )).all()
    hour_map = {int(r[0]): r[1] for r in by_hour_rows}
    by_hour = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    # Appeal/void rates
    status_counts = {s["status"]: s["count"] for s in by_status}
    voided = status_counts.get("voided", 0)
    appealed = status_counts.get("appealed", 0)
    void_rate = round((voided / range_total) * 100, 1) if range_total else 0
    appeal_rate = round((appealed / range_total) * 100, 1) if range_total else 0

    # Revenue
    total_fines = float((await db.execute(
        select(func.coalesce(func.sum(Ticket.fine_amount), 0))
        .where(*time_filter)
    )).scalar() or 0)
    paid_fines = float((await db.execute(
        select(func.coalesce(func.sum(Ticket.fine_amount), 0))
        .where(*time_filter, Ticket.status == "paid")
    )).scalar() or 0)

    return {
        "this_week": this_week,
        "this_month": this_month,
        "all_time": range_total,
        "by_violation": by_violation,
        "by_status": by_status,
        "daily_activity": daily_activity,
        "by_lot": by_lot,
        "by_hour": by_hour,
        "appeal_void_rate": {
            "voided": voided, "appealed": appealed,
            "void_rate": void_rate, "appeal_rate": appeal_rate,
        },
        "revenue": {"total_fines": round(total_fines, 2), "paid_fines": round(paid_fines, 2)},
    }


@router.get("/my-stats")
async def my_ticket_stats(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    time_range: str = Query("all"),
):
    """Officer performance stats for the logged-in user."""
    now = datetime.now(timezone.utc)
    cutoff = _resolve_range(time_range, now)
    stats = await _officer_stats_for_email(user.email, db, now, cutoff)

    total_q = select(func.count()).select_from(Ticket)
    if cutoff:
        total_q = total_q.where(Ticket.issued_at >= cutoff)
    total_all = (await db.execute(total_q)).scalar() or 0
    stats["global_share"] = round((stats["all_time"] / total_all) * 100, 1) if total_all else 0
    stats["total_all"] = total_all
    return stats


@router.get("/officer-report")
async def officer_report(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
    time_range: str = Query("all"),
):
    """Admin-only: performance stats for every officer."""
    now = datetime.now(timezone.utc)
    cutoff = _resolve_range(time_range, now)

    total_q = select(func.count()).select_from(Ticket)
    if cutoff:
        total_q = total_q.where(Ticket.issued_at >= cutoff)
    total_all = (await db.execute(total_q)).scalar() or 0

    # Get all officer emails (within range)
    officer_emails_q = select(Ticket.officer_email).where(Ticket.officer_email.isnot(None))
    if cutoff:
        officer_emails_q = officer_emails_q.where(Ticket.issued_at >= cutoff)
    officer_emails_q = officer_emails_q.group_by(Ticket.officer_email)
    officer_emails = [r[0] for r in (await db.execute(officer_emails_q)).all()]

    # Build per-officer stats using the shared helper
    officers = []
    for email in officer_emails:
        stats = await _officer_stats_for_email(email, db, now, cutoff)
        officer_name_row = (await db.execute(
            select(Ticket.officer_name).where(Ticket.officer_email == email, Ticket.officer_name.isnot(None))
            .order_by(Ticket.issued_at.desc()).limit(1)
        )).scalar()
        stats["officer_email"] = email
        stats["officer_name"] = officer_name_row
        stats["global_share"] = round((stats["all_time"] / total_all) * 100, 1) if total_all else 0
        officers.append(stats)

    officers.sort(key=lambda o: o["all_time"], reverse=True)

    # Team-wide daily totals
    timeline_days = _timeline_days(cutoff, now)
    timeline_start = (now - timedelta(days=timeline_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_total_rows = (await db.execute(
        select(cast(Ticket.issued_at, Date).label("day"), func.count().label("cnt"))
        .where(Ticket.issued_at >= timeline_start)
        .group_by("day").order_by("day")
    )).all()
    daily_total_map = {str(r[0]): r[1] for r in daily_total_rows}
    daily_total = []
    for i in range(timeline_days):
        d = (timeline_start + timedelta(days=i)).strftime("%Y-%m-%d")
        daily_total.append({"date": d, "count": daily_total_map.get(d, 0)})

    # Team-wide lot breakdown
    lot_q = select(Ticket.lot, func.count().label("cnt"))
    if cutoff:
        lot_q = lot_q.where(Ticket.issued_at >= cutoff)
    lot_q = lot_q.group_by(Ticket.lot).order_by(func.count().desc())
    by_lot_total = [{"lot": r[0] or "Unknown", "count": r[1]} for r in (await db.execute(lot_q)).all()]

    # Team-wide hour breakdown
    hour_q = select(func.extract("hour", Ticket.issued_at).label("hr"), func.count().label("cnt"))
    if cutoff:
        hour_q = hour_q.where(Ticket.issued_at >= cutoff)
    hour_q = hour_q.group_by("hr").order_by("hr")
    by_hour_total_rows = (await db.execute(hour_q)).all()
    hour_map = {int(r[0]): r[1] for r in by_hour_total_rows}
    by_hour_total = [{"hour": h, "count": hour_map.get(h, 0)} for h in range(24)]

    # Team-wide violation type breakdown with per-officer detail
    viol_total_q = select(Ticket.violation_type, func.count().label("cnt"))
    if cutoff:
        viol_total_q = viol_total_q.where(Ticket.issued_at >= cutoff)
    viol_total_q = viol_total_q.group_by(Ticket.violation_type).order_by(func.count().desc())
    viol_total_rows = (await db.execute(viol_total_q)).all()
    viol_codes = [r[0] for r in viol_total_rows]
    viol_label_map: dict[str, str] = {}
    if viol_codes:
        vt_r = await db.execute(
            select(ViolationType.code, ViolationType.label).where(ViolationType.code.in_(viol_codes))
        )
        viol_label_map = {r[0]: r[1] for r in vt_r.all()}

    # Per-officer counts for each violation type (within range)
    viol_officer_q = select(Ticket.violation_type, Ticket.officer_email, func.count().label("cnt")).where(Ticket.officer_email.isnot(None))
    if cutoff:
        viol_officer_q = viol_officer_q.where(Ticket.issued_at >= cutoff)
    viol_officer_q = viol_officer_q.group_by(Ticket.violation_type, Ticket.officer_email)
    viol_officer_rows = (await db.execute(viol_officer_q)).all()
    viol_officer_map: dict[str, list] = {}
    for vtype, email, cnt in viol_officer_rows:
        viol_officer_map.setdefault(vtype, []).append({"officer_email": email, "count": cnt})

    # Sort each violation's officers by count desc
    for vtype in viol_officer_map:
        viol_officer_map[vtype].sort(key=lambda x: x["count"], reverse=True)

    # Build officer name lookup
    officer_name_map = {o["officer_email"]: o.get("officer_name") or o["officer_email"].split("@")[0] for o in officers}
    for entries in viol_officer_map.values():
        for entry in entries:
            entry["officer_name"] = officer_name_map.get(entry["officer_email"], entry["officer_email"].split("@")[0])

    by_violation_total = [
        {
            "violation_type": r[0],
            "label": viol_label_map.get(r[0], r[0]),
            "count": r[1],
            "officers": viol_officer_map.get(r[0], []),
        }
        for r in viol_total_rows
    ]

    # Team-wide revenue (within range)
    rev_q = select(func.coalesce(func.sum(Ticket.fine_amount), 0))
    paid_q = select(func.coalesce(func.sum(Ticket.fine_amount), 0)).where(Ticket.status == "paid")
    if cutoff:
        rev_q = rev_q.where(Ticket.issued_at >= cutoff)
        paid_q = paid_q.where(Ticket.issued_at >= cutoff)
    total_revenue = float((await db.execute(rev_q)).scalar() or 0)
    paid_revenue = float((await db.execute(paid_q)).scalar() or 0)

    # Team-wide week/month (always absolute, not range-scoped)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    team_this_week = (await db.execute(select(func.count()).where(Ticket.issued_at >= week_start))).scalar() or 0
    team_this_month = (await db.execute(select(func.count()).where(Ticket.issued_at >= month_start))).scalar() or 0

    # Team avg void rate
    total_voided = sum(1 for o in officers for s in o["by_status"] if s["status"] == "voided" for _ in range(s["count"]))
    avg_void_rate = round((total_voided / total_all) * 100, 1) if total_all else 0

    return {
        "total_all": total_all,
        "team_this_week": team_this_week,
        "team_this_month": team_this_month,
        "team_revenue": {"total_fines": round(total_revenue, 2), "paid_fines": round(paid_revenue, 2)},
        "avg_void_rate": avg_void_rate,
        "daily_total": daily_total,
        "by_lot_total": by_lot_total,
        "by_hour_total": by_hour_total,
        "by_violation_total": by_violation_total,
        "officers": officers,
    }


_OPERATOR_REPORT_PREFIXES = {"dillardv", "brandesd"}


@router.get("/operator-report")
async def operator_report(
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
    time_range: str = Query("30d"),
):
    """Restricted to chief and super admin only."""
    # Super admins always have access; otherwise check the allowlist
    if not user.is_admin:
        email_prefix = user.email.lower().split("@")[0]
        if email_prefix not in _OPERATOR_REPORT_PREFIXES:
            raise HTTPException(403, "This report is restricted")

    now = datetime.now(timezone.utc)
    cutoff = _resolve_range(time_range, now)

    from ..models.audit_log import AuditLog

    base = select(AuditLog).where(
        AuditLog.user_email.notlike("device:%"),
        AuditLog.user_email != "anonymous",
        AuditLog.user_email != "diagnostic-test",
        AuditLog.action != "GET",
    )
    if cutoff:
        base = base.where(AuditLog.timestamp >= cutoff)

    rows = (await db.execute(base.order_by(AuditLog.timestamp.desc()))).scalars().all()

    # Classify each action into a meaningful category
    def _classify(entry: AuditLog) -> str | None:
        ep = entry.endpoint or ""
        method = entry.action or ""
        if ep.startswith("/api/sync/"):
            return None  # Device sync, not operator work
        if ep in ("/api/auth/me", "/api/auth/config", "/api/auth/config/public"):
            return None
        if "/tickets/" in ep and method == "PUT":
            return "ticket_update"
        if "/tickets/" in ep and "void" in ep:
            return "ticket_void"
        if "/tickets/" in ep and "bulk" in ep:
            return "bulk_action"
        if "appeal" in ep and "committee" in ep:
            return "appeal_committee"
        if "appeal" in ep or "deny" in ep:
            return "appeal_decision"
        if "/permits/" in ep and method == "POST":
            return "permit_create"
        if "/permits/" in ep and method in ("PUT", "PATCH"):
            return "permit_update"
        if "/permits/" in ep and "cancel" in ep:
            return "permit_cancel"
        if "/permits/" in ep and method == "DELETE":
            return "permit_delete"
        if "conduct" in ep:
            return "conduct"
        if "escalat" in ep:
            return "escalation"
        if "/payments/" in ep:
            return "payment"
        if "/lottery" in ep:
            return "lottery"
        if "/vehicle-tags" in ep:
            return "vehicle_tag"
        if "/mail-notices" in ep or "mail" in ep:
            return "mail_notice"
        if "/settings" in ep or "/config" in ep:
            return "settings"
        if "/lots/" in ep:
            return "lot_management"
        if method in ("POST", "PUT", "PATCH", "DELETE"):
            return "other"
        return None

    CATEGORY_LABELS = {
        "ticket_update": "Ticket Updates",
        "ticket_void": "Tickets Voided",
        "bulk_action": "Bulk Actions",
        "appeal_decision": "Appeal Decisions",
        "appeal_committee": "Committee Actions",
        "permit_create": "Permits Created",
        "permit_update": "Permits Updated",
        "permit_cancel": "Permits Cancelled",
        "permit_delete": "Permits Deleted",
        "conduct": "Conduct Cases",
        "escalation": "Escalations",
        "payment": "Payment Actions",
        "lottery": "Lottery Management",
        "vehicle_tag": "Vehicle Tags",
        "mail_notice": "Mail Notices",
        "settings": "Settings Changes",
        "lot_management": "Lot Management",
        "other": "Other Actions",
    }

    # Aggregate by operator
    operators: dict[str, dict] = {}
    daily_map: dict[str, int] = {}
    category_totals: dict[str, int] = {}

    for entry in rows:
        cat = _classify(entry)
        if cat is None:
            continue

        email = entry.user_email
        if email not in operators:
            operators[email] = {
                "email": email,
                "total": 0,
                "categories": {},
                "daily": {},
                "first_action": entry.timestamp.isoformat(),
                "last_action": entry.timestamp.isoformat(),
                "recent_actions": [],
            }

        op = operators[email]
        op["total"] += 1
        op["categories"][cat] = op["categories"].get(cat, 0) + 1

        day_str = entry.timestamp.strftime("%Y-%m-%d")
        op["daily"][day_str] = op["daily"].get(day_str, 0) + 1
        daily_map[day_str] = daily_map.get(day_str, 0) + 1

        category_totals[cat] = category_totals.get(cat, 0) + 1

        # Update first/last
        ts_iso = entry.timestamp.isoformat()
        if ts_iso < op["first_action"]:
            op["first_action"] = ts_iso
        if ts_iso > op["last_action"]:
            op["last_action"] = ts_iso

        # Keep last 10 recent actions
        if len(op["recent_actions"]) < 10:
            op["recent_actions"].append({
                "timestamp": ts_iso,
                "category": cat,
                "summary": entry.summary,
                "endpoint": entry.endpoint,
            })

    # Convert to sorted lists
    operator_list = sorted(operators.values(), key=lambda o: o["total"], reverse=True)

    # Build daily timeline
    if cutoff:
        timeline_days = max(1, (now - cutoff).days)
    else:
        timeline_days = 90
    timeline_start = (now - timedelta(days=timeline_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    daily_activity = []
    for i in range(timeline_days + 1):
        d = (timeline_start + timedelta(days=i)).strftime("%Y-%m-%d")
        daily_activity.append({"date": d, "count": daily_map.get(d, 0)})

    # Category breakdown with labels
    categories = [
        {"key": k, "label": CATEGORY_LABELS.get(k, k), "count": v}
        for k, v in sorted(category_totals.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "total_actions": sum(o["total"] for o in operator_list),
        "operator_count": len(operator_list),
        "operators": operator_list,
        "daily_activity": daily_activity,
        "categories": categories,
        "category_labels": CATEGORY_LABELS,
    }


@router.get("/officer-report/export")
async def officer_report_export(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
    time_range: str = Query("all"),
):
    """Same as officer-report but includes open tickets list for PDF export."""
    now = datetime.now(timezone.utc)
    cutoff = _resolve_range(time_range, now)

    total_q = select(func.count()).select_from(Ticket)
    if cutoff:
        total_q = total_q.where(Ticket.issued_at >= cutoff)
    total_all = (await db.execute(total_q)).scalar() or 0

    # Officer emails
    officer_emails_q = select(Ticket.officer_email).where(Ticket.officer_email.isnot(None))
    if cutoff:
        officer_emails_q = officer_emails_q.where(Ticket.issued_at >= cutoff)
    officer_emails_q = officer_emails_q.group_by(Ticket.officer_email)
    officer_emails = [r[0] for r in (await db.execute(officer_emails_q)).all()]

    officers = []
    for email in officer_emails:
        stats = await _officer_stats_for_email(email, db, now, cutoff)
        officer_name_row = (await db.execute(
            select(Ticket.officer_name).where(Ticket.officer_email == email, Ticket.officer_name.isnot(None))
            .order_by(Ticket.issued_at.desc()).limit(1)
        )).scalar()
        stats["officer_email"] = email
        stats["officer_name"] = officer_name_row
        stats["global_share"] = round((stats["all_time"] / total_all) * 100, 1) if total_all else 0
        officers.append(stats)
    officers.sort(key=lambda o: o["all_time"], reverse=True)

    # Lot breakdown
    lot_q = select(Ticket.lot, func.count().label("cnt"))
    if cutoff:
        lot_q = lot_q.where(Ticket.issued_at >= cutoff)
    lot_q = lot_q.group_by(Ticket.lot).order_by(func.count().desc())
    by_lot_total = [{"lot": r[0] or "Unknown", "count": r[1]} for r in (await db.execute(lot_q)).all()]

    # Violation breakdown
    viol_total_q = select(Ticket.violation_type, func.count().label("cnt"))
    if cutoff:
        viol_total_q = viol_total_q.where(Ticket.issued_at >= cutoff)
    viol_total_q = viol_total_q.group_by(Ticket.violation_type).order_by(func.count().desc())
    viol_total_rows = (await db.execute(viol_total_q)).all()
    viol_codes = [r[0] for r in viol_total_rows]
    viol_label_map: dict[str, str] = {}
    if viol_codes:
        vt_r = await db.execute(
            select(ViolationType.code, ViolationType.label).where(ViolationType.code.in_(viol_codes))
        )
        viol_label_map = {r[0]: r[1] for r in vt_r.all()}
    by_violation_total = [
        {"violation_type": r[0], "label": viol_label_map.get(r[0], r[0]), "count": r[1]}
        for r in viol_total_rows
    ]

    # Team revenue
    rev_q = select(func.coalesce(func.sum(Ticket.fine_amount), 0))
    paid_q = select(func.coalesce(func.sum(Ticket.fine_amount), 0)).where(Ticket.status == "paid")
    if cutoff:
        rev_q = rev_q.where(Ticket.issued_at >= cutoff)
        paid_q = paid_q.where(Ticket.issued_at >= cutoff)
    total_revenue = float((await db.execute(rev_q)).scalar() or 0)
    paid_revenue = float((await db.execute(paid_q)).scalar() or 0)

    # Team week/month
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    team_this_week = (await db.execute(select(func.count()).select_from(Ticket).where(Ticket.issued_at >= week_start))).scalar() or 0
    team_this_month = (await db.execute(select(func.count()).select_from(Ticket).where(Ticket.issued_at >= month_start))).scalar() or 0

    total_voided = sum(1 for o in officers for s in o.get("by_status", []) if s["status"] == "voided" for _ in range(s["count"]))
    avg_void_rate = round((total_voided / total_all) * 100, 1) if total_all else 0

    # Open tickets within the time range
    open_q = (
        select(
            Ticket.ticket_number, Ticket.plate, Ticket.lot, Ticket.violation_type,
            Ticket.fine_amount, Ticket.status, Ticket.issued_at, Ticket.officer_name,
            Ticket.owner_name,
        )
        .where(Ticket.status.notin_(["paid", "voided", "resolved_permit"]))
        .order_by(Ticket.issued_at.desc())
    )
    if cutoff:
        open_q = open_q.where(Ticket.issued_at >= cutoff)
    open_rows = (await db.execute(open_q)).all()
    open_tickets = [
        {
            "ticket_number": r[0],
            "plate": r[1],
            "lot": r[2],
            "violation_type": viol_label_map.get(r[3], (r[3] or "").replace("_", " ").title()),
            "fine_amount": f"{float(r[4]):.2f}",
            "status": r[5],
            "issued_at": r[6].isoformat() if r[6] else None,
            "officer_name": r[7],
            "owner_name": r[8],
        }
        for r in open_rows
    ]

    return {
        "total_all": total_all,
        "team_this_week": team_this_week,
        "team_this_month": team_this_month,
        "team_revenue": {"total_fines": round(total_revenue, 2), "paid_fines": round(paid_revenue, 2)},
        "avg_void_rate": avg_void_rate,
        "by_lot_total": by_lot_total,
        "by_violation_total": by_violation_total,
        "officers": officers,
        "open_tickets": open_tickets,
        "time_range": time_range,
    }


@router.get("/hold-check/{lookup_id}")
async def check_hold_status(
    lookup_id: str,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_office()),
):
    """Live check of registration hold status — compares Quarry's record to Jenzabar.

    lookup_id can be: student_id (Okta sub), moravian_id (numeric), or permit_id (UUID).
    """
    moravian_id: str | None = None
    student_id: str | None = None

    # Try as permit_id (UUID)
    try:
        permit_uuid = uuid.UUID(lookup_id)
        permit_row = await db.execute(
            select(Permit.moravian_id, Permit.student_id).where(Permit.id == permit_uuid)
        )
        pr = permit_row.first()
        if pr:
            moravian_id = pr[0] if pr[0] else None
            student_id = pr[1] if pr[1] else None
    except ValueError:
        pass

    # Try as student_id (Okta sub) or moravian_id (numeric)
    if not moravian_id:
        result = await db.execute(
            select(Permit.moravian_id, Permit.student_id).where(
                Permit.student_id == lookup_id,
                Permit.deleted_at.is_(None),
                Permit.moravian_id.isnot(None),
                Permit.moravian_id != "",
            ).limit(1)
        )
        row = result.first()
        if row:
            moravian_id = row[0]
            student_id = row[1]

    if not moravian_id and lookup_id.strip().isdigit():
        moravian_id = lookup_id

    if not moravian_id:
        raise HTTPException(404, "No Moravian ID found for this student")

    # Quarry's record — search by both student_id and moravian_id
    search_ids = [i for i in [student_id, moravian_id, lookup_id] if i]
    quarry_result = await db.execute(
        text("""
            SELECT id, status, created_at, resolved_at, resolved_by, ticket_count
            FROM escalation_log
            WHERE student_id = ANY(:sids)
              AND escalation_type = 'registration_hold'
            ORDER BY created_at DESC LIMIT 1
        """),
        {"sids": search_ids},
    )
    quarry_row = quarry_result.mappings().first()
    quarry_active = quarry_row["resolved_at"] is None if quarry_row else False

    # Live Jenzabar check
    from ..services.sis_hold_service import check_jenzabar_hold
    jenzabar_active = await check_jenzabar_hold(moravian_id)

    synced = jenzabar_active == quarry_active if jenzabar_active is not None else None

    return {
        "moravian_id": moravian_id,
        "quarry_hold_active": quarry_active,
        "jenzabar_hold_active": jenzabar_active,
        "synced": synced,
        "quarry_record": {
            "status": quarry_row["status"],
            "created_at": quarry_row["created_at"].isoformat() if quarry_row and quarry_row["created_at"] else None,
            "resolved_at": quarry_row["resolved_at"].isoformat() if quarry_row and quarry_row["resolved_at"] else None,
            "resolved_by": quarry_row["resolved_by"] if quarry_row else None,
        } if quarry_row else None,
    }


@router.get("/placeholder-holds")
async def placeholder_holds(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Registration holds filed under a placeholder student_id (visitor/legacy metadata)
    instead of a real person, with the Jenzabar ID those holds were applied to."""
    import asyncio
    from ..services.escalation import PLACEHOLDER_SID_SQL
    from ..services.sis_hold_service import check_jenzabar_hold

    rows = (await db.execute(text("""
        SELECT l.id::text AS id, l.student_id, l.student_name, l.student_email, l.plate,
               l.ticket_count, l.created_at, l.resolved_at, l.resolved_by,
               EXISTS (
                   SELECT 1 FROM hold_exemptions e
                   WHERE e.plate = UPPER(REPLACE(REPLACE(COALESCE(l.plate, ''), ' ', ''), '-', ''))
               ) AS plate_on_exemption_list
        FROM escalation_log l
        WHERE l.escalation_type = 'registration_hold' AND l.student_id ~ :pattern
        ORDER BY l.resolved_at DESC NULLS FIRST, l.created_at DESC
    """), {"pattern": PLACEHOLDER_SID_SQL})).mappings().all()

    jenzabar_targets: dict[str, dict] = {}
    for sid in {r["student_id"] for r in rows}:
        target = (await db.execute(text("""
            SELECT moravian_id, name, email FROM permits
            WHERE student_id = :sid AND moravian_id IS NOT NULL AND moravian_id <> ''
            LIMIT 1
        """), {"sid": sid})).mappings().first()
        if not target:
            continue
        try:
            live = await asyncio.wait_for(check_jenzabar_hold(target["moravian_id"]), timeout=15)
        except Exception as e:
            error_reporting.capture_exception(e)
            live = None
        jenzabar_targets[sid] = {
            "moravian_id": target["moravian_id"],
            "name": target["name"],
            "email": target["email"],
            "jenzabar_hold_now": live,
        }

    return [
        {
            "id": r["id"],
            "placeholder": r["student_id"],
            "student_name": r["student_name"],
            "student_email": r["student_email"],
            "plate": r["plate"],
            "ticket_count": r["ticket_count"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "resolved_at": r["resolved_at"].isoformat() if r["resolved_at"] else None,
            "resolved_by": r["resolved_by"],
            "lifted_by_exemption": r["resolved_by"] == "exemption:hold-grace",
            "plate_on_exemption_list": r["plate_on_exemption_list"],
            "jenzabar": jenzabar_targets.get(r["student_id"]),
        }
        for r in rows
    ]


@router.post("", response_model=TicketRead, status_code=201)
async def create_ticket(data: TicketCreate, db: AsyncSession = Depends(get_db)):
    from ..services.ticket_numbering import next_ticket_number
    ticket = Ticket(**data.model_dump())
    ticket.ticket_number = await next_ticket_number(db)
    db.add(ticket)
    await db.flush()
    await db.refresh(ticket)

    try:
        if ticket.plate:
            permit_result = await db.execute(
                select(Permit).where(
                    Permit.plates.contains([ticket.plate.upper()]),
                    Permit.deleted_at.is_(None),
                ).limit(1)
            )
            permit = permit_result.scalar()
            if permit and getattr(permit, "email", None) and "@" in permit.email:
                ticket.notification_email = permit.email
                vtype_label = ticket.violation_type or "Parking Violation"
                if ticket.violation_type:
                    vt_row = await db.execute(
                        select(ViolationType.label).where(ViolationType.code == ticket.violation_type)
                    )
                    vt_lbl = vt_row.scalar()
                    if vt_lbl:
                        vtype_label = vt_lbl
                payment_url = f"{settings.student_facing_url}/pay?ticket={ticket.id}"
                await send_citation_email(
                    recipient_email=permit.email,
                    plate=ticket.plate,
                    lot=ticket.lot or "",
                    violation_label=vtype_label,
                    fine_amount=str(ticket.fine_amount),
                    payment_url=payment_url,
                    officer_name=ticket.officer_name,
                    issued_at=to_local(ticket.issued_at).strftime("%b %d, %Y %I:%M %p %Z") if ticket.issued_at else "",
                    ticket_id=ticket.ticket_number or str(ticket.id),
                )
                await db.flush()
    except Exception as e:
        error_reporting.capture_exception(e)
        import logging
        logging.getLogger("quarry.tickets").warning("Citation email failed (non-fatal): %s", e)

    try:
        if ticket.plate:
            from ..services.escalation import check_and_escalate, resolve_escalation_student_id
            esc_permit_result = await db.execute(
                select(Permit).where(
                    Permit.plates.contains([ticket.plate.upper()]),
                    Permit.deleted_at.is_(None),
                ).order_by(Permit.is_tag_only.asc()).limit(1)
            )
            esc_permit = esc_permit_result.scalar()
            esc_sid = await resolve_escalation_student_id(db, esc_permit)
            if esc_sid:
                await check_and_escalate(
                    db=db,
                    plate=ticket.plate,
                    student_id=esc_sid,
                    student_name=esc_permit.name or ticket.owner_name,
                    student_email=getattr(esc_permit, 'email', None),
                )
    except Exception as e:
        error_reporting.capture_exception(e)
        import logging
        logging.getLogger("quarry.tickets").warning("Escalation check failed (non-fatal): %s", e)

    return ticket


@router.get("/pipeline", response_model=TicketPipeline)
async def ticket_pipeline(
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    result = await db.execute(
        select(Ticket.status, func.count()).group_by(Ticket.status)
    )
    counts = dict(result.all())
    total = sum(counts.values())
    return TicketPipeline(
        issued=counts.get("issued", 0),
        overdue=counts.get("overdue", 0),
        pending_payment=counts.get("pending_payment", 0),
        paid=counts.get("paid", 0),
        appealed=counts.get("appealed", 0),
        escalated=counts.get("escalated", 0),
        past_due=counts.get("past_due", 0),
        voided=counts.get("voided", 0),
        resolved_permit=counts.get("resolved_permit", 0),
        total=total,
    )


TERMINAL_STATUSES = {"paid", "voided", "resolved_permit"}


@router.get("/dashboard", response_model=DashboardData)
async def dashboard(
    period: str = Query("today", pattern="^(today|week|month)$"),
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    today = today_local()
    et = campus_tz()
    if period == "today":
        since = datetime.combine(today, datetime.min.time(), tzinfo=et)
        avg_days = 7
    elif period == "week":
        since = datetime.combine(today - timedelta(days=6), datetime.min.time(), tzinfo=et)
        avg_days = 28
    else:
        since = datetime.combine(today.replace(day=1), datetime.min.time(), tzinfo=et)
        avg_days = 90

    # Needs action (all time — these are currently open)
    action_q = await db.execute(
        select(Ticket.status, func.count())
        .where(Ticket.status.in_(["appealed", "escalated", "overdue", "past_due"]))
        .group_by(Ticket.status)
    )
    action_counts = dict(action_q.all())
    needs_action = NeedsAction(
        total=sum(action_counts.values()),
        appealed=action_counts.get("appealed", 0),
        escalated=action_counts.get("escalated", 0),
        overdue=action_counts.get("overdue", 0),
        past_due=action_counts.get("past_due", 0),
    )

    # Issued count within period (all tickets created, regardless of current status)
    issued_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(Ticket.issued_at >= since)
    )
    issued_total = issued_q.scalar() or 0

    avg_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(
            Ticket.issued_at >= datetime.combine(today - timedelta(days=avg_days), datetime.min.time(), tzinfo=et),
        )
    )
    avg_raw = avg_q.scalar() or 0
    daily_avg = round(avg_raw / avg_days, 1) if avg_days > 0 else 0

    issued_count = IssuedCount(total=issued_total, daily_avg=daily_avg)

    # Revenue within period
    collected_q = await db.execute(
        select(func.coalesce(func.sum(Payment.amount), 0))
        .where(Payment.paid_at >= since)
    )
    collected = collected_q.scalar()

    pending_q = await db.execute(
        select(func.count(), func.coalesce(func.sum(Ticket.fine_amount), 0))
        .select_from(Ticket)
        .where(Ticket.status == "pending_payment", Ticket.issued_at >= since)
    )
    pending_row = pending_q.one()
    revenue = Revenue(
        collected=collected,
        pending_count=pending_row[0],
        pending_amount=pending_row[1],
    )

    # Resolution rate within period
    period_total_q = await db.execute(
        select(func.count()).select_from(Ticket).where(Ticket.issued_at >= since)
    )
    period_total = period_total_q.scalar() or 0

    resolved_q = await db.execute(
        select(func.count()).select_from(Ticket)
        .where(Ticket.issued_at >= since, Ticket.status.in_(list(TERMINAL_STATUSES)))
    )
    resolved = resolved_q.scalar() or 0

    rate = round(resolved / period_total * 100, 1) if period_total > 0 else 0
    resolution_rate = ResolutionRate(rate=rate, resolved=resolved, total=period_total)

    # Action items (appealed/escalated, oldest first)
    items_q = await db.execute(
        select(Ticket)
        .where(Ticket.status.in_(["appealed", "escalated", "past_due"]))
        .options(defer(Ticket.photo_data))
        .order_by(Ticket.issued_at.asc())
        .limit(20)
    )
    action_items = [
        ActionItem.model_validate(t) for t in items_q.scalars().all()
    ]

    # Activity: tickets created or updated within the period
    activity_q = await db.execute(
        select(Ticket)
        .where(or_(Ticket.issued_at >= since, Ticket.updated_at >= since))
        .options(defer(Ticket.photo_data))
        .order_by(Ticket.updated_at.desc())
        .limit(30)
    )
    activity = [
        ActivityEvent.model_validate(t) for t in activity_q.scalars().all()
    ]

    # 7-day trend
    trend_start = today - timedelta(days=6)
    trend_q = await db.execute(
        select(
            cast(Ticket.issued_at, Date).label("day"),
            func.count().label("cnt"),
        )
        .where(Ticket.issued_at >= datetime.combine(trend_start, datetime.min.time(), tzinfo=et))
        .group_by("day")
        .order_by("day")
    )
    counts_by_day = {row[0]: row[1] for row in trend_q.all()}
    trend = []
    for i in range(7):
        d = trend_start + timedelta(days=i)
        trend.append(TrendDay(
            date=d.isoformat(),
            day=d.strftime("%a"),
            count=counts_by_day.get(d, 0),
        ))

    # Pending vehicle requests
    from ..models.vehicle_request import VehicleRequest
    vr_count = (await db.execute(
        select(func.count()).select_from(VehicleRequest).where(VehicleRequest.status == "pending")
    )).scalar() or 0

    # Outstanding balance — unpaid tickets with breakdown
    from ..schemas.ticket import OutstandingBalance, EnforcementSnapshot
    unpaid_statuses = ["issued", "overdue", "past_due", "appealed", "escalated"]
    outstanding_q = await db.execute(
        text("""
            SELECT
                COUNT(*) AS cnt,
                COALESCE(SUM(fine_amount), 0) AS total,
                COUNT(*) FILTER (WHERE notification_email IS NOT NULL AND notification_email != '') AS contactable_cnt,
                COALESCE(SUM(fine_amount) FILTER (WHERE notification_email IS NOT NULL AND notification_email != ''), 0) AS contactable_amt
            FROM tickets
            WHERE status IN :statuses
        """).bindparams(bindparam("statuses", expanding=True)),
        {"statuses": unpaid_statuses},
    )
    orow = outstanding_q.mappings().first()
    outstanding = OutstandingBalance(
        total_unpaid=orow["total"],
        ticket_count=orow["cnt"],
        contactable_count=orow["contactable_cnt"],
        contactable_amount=orow["contactable_amt"],
        uncollectable_count=orow["cnt"] - orow["contactable_cnt"],
        uncollectable_amount=orow["total"] - orow["contactable_amt"],
    )

    # Enforcement snapshot
    active_permits_q = (await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.status == "active", Permit.deleted_at.is_(None), Permit.is_tag_only.is_(False)
        )
    )).scalar() or 0

    active_tags_q = (await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.status == "active", Permit.deleted_at.is_(None), Permit.is_tag_only.is_(True)
        )
    )).scalar() or 0

    conduct_q = (await db.execute(text(
        "SELECT COUNT(*) FROM escalation_log WHERE escalation_type = 'conduct_referral' AND resolved_at IS NULL"
    ))).scalar() or 0

    holds_q = (await db.execute(text(
        "SELECT COUNT(*) FROM escalation_log WHERE escalation_type = 'registration_hold' AND resolved_at IS NULL"
    ))).scalar() or 0

    enforcement = EnforcementSnapshot(
        active_permits=active_permits_q,
        active_tags=active_tags_q,
        conduct_cases=conduct_q,
        registration_holds=holds_q,
    )

    return DashboardData(
        needs_action=needs_action,
        issued_count=issued_count,
        revenue=revenue,
        resolution_rate=resolution_rate,
        outstanding=outstanding,
        enforcement=enforcement,
        action_items=action_items,
        activity=activity,
        trend=trend,
        pending_vehicle_requests=vr_count,
    )


@router.get("/{ticket_id}", response_model=TicketRead)
async def get_ticket(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    return ticket


@router.put("/{ticket_id}", response_model=TicketRead)
async def update_ticket(
    ticket_id: uuid.UUID,
    data: TicketUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_office()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    updated_fields = data.model_dump(exclude_unset=True)

    # If plate changed, re-link to the correct permit/tag
    old_owner_email: str | None = None
    old_owner_name: str | None = None
    plate_was_corrected = False
    if "plate" in updated_fields and updated_fields["plate"]:
        old_plate = ticket.plate
        new_plate = updated_fields["plate"].upper().replace(" ", "").replace("-", "")
        updated_fields["plate"] = new_plate
        if new_plate != old_plate.upper().replace(" ", "").replace("-", ""):
            plate_was_corrected = True
            old_owner_email = ticket.notification_email
            old_owner_name = ticket.owner_name
            # Store original plate if this is the first correction
            if not ticket.ocr_original_plate:
                ticket.ocr_original_plate = old_plate
            # Find permit/tag for the new plate
            permit_result = await db.execute(
                select(Permit).where(
                    Permit.deleted_at.is_(None),
                    Permit.status != "cancelled",
                    Permit.plates.any(new_plate),
                ).order_by(Permit.is_tag_only.asc())  # real permits first
            )
            new_permit = permit_result.scalars().first()
            if new_permit:
                updated_fields["permit_id"] = new_permit.id
                if new_permit.name:
                    updated_fields["owner_name"] = new_permit.name
                if new_permit.email and "@" in new_permit.email:
                    updated_fields["notification_email"] = new_permit.email
            else:
                updated_fields["permit_id"] = None

    if "plate_state" in updated_fields:
        updated_fields["plate_state"] = (updated_fields["plate_state"] or "").strip().upper() or None

    if "owner_address" in updated_fields:
        addr = (updated_fields["owner_address"] or "").strip()
        if addr:
            from ..services.address_format import mailing_address_error
            problem = mailing_address_error(addr)
            if problem:
                raise HTTPException(400, problem)
        updated_fields["owner_address"] = addr or None

    if updated_fields.get("status") == "voided" and ticket.status != "voided" and not _admin.is_admin:
        raise HTTPException(403, "Only admins can void tickets")
    for field, value in updated_fields.items():
        if field == "status" and value not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status: {value}")
        setattr(ticket, field, value)

    from ..services.citation_policy.service import DISMISSED_STATUSES, void_fees_for_dismissed
    if updated_fields.get("status") in DISMISSED_STATUSES:
        await void_fees_for_dismissed(db, ticket, _admin.email, f"Citation marked {ticket.status}")
    elif plate_was_corrected:
        await void_fees_for_dismissed(db, ticket, _admin.email, "Plate corrected; fees accrued under the wrong plate")

    await db.flush()
    await db.refresh(ticket)

    # If owner info changed, propagate to the vehicle tag and other tickets on same plate
    propagate_fields = {}
    if "owner_name" in updated_fields and ticket.owner_name:
        propagate_fields["owner_name"] = ticket.owner_name
    if "notification_email" in updated_fields and ticket.notification_email:
        propagate_fields["notification_email"] = ticket.notification_email
    if "owner_address" in updated_fields and ticket.owner_address:
        propagate_fields["owner_address"] = ticket.owner_address

    if propagate_fields:
        plate_norm = ticket.plate.upper().replace(" ", "").replace("-", "")
        # Update the associated tag
        tag_result = await db.execute(
            select(Permit).where(
                Permit.is_tag_only.is_(True),
                Permit.deleted_at.is_(None),
                Permit.plates.any(plate_norm),
            )
        )
        tag = tag_result.scalars().first()
        if tag:
            if "owner_name" in propagate_fields:
                tag.name = propagate_fields["owner_name"]
            if "notification_email" in propagate_fields:
                tag.email = propagate_fields["notification_email"]
            await db.flush()
        # Update other tickets with the same plate
        await db.execute(
            Ticket.__table__.update()
            .where(Ticket.plate == ticket.plate, Ticket.id != ticket.id)
            .values(**propagate_fields)
        )
        await db.flush()

    # Send dismissal email to the originally ticketed student if plate was corrected
    if plate_was_corrected and old_owner_email:
        try:
            await send_plate_correction_dismissal_email(
                recipient_email=old_owner_email,
                recipient_name=old_owner_name or "",
                ticket_number=ticket.ticket_number or str(ticket.id)[:8].upper(),
                old_plate=ticket.ocr_original_plate or old_plate,
                fine_amount=f"${float(ticket.fine_amount):.2f}",
                violation_label=ticket.violation_type.replace("_", " ").title(),
                lot=ticket.lot or "",
                issued_at=ticket.issued_at.isoformat() if ticket.issued_at else "",
            )
        except Exception as e:
            error_reporting.capture_exception(e)

    # Re-check escalation after plate correction or owner propagation
    if plate_was_corrected or propagate_fields:
        try:
            from ..services.escalation import check_and_escalate, resolve_escalation_student_id
            # Find the permit for the (possibly new) plate to get student info
            esc_permit = (await db.execute(
                select(Permit).where(
                    Permit.deleted_at.is_(None),
                    Permit.plates.any(ticket.plate.upper().replace(" ", "").replace("-", "")),
                ).order_by(Permit.is_tag_only.asc())
            )).scalars().first()
            esc_sid = await resolve_escalation_student_id(db, esc_permit)
            if esc_sid:
                await check_and_escalate(
                    db=db,
                    plate=ticket.plate,
                    student_id=esc_sid,
                    student_name=esc_permit.name or ticket.owner_name,
                    student_email=getattr(esc_permit, 'email', None),
                )
        except Exception as e:
            error_reporting.capture_exception(e)

    return ticket


@router.post("/{ticket_id}/void", response_model=TicketRead)
async def void_ticket(
    ticket_id: uuid.UUID,
    body: VoidRequest | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(require_admin()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status == "paid":
        raise HTTPException(400, "Cannot void a paid ticket")
    ticket.status = "voided"
    if body and body.reason:
        ticket.void_reason = body.reason.strip()[:1024]
    from ..services.citation_policy.service import void_fees_for_dismissed
    await void_fees_for_dismissed(db, ticket, user.email, f"Citation voided: {ticket.void_reason or 'no reason given'}")
    await db.flush()

    if ticket.plate:
        try:
            from ..services.escalation import check_and_resolve_on_payment
            await check_and_resolve_on_payment(db, ticket.plate)
        except Exception as e:
            error_reporting.capture_exception(e)

    await db.refresh(ticket)
    return ticket


@router.post("/bulk-void")
async def bulk_void_tickets(
    data: dict,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Void multiple tickets at once (admins only)."""
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(400, "No ticket IDs provided")

    voided = 0
    skipped = 0
    plates_seen: set[str] = set()
    for tid in ids:
        try:
            ticket = await db.get(Ticket, uuid.UUID(tid))
        except (ValueError, AttributeError):
            skipped += 1
            continue
        if not ticket:
            skipped += 1
            continue
        if ticket.status in ("paid", "voided"):
            skipped += 1
            continue
        ticket.status = "voided"
        from ..services.citation_policy.service import void_fees_for_dismissed
        await void_fees_for_dismissed(db, ticket, _admin.email, "Citation voided (bulk)")
        voided += 1
        if ticket.plate:
            plates_seen.add(ticket.plate)

    await db.flush()

    for plate in plates_seen:
        try:
            from ..services.escalation import check_and_resolve_on_payment
            await check_and_resolve_on_payment(db, plate)
        except Exception as e:
            error_reporting.capture_exception(e)

    return {"voided": voided, "skipped": skipped}


class DenyRequest(BaseModel):
    reason: str = ""


@router.post("/{ticket_id}/deny", response_model=TicketRead)
async def deny_ticket(
    ticket_id: uuid.UUID,
    body: DenyRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_role("admin", "operator")),
):
    """Deny/uphold a ticket — confirms the citation stands.

    For appealed tickets: denies the appeal and moves to pending_payment.
    For non-appealed tickets: marks as reviewed/upheld and moves to pending_payment.
    """
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided"):
        raise HTTPException(400, f"Cannot deny a {ticket.status} ticket")

    if ticket.appeal_decision == "pending":
        from ..services.citation_policy.service import record_appeal_decision
        await record_appeal_decision(db, ticket, "denied", admin.email, body.reason)

    ticket.status = "pending_payment"
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/bulk-deny")
async def bulk_deny_tickets(
    data: dict,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_role("admin", "operator")),
):
    """Deny/uphold multiple tickets — confirms citations stand."""
    ids = data.get("ids", [])
    reason = data.get("reason", "")
    if not ids:
        raise HTTPException(400, "No ticket IDs provided")

    denied = 0
    skipped = 0
    for tid in ids:
        try:
            ticket = await db.get(Ticket, uuid.UUID(tid))
        except (ValueError, AttributeError):
            skipped += 1
            continue
        if not ticket:
            skipped += 1
            continue
        if ticket.status in ("paid", "voided"):
            skipped += 1
            continue

        if ticket.appeal_decision == "pending":
            from ..services.citation_policy.service import record_appeal_decision
            await record_appeal_decision(db, ticket, "denied", admin.email, reason)

        ticket.status = "pending_payment"
        denied += 1

    await db.flush()
    return {"denied": denied, "skipped": skipped}


@router.post("/{ticket_id}/appeal", response_model=TicketRead)
async def appeal_ticket(
    ticket_id: uuid.UUID, appeal: AppealRequest, db: AsyncSession = Depends(get_db)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided"):
        raise HTTPException(400, f"Cannot appeal a {ticket.status} ticket")
    if ticket.appeal_decision == "pending":
        raise HTTPException(400, "An appeal has already been submitted for this ticket.")

    from ..services.citation_policy.service import appeal_deadline_for, on_appeal_submitted
    deadline, appeal_window_days = await appeal_deadline_for(db, ticket)
    if deadline and datetime.now(timezone.utc) > deadline:
        raise HTTPException(
            400,
            f"Appeal window has closed. Appeals must be submitted within "
            f"{appeal_window_days} day(s) of the citation notice.",
        )

    ticket.status = "appealed"
    ticket.appeal_note = appeal.note
    ticket.appeal_decision = "pending"
    await on_appeal_submitted(db, ticket, ticket.dispute_email or "staff")
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/appeal/decide", response_model=TicketRead)
async def decide_appeal(
    ticket_id: uuid.UUID,
    decision: AppealDecision,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_role("admin", "operator")),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.appeal_decision != "pending":
        raise HTTPException(400, "No pending appeal on this ticket")

    if decision.decision not in ("approved", "denied"):
        raise HTTPException(400, "Decision must be 'approved' or 'denied'")

    from ..services.citation_policy.service import record_appeal_decision
    await record_appeal_decision(
        db, ticket, decision.decision, decision.decided_by or _admin.email, decision.reason,
    )
    await db.flush()

    if decision.decision == "approved" and ticket.plate:
        try:
            from ..services.escalation import check_and_resolve_on_payment
            await check_and_resolve_on_payment(db, ticket.plate)
        except Exception as e:
            error_reporting.capture_exception(e)

    await db.refresh(ticket)
    return ticket


@router.get("/mail-notices/pending")
async def pending_mail_notices(
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    """Return overdue/escalated tickets for guests/visitors that haven't been mailed.

    These are tickets where:
    - The plate is NOT associated with any active permit (guest/visitor)
    - Status is overdue or escalated
    - No mail notice has been sent yet (mailed_at is NULL)
    """
    from ..models.permit import Permit

    unmailed_q = await db.execute(
        select(Ticket).where(
            Ticket.status.in_(["overdue", "escalated", "past_due"]),
            Ticket.mailed_at.is_(None),
        ).order_by(Ticket.issued_at.asc())
    )
    unmailed = unmailed_q.scalars().all()

    guest_tickets = []
    for ticket in unmailed:
        permit_result = await db.execute(
            select(Permit.id).where(
                Permit.plates.contains([ticket.plate.upper()]),
                Permit.deleted_at.is_(None),
            ).limit(1)
        )
        has_permit = permit_result.scalar() is not None
        if not has_permit:
            owner_name, owner_address = ticket.owner_name, ticket.owner_address
            if not owner_address:
                sibling = (await db.execute(
                    select(Ticket.owner_name, Ticket.owner_address).where(
                        Ticket.plate == ticket.plate,
                        Ticket.id != ticket.id,
                        Ticket.owner_address.is_not(None),
                        Ticket.owner_address != "",
                    ).order_by(Ticket.issued_at.desc()).limit(1)
                )).first()
                if sibling:
                    owner_address = sibling.owner_address
                    owner_name = owner_name or sibling.owner_name
            guest_tickets.append({
                "id": str(ticket.id),
                "ticket_number": ticket.ticket_number,
                "plate": ticket.plate,
                "lot": ticket.lot,
                "zone": ticket.zone,
                "violation_type": ticket.violation_type,
                "fine_amount": str(ticket.fine_amount),
                "status": ticket.status,
                "issued_at": ticket.issued_at.isoformat() if ticket.issued_at else None,
                "owner_name": owner_name,
                "owner_address": owner_address,
                "vehicle_description": ticket.vehicle_description,
                "officer_name": ticket.officer_name,
                "officer_id": ticket.officer_id,
                "plate_state": ticket.plate_state,
                "ticket_category": ticket.ticket_category,
                "location_text": ticket.location_text,
                "location_lat": ticket.location_lat,
                "location_lng": ticket.location_lng,
                "additional_violations": ticket.additional_violations,
                "photo_url": ticket.photo_url,
                "payment_url": f"{settings.student_facing_url}/pay/{ticket.id}",
            })

    return {"tickets": guest_tickets, "total": len(guest_tickets)}


@router.post("/mail-notices/mark-mailed")
async def mark_mailed(
    data: dict,
    db: AsyncSession = Depends(get_db),
    _office: OktaUser = Depends(require_office()),
):
    """Mark tickets as having had a mail notice sent.

    Body: {"ticket_ids": [...], "mailing_address": "optional address note"}
    """
    ticket_ids = data.get("ticket_ids", [])
    address = data.get("mailing_address", "")
    if not ticket_ids:
        raise HTTPException(400, "No ticket_ids provided")

    now = datetime.now(timezone.utc)
    marked = 0
    for tid in ticket_ids:
        try:
            ticket = await db.get(Ticket, uuid.UUID(tid))
            if ticket and ticket.mailed_at is None:
                ticket.mailed_at = now
                on_file = ", ".join(p for p in (ticket.owner_name, ticket.owner_address) if p)
                ticket.mailed_address = address or on_file or None
                marked += 1
        except (ValueError, TypeError):
            continue

    await db.flush()
    return {"marked": marked, "total_requested": len(ticket_ids)}


@router.post("/{ticket_id}/photo")
async def upload_photo(
    ticket_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/heic"}
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"Invalid file type. Allowed: {', '.join(allowed_types)}")

    contents = await file.read()
    if len(contents) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large. Maximum size is 10MB.")

    ticket.photo_data = contents
    ticket.photo_mime = file.content_type
    ticket.photo_url = f"/api/tickets/{ticket_id}/photo"
    await db.flush()
    return {"photo_url": ticket.photo_url}


@public_router.get("/{ticket_id}/photo")
async def serve_photo(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as _select
    result = await db.execute(
        _select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    if ticket.photo_data:
        from fastapi.responses import Response
        return Response(
            content=ticket.photo_data,
            media_type=ticket.photo_mime or "image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    # Legacy fallback: serve from disk if photo_url points to old /uploads/ path
    if ticket.photo_url and "/uploads/photos/" in ticket.photo_url:
        import os
        filename = ticket.photo_url.split("/uploads/photos/")[-1]
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "photos")
        filepath = os.path.join(upload_dir, filename)
        if os.path.isfile(filepath):
            from fastapi.responses import FileResponse
            return FileResponse(filepath, media_type="image/jpeg")

    raise HTTPException(404, "No photo found")


@public_router.get("/{ticket_id}/photos/{index}")
async def serve_additional_photo(
    ticket_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select as _select
    result = await db.execute(
        _select(Ticket).where(Ticket.id == ticket_id)
    )
    ticket = result.scalar()
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    if not ticket.additional_photos or index < 0 or index >= len(ticket.additional_photos):
        raise HTTPException(404, "Photo not found")

    photo_entry = ticket.additional_photos[index]
    from fastapi.responses import Response
    import base64
    return Response(
        content=base64.b64decode(photo_entry["data"]),
        media_type=photo_entry.get("mime", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )
