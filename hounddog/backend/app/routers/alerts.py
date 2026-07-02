import csv
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser, require_role
from ..config import settings
from ..database import get_db
from ..models.alert_log import AlertLog
from ..models.alert_subscriber import AlertSubscriber
from ..schemas.alerts import (
    ActiveAlertRead,
    AlertChannelRead,
    AlertLogRead,
    AlertSendPreview,
    AlertSendRequest,
    AlertSendResult,
    AlertTestRequest,
    PublicSubscribeRequest,
    PublicSubscribeResponse,
    SubscriberCreate,
    SubscriberRead,
    SubscriberUpdate,
)
from ..services.alert_dispatcher import clear_alert, dispatch_alert
from ..services.channels import get_registry

logger = logging.getLogger("quarry.alerts")

admin_router = APIRouter(dependencies=[Depends(require_role("admin", "staff"))])
public_router = APIRouter()


# ---------------------------------------------------------------------------
# Public endpoints (no auth)
# ---------------------------------------------------------------------------

@public_router.post("/subscribe", response_model=PublicSubscribeResponse, status_code=201)
async def public_subscribe(data: PublicSubscribeRequest, db: AsyncSession = Depends(get_db)):
    if not data.email and not data.phone:
        raise HTTPException(400, "At least one of email or phone is required")

    if data.email:
        existing = await db.execute(
            select(AlertSubscriber).where(AlertSubscriber.email == data.email)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(409, "This email is already subscribed")

    subscriber = AlertSubscriber(
        name=data.name,
        email=data.email,
        phone=data.phone,
        categories=data.categories or ["emergency", "weather", "campus_closing", "parking", "general"],
        source="self",
    )
    db.add(subscriber)
    await db.flush()
    await db.refresh(subscriber)
    return PublicSubscribeResponse(
        message="Successfully subscribed to alerts",
        subscriber_id=subscriber.id,
    )


@public_router.get("/unsubscribe/{token}")
async def public_unsubscribe(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertSubscriber).where(AlertSubscriber.unsubscribe_token == token)
    )
    subscriber = result.scalar_one_or_none()
    if not subscriber:
        raise HTTPException(404, "Invalid unsubscribe link")

    await db.delete(subscriber)
    await db.flush()
    return {"message": "You have been unsubscribed from all alerts."}


@public_router.get("/active")
async def get_active_alert(db: AsyncSession = Depends(get_db)):
    """Public endpoint for website banner JS and signage players to poll."""
    from ..services.channels.banner_channel import get_active_banner
    banner = get_active_banner()
    if banner:
        return banner
    result = await db.execute(
        select(AlertLog)
        .where(AlertLog.status == "active")
        .order_by(AlertLog.sent_at.desc())
        .limit(1)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return None
    return ActiveAlertRead.model_validate(alert)


# ---------------------------------------------------------------------------
# Admin: Send, Clear, Test & Preview
# ---------------------------------------------------------------------------

@admin_router.get("/send/preview", response_model=AlertSendPreview)
async def preview_send(
    category: str = Query("emergency"),
    db: AsyncSession = Depends(get_db),
):
    is_emergency = category == "emergency"

    total_q = select(func.count()).select_from(AlertSubscriber)
    total = await db.scalar(total_q) or 0

    if is_emergency:
        email_q = select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.email.isnot(None),
            AlertSubscriber.email_enabled.is_(True),
        )
        sms_q = select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
        )
    else:
        email_q = select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.email.isnot(None),
            AlertSubscriber.email_enabled.is_(True),
            AlertSubscriber.categories.op("@>")(f'["{category}"]'),
        )
        sms_q = select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
            AlertSubscriber.categories.op("@>")(f'["{category}"]'),
        )

    email_count = await db.scalar(email_q) or 0
    sms_count = await db.scalar(sms_q) or 0

    configured_channels = [c.name for c in get_registry() if c.is_configured()]

    return AlertSendPreview(
        category=category,
        email_recipient_count=email_count,
        sms_recipient_count=sms_count,
        total_subscribers=total,
        configured_channels=configured_channels,
    )


