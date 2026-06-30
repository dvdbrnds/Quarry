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
    AlertLogRead,
    AlertSendPreview,
    AlertSendRequest,
    AlertSendResult,
    PublicSubscribeRequest,
    PublicSubscribeResponse,
    SubscriberCreate,
    SubscriberRead,
    SubscriberUpdate,
)
from ..services.email import send_email
from ..services.sms import send_bulk_sms

logger = logging.getLogger("quarry.alerts")

admin_router = APIRouter(dependencies=[Depends(require_role("admin", "staff"))])
public_router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unsubscribe_url(token: str) -> str:
    return f"{settings.public_url}/alerts/unsubscribe/{token}"


def _build_email_html(subject: str, body: str, unsub_token: str) -> str:
    school = settings.school_name or "Campus"
    unsub_link = _unsubscribe_url(unsub_token)
    return f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
        <h2 style="color: #1a2744;">{subject}</h2>
        <div style="white-space: pre-wrap;">{body}</div>
        <hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;">
        <p style="font-size: 12px; color: #888;">{school} — Quarry Alerts</p>
        <p style="font-size: 11px; color: #aaa;">
            <a href="{unsub_link}" style="color: #aaa;">Unsubscribe from alerts</a>
        </p>
    </div>
    """


def _build_sms_body(body: str, unsub_token: str) -> str:
    unsub_link = _unsubscribe_url(unsub_token)
    return f"{body}\n\nUnsubscribe: {unsub_link}"


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


# ---------------------------------------------------------------------------
# Admin: Send & Preview
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
        from sqlalchemy import cast, String
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

    return AlertSendPreview(
        category=category,
        email_recipient_count=email_count,
        sms_recipient_count=sms_count,
        total_subscribers=total,
    )


@admin_router.post("/send", response_model=AlertSendResult)
async def send_alert(
    data: AlertSendRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    is_emergency = data.category == "emergency"

    if is_emergency:
        q = select(AlertSubscriber).where(
            or_(
                AlertSubscriber.email.isnot(None),
                AlertSubscriber.phone.isnot(None),
            )
        )
    else:
        q = select(AlertSubscriber).where(
            AlertSubscriber.categories.op("@>")(f'["{data.category}"]'),
            or_(
                AlertSubscriber.email.isnot(None),
                AlertSubscriber.phone.isnot(None),
            ),
        )

    subscribers = (await db.execute(q)).scalars().all()

    emails_sent = 0
    sms_sent = 0

    if data.send_email and data.subject:
        email_recipients = [
            s for s in subscribers
            if s.email and s.email_enabled
        ]
        for batch_start in range(0, len(email_recipients), 50):
            batch = email_recipients[batch_start:batch_start + 50]
            for sub in batch:
                html = _build_email_html(data.subject, data.body_text, sub.unsubscribe_token)
                text_body = f"{data.body_text}\n\nUnsubscribe: {_unsubscribe_url(sub.unsubscribe_token)}"
                success = await send_email([sub.email], data.subject, html, text_body)
                if success:
                    emails_sent += 1

    if data.send_sms and data.body_sms:
        sms_recipients = [
            s for s in subscribers
            if s.phone and s.sms_enabled
        ]
        for sub in sms_recipients:
            sms_text = _build_sms_body(data.body_sms, sub.unsubscribe_token)
            sent = send_bulk_sms([sub.phone], sms_text)
            sms_sent += sent

    log_entry = AlertLog(
        category=data.category,
        subject=data.subject,
        body_text=data.body_text,
        body_sms=data.body_sms,
        sent_by=user.email,
        email_count=emails_sent,
        sms_count=sms_sent,
    )
    db.add(log_entry)
    await db.flush()
    await db.refresh(log_entry)

    return AlertSendResult(
        emails_sent=emails_sent,
        sms_sent=sms_sent,
        alert_id=log_entry.id,
    )


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
