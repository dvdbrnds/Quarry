import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_role
from ..config import settings
from ..database import get_db
from ..models.lot import ParkingLot
from ..models.message_template import MessageTemplate
from ..models.notification_preference import NotificationPreference
from ..models.permit import Permit
from ..schemas.messaging import (
    MessageTemplateCreate,
    MessageTemplateRead,
    MessageTemplateUpdate,
    PermitNotificationStatus,
    SendMessagePreview,
    SendMessageRequest,
    SendMessageResult,
)
from ..services.email import send_email
from ..services.sms import send_bulk_sms

router = APIRouter(dependencies=[Depends(require_role("admin", "staff"))])


def _render_template(text: str, context: dict[str, str]) -> str:
    """Replace {placeholder} tokens with context values."""
    result = text
    for key, value in context.items():
        result = result.replace(f"{{{key}}}", value or "")
    return result


async def _build_context(
    lot: ParkingLot | None, reason: str = "", closes_at: str = "", reopens_at: str = ""
) -> dict[str, str]:
    return {
        "lot_name": lot.name if lot else "All Lots",
        "reason": reason,
        "closes_at": closes_at or datetime.now(timezone.utc).strftime("%b %d, %Y %I:%M %p %Z"),
        "reopens_at": reopens_at or "TBD",
        "school": settings.school_name or "Campus",
    }


# --- Template CRUD ---


@router.get("/templates", response_model=list[MessageTemplateRead])
async def list_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(MessageTemplate).order_by(MessageTemplate.reason_code)
    )
    return result.scalars().all()


@router.post("/templates", response_model=MessageTemplateRead, status_code=201)
async def create_template(data: MessageTemplateCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(
        select(MessageTemplate).where(MessageTemplate.reason_code == data.reason_code)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Template with reason_code '{data.reason_code}' already exists")

    template = MessageTemplate(**data.model_dump())
    db.add(template)
    await db.flush()
    await db.refresh(template)
    return template


@router.put("/templates/{template_id}", response_model=MessageTemplateRead)
async def update_template(
    template_id: uuid.UUID,
    data: MessageTemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    template = await db.get(MessageTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(template, field, value)

    await db.flush()
    await db.refresh(template)
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    template = await db.get(MessageTemplate, template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    await db.delete(template)
    await db.flush()


# --- Send + Preview ---


async def _get_recipients(
    lot_id: uuid.UUID | None, is_emergency: bool, db: AsyncSession
) -> tuple[list[str], list[str]]:
    """Return (email_list, sms_list) for a given lot or all lots."""
    q = select(Permit.email, Permit.phone, Permit.sms_opt_in).where(
        Permit.status == "active",
        Permit.deleted_at.is_(None),
    )
    if lot_id:
        lot = await db.get(ParkingLot, lot_id)
        if lot:
            q = q.where(Permit.lot_assignment == lot.name)

    rows = (await db.execute(q)).all()

    emails = [r.email for r in rows if r.email]
    if is_emergency:
        phones = [r.phone for r in rows if r.phone]
    else:
        phones = [r.phone for r in rows if r.phone and r.sms_opt_in]

    return emails, phones


@router.get("/send/preview", response_model=SendMessagePreview)
async def preview_send(
    template_id: uuid.UUID | None = None,
    lot_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    is_emergency = False
    rendered_subject = ""
    rendered_sms = ""

    lot = await db.get(ParkingLot, lot_id) if lot_id else None
    context = await _build_context(lot)

    if template_id:
        template = await db.get(MessageTemplate, template_id)
        if template:
            is_emergency = template.is_emergency
            rendered_subject = _render_template(template.email_subject, context)
            rendered_sms = _render_template(template.sms_body, context)

    emails, sms_opted_in = await _get_recipients(lot_id, False, db)
    _, sms_all = await _get_recipients(lot_id, True, db)

    return SendMessagePreview(
        email_recipient_count=len(emails),
        sms_recipient_count=len(sms_all) if is_emergency else len(sms_opted_in),
        sms_opted_in_count=len(sms_opted_in),
        sms_total_with_phone=len(sms_all),
        is_emergency=is_emergency,
        rendered_email_subject=rendered_subject,
        rendered_sms_body=rendered_sms,
    )


@router.post("/send", response_model=SendMessageResult)
async def send_message(data: SendMessageRequest, db: AsyncSession = Depends(get_db)):
    is_emergency = False
    lot = await db.get(ParkingLot, data.lot_id) if data.lot_id else None
    context = await _build_context(lot)

    email_subject = data.custom_email_subject or ""
    email_body = data.custom_email_body or ""
    sms_body = data.custom_sms_body or ""

    if data.template_id:
        template = await db.get(MessageTemplate, data.template_id)
        if not template:
            raise HTTPException(404, "Template not found")
        is_emergency = template.is_emergency
        if not data.custom_email_subject:
            email_subject = _render_template(template.email_subject, context)
        if not data.custom_email_body:
            email_body = _render_template(template.email_body, context)
        if not data.custom_sms_body:
            sms_body = _render_template(template.sms_body, context)

    emails_sent = 0
    sms_sent = 0

    if data.send_email:
        email_recipients, _ = await _get_recipients(data.lot_id, is_emergency, db)
        email_recipients.extend(data.extra_emails)
        email_recipients = list(set(email_recipients))
        if email_recipients and email_subject:
            success = await send_email(email_recipients, email_subject, email_body)
            emails_sent = len(email_recipients) if success else 0

    if data.send_sms and sms_body:
        _, sms_recipients = await _get_recipients(data.lot_id, is_emergency, db)
        sms_recipients.extend(data.extra_phones)
        sms_recipients = list(set(sms_recipients))
        if sms_recipients:
            sms_sent = send_bulk_sms(sms_recipients, sms_body)

    return SendMessageResult(emails_sent=emails_sent, sms_sent=sms_sent)


# --- Notification Preferences (admin view) ---


@router.get("/preferences", response_model=list[PermitNotificationStatus])
async def list_preferences(
    lot: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    q = select(Permit, NotificationPreference).outerjoin(
        NotificationPreference, NotificationPreference.permit_id == Permit.id
    ).where(
        Permit.status == "active",
        Permit.deleted_at.is_(None),
    )
    if lot:
        q = q.where(Permit.lot_assignment == lot)

    q = q.order_by(Permit.name)
    rows = (await db.execute(q)).all()

    result = []
    for permit, pref in rows:
        token = pref.opt_out_token if pref else ""
        pref_url = f"{settings.public_url}/notifications/{token}" if token else ""
        result.append(PermitNotificationStatus(
            permit_id=permit.id,
            name=permit.name,
            lot_assignment=permit.lot_assignment,
            email=permit.email,
            phone=permit.phone,
            sms_opt_in=permit.sms_opt_in,
            preference_url=pref_url,
        ))

    return result
