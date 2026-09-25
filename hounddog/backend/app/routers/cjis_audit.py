"""
CJIS administration endpoints — audit logs, alerts, user management.

All endpoints require cjis_admin role.
No CJI data is ever returned from these endpoints.
"""

import csv
import io
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, desc, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..utils.safe_router import SafeRouter
from ..database import get_db
from ..models.cjis_audit_log import CJISAuditLog
from ..models.cjis_audit_alert import CJISAuditAlert
from ..models.cjis_incident import CJISIncident
from ..models.jnet_authorized_user import JNETAuthorizedUser
from ..services.jnet.dependencies import require_cjis_admin_visible
from ..services.jnet.config import jnet_settings

router = SafeRouter(
    prefix="/api/cjis",
    tags=["CJIS Administration"],
    dependencies=[Depends(require_cjis_admin_visible)],
)


# ── Audit Logs ───────────────────────────────────────────────────────────────


@router.get("/audit/logs")
async def list_audit_logs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    user_email: str | None = None,
    plate: str | None = None,
    success: bool | None = None,
):
    """Paginated CJIS audit log. Returns query metadata only — no CJI."""
    query = select(CJISAuditLog).order_by(desc(CJISAuditLog.timestamp))

    if date_from:
        query = query.where(CJISAuditLog.timestamp >= date_from)
    if date_to:
        query = query.where(CJISAuditLog.timestamp <= date_to)
    if user_email:
        query = query.where(CJISAuditLog.user_email.ilike(f"%{user_email}%"))
    if plate:
        query = query.where(CJISAuditLog.query_plate == plate.upper().strip())
    if success is not None:
        query = query.where(CJISAuditLog.success == success)

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Page
    offset = (page - 1) * page_size
    rows = (
        await db.execute(query.offset(offset).limit(page_size))
    ).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(r.id),
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "user_email": r.user_email,
                "user_full_name": r.user_full_name,
                "action": r.action,
                "query_plate": r.query_plate,
                "query_state": r.query_state,
                "ori": r.ori,
                "source_ip": r.source_ip,
                "device_id": r.device_id,
                "success": r.success,
                "error_message": r.error_message,
                "response_time_ms": r.response_time_ms,
            }
            for r in rows
        ],
    }


