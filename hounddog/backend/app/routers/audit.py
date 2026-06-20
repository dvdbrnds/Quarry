from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user
from ..database import get_db
from ..models.audit_log import AuditLog
from ..schemas.audit import AuditLogList, AuditLogRead

router = APIRouter(dependencies=[Depends(get_current_user)])


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
