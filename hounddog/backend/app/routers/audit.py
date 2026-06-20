import logging
import traceback

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser
from ..database import get_db, async_session
from ..models.audit_log import AuditLog
from ..schemas.audit import AuditLogList, AuditLogRead

logger = logging.getLogger("quarry.audit")

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("/diagnostic")
async def audit_diagnostic(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Diagnostic endpoint: tests every piece of the audit chain."""
    results: dict = {"user": user.email, "steps": {}}

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

    # 2. Can we write to it?
    try:
        test_entry = AuditLog(
            user_email=user.email,
            user_sub=user.sub,
            action="DIAGNOSTIC",
            resource_type="audit",
            endpoint="/api/audit/diagnostic",
            summary=f"Audit diagnostic test by {user.email}",
            response_status=200,
        )
        db.add(test_entry)
        await db.flush()
        results["steps"]["write_ok"] = True
        results["steps"]["test_entry_id"] = str(test_entry.id)
    except Exception as e:
        results["steps"]["write_ok"] = False
        results["steps"]["write_error"] = f"{type(e).__name__}: {e}"
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

    # 4. Can the middleware's async_session write?
    try:
        async with async_session() as mw_session:
            async with mw_session.begin():
                mw_entry = AuditLog(
                    user_email=user.email,
                    user_sub=user.sub,
                    action="DIAGNOSTIC",
                    resource_type="audit",
                    endpoint="/api/audit/diagnostic",
                    summary=f"Middleware-style write test by {user.email}",
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
        query = query.where(AuditLog.summary.ilike(f"%{search}%"))

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(desc(AuditLog.timestamp))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    return AuditLogList(items=items, total=total, page=page, page_size=page_size)


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
    return result.scalars().all()