@router.get("/audit/logs/export")
async def export_audit_logs(
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """CSV export of CJIS audit logs for compliance reporting."""
    query = select(CJISAuditLog).order_by(desc(CJISAuditLog.timestamp))

    if date_from:
        query = query.where(CJISAuditLog.timestamp >= date_from)
    if date_to:
        query = query.where(CJISAuditLog.timestamp <= date_to)

    rows = (await db.execute(query)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "timestamp", "user_email", "user_full_name", "action",
        "query_plate", "query_state", "ori", "source_ip",
        "device_id", "success", "error_message", "response_time_ms",
    ])

    for r in rows:
        writer.writerow([
            r.timestamp.isoformat() if r.timestamp else "",
            r.user_email,
            r.user_full_name,
            r.action,
            r.query_plate,
            r.query_state,
            r.ori,
            r.source_ip,
            r.device_id or "",
            r.success,
            r.error_message or "",
            r.response_time_ms,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=cjis_audit_log.csv"},
    )


@router.get("/audit/stats")
async def audit_stats(db: AsyncSession = Depends(get_db)):
    """Dashboard aggregates: queries per day, per officer, per hour."""
    now = datetime.now(timezone.utc)

    # Queries today
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_count = (
        await db.execute(
            select(func.count()).where(CJISAuditLog.timestamp >= today_start)
        )
    ).scalar() or 0

    # Queries this week
    week_start = today_start - timedelta(days=now.weekday())
    week_count = (
        await db.execute(
            select(func.count()).where(CJISAuditLog.timestamp >= week_start)
        )
    ).scalar() or 0

    # Queries this month
    month_start = today_start.replace(day=1)
    month_count = (
        await db.execute(
            select(func.count()).where(CJISAuditLog.timestamp >= month_start)
        )
    ).scalar() or 0

    # Per-officer counts (last 30 days)
    thirty_days_ago = now - timedelta(days=30)
    officer_counts = (
        await db.execute(
            select(
                CJISAuditLog.user_email,
                CJISAuditLog.user_full_name,
                func.count().label("query_count"),
            )
            .where(CJISAuditLog.timestamp >= thirty_days_ago)
            .group_by(CJISAuditLog.user_email, CJISAuditLog.user_full_name)
            .order_by(desc("query_count"))
        )
    ).all()

    # Per-hour distribution (last 30 days)
    hour_dist = (
        await db.execute(
            select(
                func.extract("hour", CJISAuditLog.timestamp).label("hour"),
                func.count().label("count"),
            )
            .where(CJISAuditLog.timestamp >= thirty_days_ago)
            .group_by("hour")
            .order_by("hour")
        )
    ).all()

    # Pending alerts count
    pending_alerts = (
        await db.execute(
            select(func.count()).where(
                and_(
                    CJISAuditAlert.dismissed == False,  # noqa: E712
                    CJISAuditAlert.reviewed_at.is_(None),
                )
            )
        )
    ).scalar() or 0

    return {
        "queries_today": today_count,
        "queries_this_week": week_count,
        "queries_this_month": month_count,
        "pending_alerts": pending_alerts,
        "officer_counts": [
            {
                "email": row.user_email,
                "name": row.user_full_name,
                "count": row.query_count,
            }
            for row in officer_counts
        ],
        "hourly_distribution": [
            {"hour": int(row.hour), "count": row.count}
            for row in hour_dist
        ],
    }


# ── Alerts ───────────────────────────────────────────────────────────────────


@router.get("/audit/alerts")
async def list_alerts(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    alert_type: str | None = None,
    status: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    """List anomaly alerts with filtering."""
    query = select(CJISAuditAlert).order_by(desc(CJISAuditAlert.created_at))

    if alert_type:
        query = query.where(CJISAuditAlert.alert_type == alert_type)
    if status == "pending":
        query = query.where(
            and_(
                CJISAuditAlert.dismissed == False,  # noqa: E712
                CJISAuditAlert.reviewed_at.is_(None),
            )
        )
    elif status == "reviewed":
        query = query.where(CJISAuditAlert.reviewed_at.isnot(None))
    elif status == "dismissed":
        query = query.where(CJISAuditAlert.dismissed == True)  # noqa: E712
    if date_from:
        query = query.where(CJISAuditAlert.created_at >= date_from)
    if date_to:
        query = query.where(CJISAuditAlert.created_at <= date_to)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(query.offset(offset).limit(page_size))
    ).scalars().all()

    # Last full review date
    last_review = (
        await db.execute(
            select(func.max(CJISAuditAlert.reviewed_at)).where(
                CJISAuditAlert.reviewed_at.isnot(None)
            )
        )
    ).scalar()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "last_full_review": last_review.isoformat() if last_review else None,
        "items": [
            {
                "id": str(a.id),
                "audit_log_id": str(a.audit_log_id) if a.audit_log_id else None,
                "alert_type": a.alert_type,
                "description": a.description,
                "reviewed_by": a.reviewed_by,
                "reviewed_at": a.reviewed_at.isoformat() if a.reviewed_at else None,
                "dismissed": a.dismissed,
                "dismiss_reason": a.dismiss_reason,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in rows
        ],
    }


class ReviewAlertBody(BaseModel):
    dismissed: bool = False
    dismiss_reason: str | None = None


@router.post("/audit/alerts/{alert_id}/review")
async def review_alert(
    alert_id: uuid.UUID,
    body: ReviewAlertBody,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Mark an alert as reviewed or dismissed."""
    result = await db.execute(
        select(CJISAuditAlert).where(CJISAuditAlert.id == alert_id)
    )
    alert = result.scalars().first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.reviewed_by = jnet_user.email
    alert.reviewed_at = datetime.now(timezone.utc)
    alert.dismissed = body.dismissed
    if body.dismiss_reason:
        alert.dismiss_reason = body.dismiss_reason

    return {"status": "ok", "alert_id": str(alert_id)}


# ── User Management ─────────────────────────────────────────────────────────


@router.get("/users")
async def list_jnet_users(db: AsyncSession = Depends(get_db)):
    """List all users with JNET authorization status."""
    rows = (
        await db.execute(
            select(JNETAuthorizedUser).order_by(JNETAuthorizedUser.email)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(u.id),
                "okta_sub": u.okta_sub,
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "jnet_authorized": u.jnet_authorized,
                "jnet_authorized_by_email": u.jnet_authorized_by_email,
                "jnet_authorized_at": u.jnet_authorized_at.isoformat() if u.jnet_authorized_at else None,
                "jnet_background_check_date": u.jnet_background_check_date.isoformat() if u.jnet_background_check_date else None,
                "jnet_training_completed_at": u.jnet_training_completed_at.isoformat() if u.jnet_training_completed_at else None,
                "jnet_last_activity": u.jnet_last_activity.isoformat() if u.jnet_last_activity else None,
                "jnet_last_access_review": u.jnet_last_access_review.isoformat() if u.jnet_last_access_review else None,
            }
            for u in rows
        ]
    }


class AuthorizeUserBody(BaseModel):
    okta_sub: str
    email: str
    full_name: str
    role: str = "jnet_officer"


@router.post("/users/{user_id}/authorize")
async def authorize_user(
    user_id: uuid.UUID,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Grant JNET access to a user."""
    result = await db.execute(
        select(JNETAuthorizedUser).where(JNETAuthorizedUser.id == user_id)
    )
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.jnet_authorized = True
    target.jnet_authorized_by_email = jnet_user.email
    target.jnet_authorized_at = datetime.now(timezone.utc)

    return {"status": "ok", "user_id": str(user_id)}


@router.post("/users/create")
async def create_jnet_user(
    body: AuthorizeUserBody,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Create a new JNET authorized user record."""
    existing = await db.execute(
        select(JNETAuthorizedUser).where(
            or_(
                JNETAuthorizedUser.okta_sub == body.okta_sub,
                JNETAuthorizedUser.email == body.email,
            )
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="User already exists")

    new_user = JNETAuthorizedUser(
        okta_sub=body.okta_sub,
        email=body.email,
        full_name=body.full_name,
        role=body.role,
        jnet_authorized=True,
        jnet_authorized_by_email=jnet_user.email,
        jnet_authorized_at=datetime.now(timezone.utc),
    )
    db.add(new_user)

    return {"status": "ok", "user_id": str(new_user.id)}


@router.post("/users/{user_id}/revoke")
async def revoke_user(
    user_id: uuid.UUID,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Revoke JNET access from a user."""
    result = await db.execute(
        select(JNETAuthorizedUser).where(JNETAuthorizedUser.id == user_id)
    )
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.jnet_authorized = False

    return {"status": "ok", "user_id": str(user_id)}


class BackgroundCheckBody(BaseModel):
    date: datetime


@router.put("/users/{user_id}/background-check")
async def record_background_check(
    user_id: uuid.UUID,
    body: BackgroundCheckBody,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Record a background check completion date."""
    result = await db.execute(
        select(JNETAuthorizedUser).where(JNETAuthorizedUser.id == user_id)
    )
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.jnet_background_check_date = body.date

    return {"status": "ok", "user_id": str(user_id)}


class TrainingBody(BaseModel):
    date: datetime


@router.put("/users/{user_id}/training")
async def record_training(
    user_id: uuid.UUID,
    body: TrainingBody,
    jnet_user: JNETAuthorizedUser = Depends(require_cjis_admin_visible),
    db: AsyncSession = Depends(get_db),
):
    """Record security awareness training completion date."""
    result = await db.execute(
        select(JNETAuthorizedUser).where(JNETAuthorizedUser.id == user_id)
    )
    target = result.scalars().first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.jnet_training_completed_at = body.date

    return {"status": "ok", "user_id": str(user_id)}


@router.get("/users/access-review")
async def access_review_due(db: AsyncSession = Depends(get_db)):
    """List users due for periodic access review (last review > 90 days ago)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)

    rows = (
        await db.execute(
            select(JNETAuthorizedUser).where(
                and_(
                    JNETAuthorizedUser.jnet_authorized == True,  # noqa: E712
                    or_(
                        JNETAuthorizedUser.jnet_last_access_review.is_(None),
                        JNETAuthorizedUser.jnet_last_access_review < cutoff,
                    ),
                )
            ).order_by(JNETAuthorizedUser.email)
        )
    ).scalars().all()

    return {
        "items": [
            {
                "id": str(u.id),
                "email": u.email,
                "full_name": u.full_name,
                "role": u.role,
                "jnet_last_access_review": u.jnet_last_access_review.isoformat() if u.jnet_last_access_review else None,
                "jnet_last_activity": u.jnet_last_activity.isoformat() if u.jnet_last_activity else None,
            }
            for u in rows
        ]
    }


# ── Incidents ────────────────────────────────────────────────────────────────


@router.get("/incidents")
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List CJIS security incidents."""
    query = select(CJISIncident).order_by(desc(CJISIncident.timestamp))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    offset = (page - 1) * page_size
    rows = (
        await db.execute(query.offset(offset).limit(page_size))
    ).scalars().all()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": str(i.id),
                "timestamp": i.timestamp.isoformat() if i.timestamp else None,
                "incident_type": i.incident_type,
                "description": i.description,
                "affected_records_count": i.affected_records_count,
                "detected_by": i.detected_by,
                "reported_to_iso_at": i.reported_to_iso_at.isoformat() if i.reported_to_iso_at else None,
                "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
                "resolution_notes": i.resolution_notes,
            }
            for i in rows
        ],
    }
