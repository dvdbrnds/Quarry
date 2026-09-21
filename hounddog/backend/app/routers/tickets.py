import uuid
import sentry_sdk
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from ..utils.safe_router import SafeRouter
from sqlalchemy import select, func, or_, cast, Date, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..auth.okta import get_current_user, OktaUser, require_admin, require_office
from ..config import settings
from ..database import get_db
from ..models.enforcement_settings import EnforcementSettings
from ..models.payment import Payment
from ..models.permit import Permit
from ..models.legacy_record import LegacyRecord
from ..models.ticket import Ticket
from ..models.violation_type import ViolationType
from ..services.timeutils import campus_tz, today_local, to_local
from ..services.email import send_citation_email
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

VALID_STATUSES = {"issued", "warning", "pending_payment", "paid", "appealed", "escalated", "voided", "resolved_permit", "overdue"}

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

    enriched = []
    for t in items:
        d = TicketRead.model_validate(t).model_dump()
        norm = t.plate.upper().replace(" ", "").replace("-", "") if t.plate else ""
        d["has_legacy"] = norm in legacy_plates
        enriched.append(d)

    return {"items": enriched, "total": total, "page": page, "page_size": page_size}


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
            if permit and getattr(permit, "email", None):
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
        sentry_sdk.capture_exception(e)
        import logging
        logging.getLogger("quarry.tickets").warning("Citation email failed (non-fatal): %s", e)

    try:
        if ticket.plate:
            from ..services.escalation import check_and_escalate
            esc_permit_result = await db.execute(
                select(Permit).where(
                    Permit.plates.contains([ticket.plate.upper()]),
                    Permit.deleted_at.is_(None),
                ).limit(1)
            )
            esc_permit = esc_permit_result.scalar()
            if esc_permit and getattr(esc_permit, 'student_id', None):
                await check_and_escalate(
                    db=db,
                    plate=ticket.plate,
                    student_id=esc_permit.student_id,
                    student_name=esc_permit.name or ticket.owner_name,
                    student_email=getattr(esc_permit, 'email', None),
                )
    except Exception as e:
        sentry_sdk.capture_exception(e)
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
        .where(Ticket.status.in_(["appealed", "escalated"]))
        .group_by(Ticket.status)
    )
    action_counts = dict(action_q.all())
    needs_action = NeedsAction(
        total=sum(action_counts.values()),
        appealed=action_counts.get("appealed", 0),
        escalated=action_counts.get("escalated", 0),
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
        .where(Ticket.status.in_(["appealed", "escalated"]))
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

    return DashboardData(
        needs_action=needs_action,
        issued_count=issued_count,
        revenue=revenue,
        resolution_rate=resolution_rate,
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
    _admin: OktaUser = Depends(require_admin()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")

    updated_fields = data.model_dump(exclude_unset=True)
    for field, value in updated_fields.items():
        if field == "status" and value not in VALID_STATUSES:
            raise HTTPException(400, f"Invalid status: {value}")
        setattr(ticket, field, value)

    await db.flush()
    await db.refresh(ticket)

    # If owner info changed, propagate to the vehicle tag and other tickets on same plate
    if "owner_name" in updated_fields and ticket.owner_name:
        plate_norm = ticket.plate.upper().replace(" ", "").replace("-", "")
        # Update the associated tag
        tag_result = await db.execute(
            select(Permit).where(
                Permit.is_tag_only.is_(True),
                Permit.deleted_at.is_(None),
                Permit.plates.any(plate_norm),
            )
        )
        tag = tag_result.scalar_one_or_none()
        if tag:
            tag.name = ticket.owner_name
            if ticket.notification_email and not tag.email:
                tag.email = ticket.notification_email
            await db.flush()
        # Update other tickets with the same plate
        await db.execute(
            Ticket.__table__.update()
            .where(Ticket.plate == ticket.plate, Ticket.id != ticket.id)
            .values(owner_name=ticket.owner_name)
        )
        await db.flush()

    return ticket


@router.post("/{ticket_id}/void", response_model=TicketRead)
async def void_ticket(
    ticket_id: uuid.UUID,
    body: VoidRequest | None = None,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status == "paid":
        raise HTTPException(400, "Cannot void a paid ticket")
    ticket.status = "voided"
    if body and body.reason:
        ticket.void_reason = body.reason.strip()[:1024]
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/bulk-void")
async def bulk_void_tickets(
    data: dict,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Void multiple tickets at once."""
    ids = data.get("ids", [])
    if not ids:
        raise HTTPException(400, "No ticket IDs provided")

    voided = 0
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
        ticket.status = "voided"
        voided += 1

    await db.flush()
    return {"voided": voided, "skipped": skipped}


@router.post("/{ticket_id}/appeal", response_model=TicketRead)
async def appeal_ticket(
    ticket_id: uuid.UUID, appeal: AppealRequest, db: AsyncSession = Depends(get_db)
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status in ("paid", "voided"):
        raise HTTPException(400, f"Cannot appeal a {ticket.status} ticket")

    # Enforce appeal window from EnforcementSettings
    es_result = await db.execute(
        select(EnforcementSettings).where(EnforcementSettings.id == 1)
    )
    es = es_result.scalar()
    appeal_window_days = es.appeal_window_days if es else 5

    if ticket.issued_at:
        from datetime import timedelta
        issued = ticket.issued_at
        if issued.tzinfo is None:
            issued = issued.replace(tzinfo=timezone.utc)
        deadline = issued + timedelta(days=appeal_window_days)
        if datetime.now(timezone.utc) > deadline:
            raise HTTPException(
                400,
                f"Appeal window has closed. Appeals must be submitted within "
                f"{appeal_window_days} day(s) of issuance.",
            )

    ticket.status = "appealed"
    ticket.appeal_note = appeal.note
    ticket.appeal_decision = "pending"
    await db.flush()
    await db.refresh(ticket)
    return ticket


@router.post("/{ticket_id}/appeal/decide", response_model=TicketRead)
async def decide_appeal(
    ticket_id: uuid.UUID,
    decision: AppealDecision,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.appeal_decision != "pending":
        raise HTTPException(400, "No pending appeal on this ticket")

    if decision.decision not in ("approved", "denied"):
        raise HTTPException(400, "Decision must be 'approved' or 'denied'")

    ticket.appeal_decision = decision.decision
    ticket.appeal_decided_by = decision.decided_by
    if decision.reason:
        ticket.appeal_decision_reason = decision.reason.strip()[:1024]

    if decision.decision == "approved":
        ticket.status = "voided"
    else:
        ticket.status = "pending_payment"

    await db.flush()
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
            Ticket.status.in_(["overdue", "escalated"]),
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
                "owner_name": ticket.owner_name,
                "vehicle_description": ticket.vehicle_description,
                "officer_name": ticket.officer_name,
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
                ticket.mailed_address = address or None
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
