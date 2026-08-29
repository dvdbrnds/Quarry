import logging
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, text, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, require_admin, require_office
from ..database import get_db, async_session
from ..models.audit_log import AuditLog
from ..models.permit_type import PermitType
from ..schemas.audit import AuditLogList, AuditLogRead

logger = logging.getLogger("quarry.audit")

diagnostic_router = APIRouter()
router = APIRouter(dependencies=[Depends(require_office())])


async def _enrich_lottery_audit_items(
    db: AsyncSession, items: list[AuditLog]
) -> list[AuditLogRead]:
    """Resolve tier preference UUIDs to labels for lottery application audits."""
    pref_ids: set = set()
    for entry in items:
        body = entry.request_body if isinstance(entry.request_body, dict) else None
        if not body:
            continue
        for raw in body.get("tier_preferences") or []:
            try:
                import uuid as _uuid
                pref_ids.add(_uuid.UUID(str(raw)))
            except (ValueError, TypeError):
                pass

    labels_by_id: dict[str, str] = {}
    if pref_ids:
        rows = (
            await db.execute(select(PermitType).where(PermitType.id.in_(pref_ids)))
        ).scalars().all()
        labels_by_id = {str(pt.id): pt.label for pt in rows}

    out: list[AuditLogRead] = []
    for entry in items:
        read = AuditLogRead.model_validate(entry)
        body = dict(read.request_body) if isinstance(read.request_body, dict) else None
        if body and body.get("tier_preferences"):
            labels = [
                labels_by_id.get(str(p), str(p)[:8])
                for p in body["tier_preferences"]
            ]
            body = {**body, "tier_preference_labels": labels}
            read.request_body = body
            # Upgrade generic middleware summaries for older rows
            if labels and not read.summary.startswith("Submitted lottery application"):
                campus = (body.get("campus") or "").capitalize()
                ranked = " → ".join(f"#{i} {lab}" for i, lab in enumerate(labels, 1))
                where = f"{campus} campus — " if campus else ""
                read.summary = f"Submitted lottery application ({where}{ranked})"
        out.append(read)
    return out


@diagnostic_router.get("/diagnostic")
async def audit_diagnostic(
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(require_admin()),
):
    """Diagnostic endpoint: tests every piece of the audit chain. No auth required."""
    results: dict = {"steps": {}}

    # 1. Does the table exist?
    try:
        row = await db.execute(text("SELECT count(*) FROM audit_log"))
        count = row.scalar()
        results["steps"]["table_exists"] = True
        results["steps"]["total_rows"] = count
    except Exception as e:
        results["steps"]["table_exists"] = False
        results["steps"]["table_error"] = f"{type(e).__name__}: {e}"
        return results

    # 2. Can we write to it via route session?
    try:
        test_entry = AuditLog(
            user_email="diagnostic-test",
            user_sub="",
            action="DIAGNOSTIC",
            resource_type="audit",
            endpoint="/api/audit/diagnostic",
            summary="Audit diagnostic test (route session)",
            response_status=200,
        )
        db.add(test_entry)
        await db.flush()
        results["steps"]["route_session_write_ok"] = True
        results["steps"]["test_entry_id"] = str(test_entry.id)
    except Exception as e:
        results["steps"]["route_session_write_ok"] = False
        results["steps"]["route_session_write_error"] = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        return results

    # 3. Can we read it back?
    try:
        row = await db.execute(
            select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(5)
        )
        entries = row.scalars().all()
        results["steps"]["read_ok"] = True
        results["steps"]["recent_entries"] = [
            {
                "id": str(e.id),
                "timestamp": str(e.timestamp),
                "user_email": e.user_email,
                "action": e.action,
                "summary": e.summary,
                "response_status": e.response_status,
            }
            for e in entries
        ]
    except Exception as e:
        results["steps"]["read_ok"] = False
        results["steps"]["read_error"] = f"{type(e).__name__}: {e}"

    # 4. Can the middleware's standalone async_session write?
    try:
        async with async_session() as mw_session:
            async with mw_session.begin():
                mw_entry = AuditLog(
                    user_email="diagnostic-test",
                    user_sub="",
                    action="DIAGNOSTIC",
                    resource_type="audit",
                    endpoint="/api/audit/diagnostic",
                    summary="Audit diagnostic test (middleware session)",
                    response_status=200,
                )
                mw_session.add(mw_entry)
        results["steps"]["middleware_session_write_ok"] = True
    except Exception as e:
        results["steps"]["middleware_session_write_ok"] = False
        results["steps"]["middleware_session_error"] = traceback.format_exc()

    # 5. Re-count after writes
    try:
        row = await db.execute(text("SELECT count(*) FROM audit_log"))
        results["steps"]["total_rows_after"] = row.scalar()
    except Exception:
        pass

    return results


