import csv
import io
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import get_current_user, OktaUser, require_role
from ..config import settings
from ..database import get_db
from ..models.alert_log import AlertLog
from ..models.alert_response import AlertResponse
from ..models.alert_scenario import AlertScenario
from ..models.alert_subscriber import AlertSubscriber
from ..models.alert_template import AlertTemplate
from ..models.subscriber_group import SubscriberGroup, subscriber_group_members
from ..schemas.alerts import (
    ActiveAlertRead,
    AlertChannelRead,
    AlertLogRead,
    AlertResponseRead,
    AlertResponseSummary,
    AlertScenarioCreate,
    AlertScenarioRead,
    AlertScenarioUpdate,
    AlertSendPreview,
    AlertSendRequest,
    AlertSendResult,
    AlertTemplateCreate,
    AlertTemplateRead,
    AlertTemplateUpdate,
    AlertTestRequest,
    AlertTestSendRequest,
    AlertTestSendResult,
    CheckInStatus,
    GroupMembersBatch,
    PublicSubscribeRequest,
    PublicSubscribeResponse,
    RunningScenario,
    SubscriberCreate,
    SubscriberGroupCreate,
    SubscriberGroupRead,
    SubscriberGroupUpdate,
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
    from fastapi.responses import JSONResponse
    from ..services.channels.banner_channel import get_active_banner

    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Cache-Control": "no-cache",
    }

    banner = get_active_banner()
    if banner:
        return JSONResponse(content=banner, headers=cors_headers)

    result = await db.execute(
        select(AlertLog)
        .where(AlertLog.status == "active")
        .order_by(AlertLog.sent_at.desc())
        .limit(1)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return JSONResponse(content=None, headers=cors_headers)
    return JSONResponse(
        content=ActiveAlertRead.model_validate(alert).model_dump(mode="json"),
        headers=cors_headers,
    )


@public_router.post("/webhooks/twilio/inbound")
async def twilio_inbound_sms(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive inbound SMS replies from Twilio."""
    form = await request.form()
    from_number = str(form.get("From", ""))
    body = str(form.get("Body", "")).strip()

    if not from_number or not body:
        return "<Response></Response>"

    # Normalize phone number
    phone = from_number.strip()

    # Look up subscriber by phone
    result = await db.execute(
        select(AlertSubscriber).where(AlertSubscriber.phone == phone)
    )
    subscriber = result.scalar_one_or_none()

    # Find the most recent active alert that has response_options
    alert_result = await db.execute(
        select(AlertLog)
        .where(
            AlertLog.status == "active",
            AlertLog.response_options.isnot(None),
        )
        .order_by(AlertLog.sent_at.desc())
        .limit(1)
    )
    alert = alert_result.scalar_one_or_none()

    if not alert:
        # No active alert expecting responses -- still log it
        alert_result = await db.execute(
            select(AlertLog)
            .where(AlertLog.status == "active")
            .order_by(AlertLog.sent_at.desc())
            .limit(1)
        )
        alert = alert_result.scalar_one_or_none()

    response = AlertResponse(
        alert_id=alert.id if alert else None,
        subscriber_id=subscriber.id if subscriber else None,
        phone=phone,
        channel="sms",
        response_text=body,
    )

    if alert:
        db.add(response)
        await db.flush()

    from fastapi.responses import Response
    return Response(
        content="<Response></Response>",
        media_type="application/xml",
    )


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
    response_options = data.response_options
    if data.is_checkin and not response_options:
        response_options = ["SAFE", "HELP"]

    sms_body = data.body_sms
    if response_options and sms_body:
        options_str = ", ".join(response_options)
        sms_body = f"{sms_body}\n\nReply: {options_str}"

    log_entry = AlertLog(
        category=data.category,
        subject=data.subject,
        body_text=data.body_text,
        body_sms=sms_body,
        sent_by=user.email,
        status="active",
        response_options=response_options,
        is_checkin=data.is_checkin,
        target_group_ids=[str(g) for g in data.group_ids] if data.group_ids else None,
    )
    db.add(log_entry)
    await db.flush()
    await db.refresh(log_entry)

    channel_results = await dispatch_alert(
        log_entry.id, db,
        group_ids=data.group_ids,
    )

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


@admin_router.post("/test-send", response_model=AlertTestSendResult)
async def test_send_channel(
    data: AlertTestSendRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    """Isolated test of a single channel. Creates a status='test' alert that
    never appears as active. For subscriber-based channels (sms, email, voice),
    uses the provided test_email/test_phone instead of the subscriber list.
    For signage, targets a single screen_id if provided."""

    registry = get_registry()
    channel_obj = next((c for c in registry if c.name == data.channel), None)
    if not channel_obj:
        raise HTTPException(400, f"Unknown channel: {data.channel}")
    if not channel_obj.is_configured():
        raise HTTPException(400, f"Channel '{data.channel}' is not configured")
    if channel_obj.emergency_only and data.category != "emergency":
        raise HTTPException(
            400,
            f"Channel '{data.channel}' is emergency-only. Set category to 'emergency' to test it.",
        )

    subscriber_channels = {"sms", "email", "voice"}
    if data.channel in subscriber_channels and not data.test_email and not data.test_phone:
        raise HTTPException(
            400,
            f"Channel '{data.channel}' requires a test_email or test_phone recipient.",
        )

    log_entry = AlertLog(
        category=data.category,
        subject=f"[TEST] {data.subject}",
        body_text=data.body_text,
        body_sms=data.body_sms,
        sent_by=user.email,
        status="test",
    )
    db.add(log_entry)
    await db.flush()
    await db.refresh(log_entry)

    test_subs = None
    if data.channel in subscriber_channels:
        from types import SimpleNamespace
        test_subs = [SimpleNamespace(
            id=uuid.uuid4(),
            name="Test Recipient",
            email=data.test_email,
            phone=data.test_phone,
            sms_enabled=True,
            email_enabled=True,
            categories=["emergency", "weather", "campus_closing", "parking", "general"],
            unsubscribe_token="test-no-unsubscribe",
        )]

    channel_results = await dispatch_alert(
        log_entry.id, db,
        channels=[data.channel],
        test_subscribers=test_subs,
    )

    result = channel_results.get(data.channel, {})

    from datetime import datetime, timezone
    log_entry.status = "test"
    log_entry.cleared_at = datetime.now(timezone.utc)
    log_entry.cleared_by = "auto-test"
    await db.flush()

    return AlertTestSendResult(
        alert_id=log_entry.id,
        channel=data.channel,
        sent=result.get("sent", 0),
        failed=result.get("failed", 0),
        error=result.get("error"),
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
    include_tests: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    q = select(AlertLog)
    if not include_tests:
        q = q.where(AlertLog.status != "test")
    result = await db.execute(
        q.order_by(AlertLog.sent_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


# ---------------------------------------------------------------------------
# Admin: Alert Templates CRUD
# ---------------------------------------------------------------------------

@admin_router.get("/templates", response_model=list[AlertTemplateRead])
async def list_templates(
    category: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(AlertTemplate).order_by(AlertTemplate.name)
    if category:
        q = q.where(AlertTemplate.category == category)
    result = await db.execute(q)
    return result.scalars().all()


@admin_router.get("/templates/{template_id}", response_model=AlertTemplateRead)
async def get_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    template = await db.get(AlertTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    return template


@admin_router.post("/templates", response_model=AlertTemplateRead, status_code=201)
async def create_template(
    data: AlertTemplateCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    template = AlertTemplate(
        name=data.name,
        category=data.category,
        subject=data.subject,
        body_text=data.body_text,
        body_sms=data.body_sms,
        is_default=data.is_default,
        created_by=user.email,
    )
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@admin_router.put("/templates/{template_id}", response_model=AlertTemplateRead)
async def update_template(
    template_id: uuid.UUID,
    data: AlertTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(AlertTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)
    await db.flush()
    await db.refresh(template)
    return template


@admin_router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    template = await db.get(AlertTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    await db.delete(template)
    await db.flush()


# ---------------------------------------------------------------------------
# Admin: Two-Way SMS Responses
# ---------------------------------------------------------------------------

@admin_router.get("/{alert_id}/responses", response_model=AlertResponseSummary)
async def get_response_summary(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    total_sent = alert.sms_count + alert.email_count

    responses = (await db.execute(
        select(AlertResponse).where(AlertResponse.alert_id == alert_id)
    )).scalars().all()

    response_counts: dict[str, int] = {}
    first_at = None
    last_at = None
    for r in responses:
        key = r.response_text.upper().strip()
        response_counts[key] = response_counts.get(key, 0) + 1
        if first_at is None or r.received_at < first_at:
            first_at = r.received_at
        if last_at is None or r.received_at > last_at:
            last_at = r.received_at

    responded_phone_set = {r.phone for r in responses if r.phone}
    total_sms_subscribers = (await db.scalar(
        select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
        )
    )) or 0
    non_responders = max(0, total_sms_subscribers - len(responded_phone_set))

    return AlertResponseSummary(
        alert_id=alert_id,
        total_sent=total_sent,
        total_responses=len(responses),
        response_counts=response_counts,
        non_responder_count=non_responders,
        first_response_at=first_at,
        last_response_at=last_at,
    )


@admin_router.get("/{alert_id}/responses/detail", response_model=list[AlertResponseRead])
async def get_response_detail(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertResponse)
        .where(AlertResponse.alert_id == alert_id)
        .order_by(AlertResponse.received_at.desc())
    )
    return result.scalars().all()


@admin_router.get("/{alert_id}/non-responders", response_model=list[SubscriberRead])
async def get_non_responders(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    responded_phones = (await db.execute(
        select(AlertResponse.phone).where(
            AlertResponse.alert_id == alert_id,
            AlertResponse.phone.isnot(None),
        )
    )).scalars().all()
    responded_set = set(responded_phones)

    all_sms = (await db.execute(
        select(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
        )
    )).scalars().all()

    return [s for s in all_sms if s.phone not in responded_set]


@admin_router.get("/{alert_id}/checkin-status", response_model=CheckInStatus)
async def get_checkin_status(alert_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    responses = (await db.execute(
        select(AlertResponse).where(AlertResponse.alert_id == alert_id)
    )).scalars().all()

    safe_count = 0
    help_count = 0
    help_details = []
    for r in responses:
        text_upper = r.response_text.upper().strip()
        if text_upper in ("SAFE", "1"):
            safe_count += 1
        elif text_upper in ("HELP", "2"):
            help_count += 1
            help_details.append(r)

    total_sms = (await db.scalar(
        select(func.count()).select_from(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
        )
    )) or 0

    responded_phones = {r.phone for r in responses if r.phone}
    no_response = max(0, total_sms - len(responded_phones))

    return CheckInStatus(
        alert_id=alert_id,
        total_subscribers=total_sms,
        responded_safe=safe_count,
        responded_help=help_count,
        no_response=no_response,
        help_details=[AlertResponseRead.model_validate(d) for d in help_details],
    )


@admin_router.post("/{alert_id}/resend-non-responders", response_model=AlertSendResult)
async def resend_to_non_responders(
    alert_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    alert = await db.get(AlertLog, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")

    responded_phones = set((await db.execute(
        select(AlertResponse.phone).where(
            AlertResponse.alert_id == alert_id,
            AlertResponse.phone.isnot(None),
        )
    )).scalars().all())

    all_sms = (await db.execute(
        select(AlertSubscriber).where(
            AlertSubscriber.phone.isnot(None),
            AlertSubscriber.sms_enabled.is_(True),
        )
    )).scalars().all()

    non_responders = [s for s in all_sms if s.phone not in responded_phones]
    if not non_responders:
        return AlertSendResult(alert_id=alert_id, emails_sent=0, sms_sent=0)

    log_entry = AlertLog(
        category=alert.category,
        subject=f"REMINDER: {alert.subject}",
        body_text=alert.body_text,
        body_sms=alert.body_sms,
        sent_by=user.email,
        status="active",
        response_options=alert.response_options,
        is_checkin=alert.is_checkin,
    )
    db.add(log_entry)
    await db.flush()
    await db.refresh(log_entry)

    channel_results = await dispatch_alert(
        log_entry.id, db,
        channels=["sms"],
        test_subscribers=non_responders,
    )

    await db.refresh(log_entry)
    return AlertSendResult(
        alert_id=log_entry.id,
        emails_sent=0,
        sms_sent=log_entry.sms_count,
        channel_results=channel_results,
    )


# ---------------------------------------------------------------------------
# Admin: Subscriber Groups
# ---------------------------------------------------------------------------

@admin_router.get("/groups", response_model=list[SubscriberGroupRead])
async def list_groups(db: AsyncSession = Depends(get_db)):
    groups = (await db.execute(
        select(SubscriberGroup).order_by(SubscriberGroup.name)
    )).scalars().all()

    result = []
    for g in groups:
        count = (await db.scalar(
            select(func.count()).select_from(subscriber_group_members).where(
                subscriber_group_members.c.group_id == g.id
            )
        )) or 0
        read = SubscriberGroupRead.model_validate(g)
        read.member_count = count
        result.append(read)
    return result


@admin_router.get("/groups/{group_id}", response_model=SubscriberGroupRead)
async def get_group(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    group = await db.get(SubscriberGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    count = (await db.scalar(
        select(func.count()).select_from(subscriber_group_members).where(
            subscriber_group_members.c.group_id == group_id
        )
    )) or 0
    read = SubscriberGroupRead.model_validate(group)
    read.member_count = count
    return read


@admin_router.post("/groups", response_model=SubscriberGroupRead, status_code=201)
async def create_group(data: SubscriberGroupCreate, db: AsyncSession = Depends(get_db)):
    group = SubscriberGroup(
        name=data.name,
        description=data.description,
        group_type=data.group_type,
    )
    db.add(group)
    await db.flush()
    await db.refresh(group)
    read = SubscriberGroupRead.model_validate(group)
    read.member_count = 0
    return read


@admin_router.put("/groups/{group_id}", response_model=SubscriberGroupRead)
async def update_group(
    group_id: uuid.UUID,
    data: SubscriberGroupUpdate,
    db: AsyncSession = Depends(get_db),
):
    group = await db.get(SubscriberGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(group, field, value)
    await db.flush()
    await db.refresh(group)
    count = (await db.scalar(
        select(func.count()).select_from(subscriber_group_members).where(
            subscriber_group_members.c.group_id == group_id
        )
    )) or 0
    read = SubscriberGroupRead.model_validate(group)
    read.member_count = count
    return read


@admin_router.delete("/groups/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    group = await db.get(SubscriberGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    await db.delete(group)
    await db.flush()


@admin_router.get("/groups/{group_id}/members", response_model=list[SubscriberRead])
async def list_group_members(group_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AlertSubscriber)
        .join(subscriber_group_members, AlertSubscriber.id == subscriber_group_members.c.subscriber_id)
        .where(subscriber_group_members.c.group_id == group_id)
        .order_by(AlertSubscriber.name)
    )
    return result.scalars().all()


@admin_router.post("/groups/{group_id}/members")
async def add_group_members(
    group_id: uuid.UUID,
    data: GroupMembersBatch,
    db: AsyncSession = Depends(get_db),
):
    group = await db.get(SubscriberGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")

    existing = set((await db.execute(
        select(subscriber_group_members.c.subscriber_id).where(
            subscriber_group_members.c.group_id == group_id,
            subscriber_group_members.c.subscriber_id.in_(data.subscriber_ids),
        )
    )).scalars().all())

    added = 0
    for sid in data.subscriber_ids:
        if sid not in existing:
            await db.execute(
                subscriber_group_members.insert().values(subscriber_id=sid, group_id=group_id)
            )
            added += 1
    await db.flush()
    return {"added": added}


@admin_router.delete("/groups/{group_id}/members")
async def remove_group_members(
    group_id: uuid.UUID,
    data: GroupMembersBatch,
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import delete as sa_delete
    result = await db.execute(
        sa_delete(subscriber_group_members).where(
            subscriber_group_members.c.group_id == group_id,
            subscriber_group_members.c.subscriber_id.in_(data.subscriber_ids),
        )
    )
    await db.flush()
    return {"removed": result.rowcount}


# ---------------------------------------------------------------------------
# Admin: Alert Scenarios
# ---------------------------------------------------------------------------

@admin_router.get("/scenarios", response_model=list[AlertScenarioRead])
async def list_scenarios(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AlertScenario).order_by(AlertScenario.name))
    return result.scalars().all()


@admin_router.get("/scenarios/running", response_model=list[RunningScenario])
async def get_running_scenarios():
    from ..services.scenario_runner import get_running
    return get_running()


@admin_router.post("/scenarios/running/{task_id}/abort")
async def abort_running_scenario(task_id: str):
    from ..services.scenario_runner import abort_scenario
    if not abort_scenario(task_id):
        raise HTTPException(404, "Running scenario not found")
    return {"status": "aborted"}


@admin_router.get("/scenarios/{scenario_id}", response_model=AlertScenarioRead)
async def get_scenario(scenario_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    scenario = await db.get(AlertScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    return scenario


@admin_router.post("/scenarios", response_model=AlertScenarioRead, status_code=201)
async def create_scenario(
    data: AlertScenarioCreate,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    scenario = AlertScenario(
        name=data.name,
        description=data.description,
        steps=[s.model_dump() for s in data.steps],
        created_by=user.email,
    )
    db.add(scenario)
    await db.flush()
    await db.refresh(scenario)
    return scenario


@admin_router.put("/scenarios/{scenario_id}", response_model=AlertScenarioRead)
async def update_scenario(
    scenario_id: uuid.UUID,
    data: AlertScenarioUpdate,
    db: AsyncSession = Depends(get_db),
):
    scenario = await db.get(AlertScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    if data.name is not None:
        scenario.name = data.name
    if data.description is not None:
        scenario.description = data.description
    if data.steps is not None:
        scenario.steps = [s.model_dump() for s in data.steps]
    await db.flush()
    await db.refresh(scenario)
    return scenario


@admin_router.delete("/scenarios/{scenario_id}", status_code=204)
async def delete_scenario(scenario_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    scenario = await db.get(AlertScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")
    await db.delete(scenario)
    await db.flush()


@admin_router.post("/scenarios/{scenario_id}/run")
async def run_scenario_endpoint(
    scenario_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(get_current_user),
):
    scenario = await db.get(AlertScenario, scenario_id)
    if not scenario:
        raise HTTPException(404, "Scenario not found")

    from ..services.scenario_runner import run_scenario
    task_id = run_scenario(scenario, user.email)
    return {"task_id": task_id}


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