@admin_router.post("/send", response_model=AlertSendResult)
async def send_alert(
    data: AlertSendRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    log_entry = AlertLog(
        category=data.category,
        subject=data.subject,
        body_text=data.body_text,
        body_sms=data.body_sms,
        sent_by=user.email,
        status="active",
    )
    db.add(log_entry)
    await db.flush()
    await db.refresh(log_entry)

    channel_results = await dispatch_alert(log_entry.id, db)

    await db.refresh(log_entry)

    return AlertSendResult(
        alert_id=log_entry.id,
        emails_sent=log_entry.email_count,
        sms_sent=log_entry.sms_count,
        channel_results=channel_results,
    )


@admin_router.post("/{alert_id}/clear", response_model=AlertLogRead)
async def clear_alert_endpoint(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    alert = await clear_alert(alert_id, user.email, db)
    if not alert:
        raise HTTPException(404, "Alert not found or already cleared")
    return alert


@admin_router.post("/{alert_id}/test", response_model=AlertSendResult)
async def test_alert_channel(
    alert_id: uuid.UUID,
    data: AlertTestRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Send an alert to a single channel for testing."""
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    channel_results = await dispatch_alert(alert_id, db, channels=[data.channel])

    await db.refresh(alert)

    return AlertSendResult(
        alert_id=alert.id,
        emails_sent=alert.email_count,
        sms_sent=alert.sms_count,
        channel_results=channel_results,
    )


# ---------------------------------------------------------------------------
# Admin: Channels
# ---------------------------------------------------------------------------

@admin_router.get("/channels", response_model=list[AlertChannelRead])
async def list_channels():
    """List all registered alert channels with their configuration status."""
    result = []
    for ch in get_registry():
        result.append(AlertChannelRead(
            name=ch.name,
            configured=ch.is_configured(),
            emergency_only=ch.emergency_only,
        ))
    return result


# ---------------------------------------------------------------------------
# Admin: Alert History
# ---------------------------------------------------------------------------

@admin_router.get("/history", response_model=list[AlertLogRead])
async def list_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AlertLog)
        .order_by(AlertLog.sent_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Admin: Subscriber CRUD
# ---------------------------------------------------------------------------

@admin_router.get("/subscribers", response_model=list[SubscriberRead])
async def list_subscribers(
    search: str | None = Query(None),
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(AlertSubscriber).order_by(AlertSubscriber.name)

    if search:
        pattern = f"%{search}%"
        q = q.where(
            or_(
                AlertSubscriber.name.ilike(pattern),
                AlertSubscriber.email.ilike(pattern),
                AlertSubscriber.phone.ilike(pattern),
            )
        )

    if category:
        q = q.where(AlertSubscriber.categories.op("@>")(f'["{category}"]'))

    result = await db.execute(q)
    return result.scalars().all()


@admin_router.post("/subscribers", response_model=SubscriberRead, status_code=201)
async def create_subscriber(
    data: SubscriberCreate,
    db: AsyncSession = Depends(get_db),
):
    if not data.email and not data.phone:
        raise HTTPException(400, "At least one of email or phone is required")

    subscriber = AlertSubscriber(
        name=data.name,
        email=data.email,
        phone=data.phone,
        sms_enabled=data.sms_enabled,
        email_enabled=data.email_enabled,
        categories=data.categories or ["emergency"],
        source=data.source,
    )
    db.add(subscriber)
    await db.flush()
    await db.refresh(subscriber)
    return subscriber


@admin_router.put("/subscribers/{subscriber_id}", response_model=SubscriberRead)
async def update_subscriber(
    subscriber_id: uuid.UUID,
    data: SubscriberUpdate,
    db: AsyncSession = Depends(get_db),
):
    subscriber = await db.get(AlertSubscriber, subscriber_id)
    if not subscriber:
        raise HTTPException(404, "Subscriber not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(subscriber, field, value)

    await db.flush()
    await db.refresh(subscriber)
    return subscriber


@admin_router.delete("/subscribers/{subscriber_id}", status_code=204)
async def delete_subscriber(
    subscriber_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    subscriber = await db.get(AlertSubscriber, subscriber_id)
    if not subscriber:
        raise HTTPException(404, "Subscriber not found")
    await db.delete(subscriber)
    await db.flush()


# ---------------------------------------------------------------------------
# Admin: Import / Export
# ---------------------------------------------------------------------------

@admin_router.post("/subscribers/import")
async def import_subscribers(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if not file.filename or not file.filename.endswith(".csv"):
        raise HTTPException(400, "File must be a CSV")

    content = await file.read()
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    created = 0
    skipped = 0
    for row in reader:
        name = row.get("name", "").strip()
        email = row.get("email", "").strip() or None
        phone = row.get("phone", "").strip() or None

        if not name or (not email and not phone):
            skipped += 1
            continue

        if email:
            existing = await db.execute(
                select(AlertSubscriber).where(AlertSubscriber.email == email)
            )
            if existing.scalar_one_or_none():
                skipped += 1
                continue

        cats_raw = row.get("categories", "").strip()
        categories = [c.strip() for c in cats_raw.split(",")] if cats_raw else ["emergency"]

        subscriber = AlertSubscriber(
            name=name,
            email=email,
            phone=phone,
            categories=categories,
            source="import",
        )
        db.add(subscriber)
        created += 1

    await db.flush()
    return {"created": created, "skipped": skipped}


@admin_router.get("/subscribers/export")
async def export_subscribers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertSubscriber).order_by(AlertSubscriber.name)
    )
    subscribers = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "email", "phone", "categories", "sms_enabled", "email_enabled", "source"])
    for s in subscribers:
        writer.writerow([
            s.name,
            s.email or "",
            s.phone or "",
            ",".join(s.categories) if s.categories else "",
            str(s.sms_enabled),
            str(s.email_enabled),
            s.source,
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=alert_subscribers.csv"},
    )