@router.get("", response_model=AuditLogList)
async def list_audit_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    user_email: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog)

    if user_email:
        query = query.where(AuditLog.user_email.ilike(f"%{user_email}%"))
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.where(AuditLog.resource_id == resource_id)
    if action:
        query = query.where(AuditLog.action == action)
    if from_date:
        query = query.where(AuditLog.timestamp >= from_date)
    if to_date:
        query = query.where(AuditLog.timestamp <= to_date)
    if search:
        like = f"%{search}%"
        query = query.where(
            or_(
                AuditLog.summary.ilike(like),
                AuditLog.user_email.ilike(like),
                AuditLog.endpoint.ilike(like),
                AuditLog.resource_type.ilike(like),
            )
        )

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(desc(AuditLog.timestamp))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    enriched = await _enrich_lottery_audit_items(db, list(items))
    return AuditLogList(items=enriched, total=total, page=page, page_size=page_size)


@router.get("/resource/{resource_type}/{resource_id}", response_model=list[AuditLogRead])
async def get_resource_audit(
    resource_type: str,
    resource_id: str,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.resource_type == resource_type, AuditLog.resource_id == resource_id)
        .order_by(desc(AuditLog.timestamp))
        .limit(100)
    )
    return await _enrich_lottery_audit_items(db, list(result.scalars().all()))


@router.get("/student-summary/{email}")
async def student_activity_summary(
    email: str,
    db: AsyncSession = Depends(get_db),
):
    """Build a summarized timeline of meaningful events for a student."""
    from ..models.permit import Permit
    from ..models.ticket import Ticket
    from ..models.lottery_v2 import LotteryV2Application
    from ..models.permit_type import PermitType

    email_lower = email.strip().lower()
    events: list[dict] = []

    # 1. Meaningful audit log entries
    meaningful_patterns = [
        "/api/lottery-v2/applications",
        "/api/payments/",
        "/api/student/permits/",
        "/api/auth/",
    ]
    audit_rows = (await db.execute(
        select(AuditLog)
        .where(
            func.lower(AuditLog.user_email) == email_lower,
            AuditLog.action != "GET",
        )
        .order_by(AuditLog.timestamp.asc())
    )).scalars().all()

    skip_endpoints = {
        "/api/auth/me", "/api/auth/config/public", "/api/auth/config",
    }

    for entry in audit_rows:
        if entry.endpoint in skip_endpoints:
            continue
        if entry.endpoint.startswith("/api/sync/"):
            continue
        if not any(p in entry.endpoint for p in meaningful_patterns):
            continue

        label = _classify_audit_event(entry)
        if not label:
            continue

        events.append({
            "timestamp": entry.timestamp.isoformat(),
            "type": "audit",
            "label": label,
            "detail": entry.summary,
            "success": entry.response_status < 400,
            "status_code": entry.response_status,
        })

    # Also get login events (first and last)
    login_rows = (await db.execute(
        select(AuditLog)
        .where(
            func.lower(AuditLog.user_email) == email_lower,
            or_(
                AuditLog.endpoint == "/api/auth/me",
                AuditLog.action == "LOGIN",
            ),
        )
        .order_by(AuditLog.timestamp.asc())
    )).scalars().all()

    if login_rows:
        events.append({
            "timestamp": login_rows[0].timestamp.isoformat(),
            "type": "login",
            "label": "First login",
            "detail": f"First seen in system",
            "success": True,
            "status_code": 200,
        })
        if len(login_rows) > 1:
            events.append({
                "timestamp": login_rows[-1].timestamp.isoformat(),
                "type": "login",
                "label": "Last login",
                "detail": f"Most recent activity ({len(login_rows)} total sessions)",
                "success": True,
                "status_code": 200,
            })

    # 2. Lottery applications
    lottery_apps = (await db.execute(
        select(LotteryV2Application)
        .where(func.lower(LotteryV2Application.student_email) == email_lower)
        .order_by(LotteryV2Application.created_at.asc())
    )).scalars().all()

    pt_ids = {a.assigned_permit_type_id for a in lottery_apps if a.assigned_permit_type_id}
    pt_ids.update({p for a in lottery_apps for p in (a.tier_preferences or [])})
    pt_labels: dict[str, str] = {}
    if pt_ids:
        pts = (await db.execute(select(PermitType).where(PermitType.id.in_(pt_ids)))).scalars().all()
        pt_labels = {str(pt.id): pt.label for pt in pts}

    for app in lottery_apps:
        prefs = [pt_labels.get(str(p), str(p)[:8]) for p in (app.tier_preferences or [])]
        pref_str = " > ".join(prefs) if prefs else "unknown"

        if app.created_at:
            events.append({
                "timestamp": app.created_at.isoformat(),
                "type": "lottery",
                "label": "Lottery application submitted",
                "detail": f"Preferences: {pref_str}",
                "success": True,
                "status_code": 200,
            })

        if app.status == "selected" and app.offer_expires_at:
            events.append({
                "timestamp": (app.offer_expires_at - timedelta(days=5)).isoformat(),
                "type": "lottery",
                "label": "Permit offer received",
                "detail": f"Offered: {pt_labels.get(str(app.assigned_permit_type_id), 'unknown')} — expires {app.offer_expires_at.strftime('%b %d')}",
                "success": True,
                "status_code": 200,
            })

        if app.status == "accepted":
            events.append({
                "timestamp": (app.offer_expires_at - timedelta(days=5)).isoformat() if app.offer_expires_at else (app.created_at or datetime.now(timezone.utc)).isoformat(),
                "type": "lottery",
                "label": "Offer accepted & paid",
                "detail": f"Paid for: {pt_labels.get(str(app.assigned_permit_type_id), 'unknown')}",
                "success": True,
                "status_code": 200,
            })

        if app.status == "expired":
            ts = app.offer_expires_at.isoformat() if app.offer_expires_at else (app.created_at or datetime.now(timezone.utc)).isoformat()
            events.append({
                "timestamp": ts,
                "type": "lottery",
                "label": "Offer expired (never paid)",
                "detail": f"Did not pay for: {pt_labels.get(str(app.assigned_permit_type_id), 'unknown')}",
                "success": False,
                "status_code": 0,
            })

        if app.status == "declined":
            events.append({
                "timestamp": (app.created_at or datetime.now(timezone.utc)).isoformat(),
                "type": "lottery",
                "label": "Declined offer",
                "detail": f"Declined: {pt_labels.get(str(app.assigned_permit_type_id), 'unknown')}",
                "success": False,
                "status_code": 0,
            })

        if app.status == "waitlisted":
            events.append({
                "timestamp": (app.created_at or datetime.now(timezone.utc)).isoformat(),
                "type": "lottery",
                "label": "Placed on waitlist",
                "detail": f"Position #{app.waitlist_position or '?'} for {pref_str}",
                "success": True,
                "status_code": 200,
            })

    # 3. Permits
    permits = (await db.execute(
        select(Permit)
        .where(
            func.lower(Permit.email) == email_lower,
            Permit.deleted_at.is_(None),
        )
        .order_by(Permit.created_at.asc())
    )).scalars().all()

    for p in permits:
        events.append({
            "timestamp": p.created_at.isoformat(),
            "type": "permit",
            "label": f"Permit issued: {p.permit_type}",
            "detail": f"#{p.permit_number} — plates: {', '.join(p.plates or [])} — status: {p.status}",
            "success": True,
            "status_code": 200,
        })

    # 4. Tickets (via plates from permits)
    all_plates = set()
    for p in permits:
        all_plates.update(p.plates or [])

    if all_plates:
        tickets = (await db.execute(
            select(Ticket)
            .where(func.upper(Ticket.plate).in_([pl.upper() for pl in all_plates]))
            .order_by(Ticket.issued_at.asc())
        )).scalars().all()

        for t in tickets:
            events.append({
                "timestamp": t.issued_at.isoformat(),
                "type": "ticket",
                "label": f"Citation issued: {t.violation_type or 'violation'}",
                "detail": f"#{t.ticket_number} — plate: {t.plate} — fine: ${t.fine_amount} — status: {t.status}",
                "success": True,
                "status_code": 200,
            })
            if t.status == "paid" and t.updated_at and t.updated_at != t.created_at:
                events.append({
                    "timestamp": t.updated_at.isoformat(),
                    "type": "payment",
                    "label": "Citation paid",
                    "detail": f"#{t.ticket_number} — ${t.fine_amount}",
                    "success": True,
                    "status_code": 200,
                })

    # Sort all events chronologically
    events.sort(key=lambda e: e["timestamp"])

    # Build verdict
    verdict = _build_payment_verdict(lottery_apps, permits, audit_rows, pt_labels)

    return {
        "email": email,
        "total_events": len(events),
        "verdict": verdict,
        "events": events,
    }


def _classify_audit_event(entry: AuditLog) -> str | None:
    """Map an audit log entry to a human-readable event label, or None to skip."""
    ep = entry.endpoint
    method = entry.action

    if method == "POST" and ep.rstrip("/") == "/api/lottery-v2/applications":
        return "Lottery application submitted"
    if method == "POST" and "/lottery-v2/applications/" in ep and ep.endswith("/accept"):
        return "Accepted offer — started Stripe payment"
    if method == "POST" and "/lottery-v2/applications/" in ep and ep.endswith("/decline"):
        return "Declined permit offer"
    if method == "POST" and ep.startswith("/api/payments/checkout"):
        return "Citation payment started (Stripe)"
    if method == "POST" and ep.startswith("/api/payments/standalone-purchase"):
        return "Direct permit purchase started (Stripe)"
    if method == "POST" and ep.startswith("/api/payments/permit-purchase"):
        return "Permit purchase started (Stripe)"
    if method == "GET" and ep.startswith("/api/payments/verify-session"):
        return None  # Just a verification poll
    if method == "POST" and "/swap-vehicle" in ep:
        return "Vehicle/plate swap"
    if method == "POST" and ep.startswith("/api/student/permits/purchase"):
        return "Direct permit purchase"
    if "login" in ep.lower() or method == "LOGIN":
        return None  # Handled separately
    if "auth" in ep and method == "POST":
        return "Authentication event"

    return None


def _build_payment_verdict(
    lottery_apps: list,
    permits: list,
    audit_rows: list,
    pt_labels: dict,
) -> dict:
    """Determine a clear payment verdict for the student."""
    from datetime import timezone

    # Check if they have an accepted lottery app (= paid)
    accepted = [a for a in lottery_apps if a.status == "accepted"]
    if accepted:
        app = accepted[0]
        permit_label = pt_labels.get(str(app.assigned_permit_type_id), "unknown")
        return {
            "status": "paid",
            "summary": f"Paid for {permit_label} permit via lottery",
            "color": "green",
        }

    # Check if they have active permits
    active_permits = [p for p in permits if p.status == "active"]
    if active_permits:
        p = active_permits[0]
        return {
            "status": "paid",
            "summary": f"Has active permit: {p.permit_type} (#{p.permit_number})",
            "color": "green",
        }

    # Check if they started payment but never completed
    payment_started = any(
        "/accept" in e.endpoint and e.response_status < 400
        for e in audit_rows
        if e.action == "POST"
    )
    standalone_started = any(
        "standalone-purchase" in e.endpoint and e.response_status < 400
        for e in audit_rows
        if e.action == "POST"
    )

    if payment_started or standalone_started:
        # They clicked pay but no permit exists
        selected = [a for a in lottery_apps if a.status == "selected"]
        expired = [a for a in lottery_apps if a.status == "expired"]
        if selected:
            return {
                "status": "payment_started",
                "summary": "Payment was initiated (Stripe session created) but never completed — offer still open",
                "color": "orange",
            }
        elif expired:
            return {
                "status": "payment_started_expired",
                "summary": "Payment was initiated but never completed — offer has since expired",
                "color": "red",
            }
        return {
            "status": "payment_started",
            "summary": "Payment session was created (Stripe) but no permit was issued — payment likely abandoned",
            "color": "orange",
        }

    # Check if they have a selected (pending) offer
    selected = [a for a in lottery_apps if a.status == "selected"]
    if selected:
        app = selected[0]
        permit_label = pt_labels.get(str(app.assigned_permit_type_id), "unknown")
        expires = app.offer_expires_at.strftime("%b %d, %Y") if app.offer_expires_at else "unknown"
        return {
            "status": "offer_pending",
            "summary": f"Has open offer for {permit_label} — expires {expires} — NO payment initiated yet",
            "color": "orange",
        }

    # Waitlisted
    waitlisted = [a for a in lottery_apps if a.status == "waitlisted"]
    if waitlisted:
        return {
            "status": "waitlisted",
            "summary": "On waitlist — no offer received yet, no payment expected",
            "color": "blue",
        }

    # Nothing
    return {
        "status": "no_payment",
        "summary": "No payment record found — no permit purchase or lottery payment was ever initiated",
        "color": "red",
    }
