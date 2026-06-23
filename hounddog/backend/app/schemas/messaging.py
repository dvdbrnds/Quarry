import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MessageTemplateCreate(BaseModel):
    reason_code: str
    reason_label: str
    is_emergency: bool = False
    email_subject: str = ""
    email_body: str = ""
    sms_body: str = ""
    is_active: bool = True


class MessageTemplateUpdate(BaseModel):
    reason_label: str | None = None
    is_emergency: bool | None = None
    email_subject: str | None = None
    email_body: str | None = None
    sms_body: str | None = None
    is_active: bool | None = None


class MessageTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    reason_code: str
    reason_label: str
    is_emergency: bool
    email_subject: str
    email_body: str
    sms_body: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


class SendMessageRequest(BaseModel):
    template_id: uuid.UUID | None = None
    lot_id: uuid.UUID | None = None
    custom_email_subject: str | None = None
    custom_email_body: str | None = None
    custom_sms_body: str | None = None
    send_email: bool = True
    send_sms: bool = True
    extra_emails: list[str] = []
    extra_phones: list[str] = []


class SendMessagePreview(BaseModel):
    email_recipient_count: int
    sms_recipient_count: int
    sms_opted_in_count: int
    sms_total_with_phone: int
    is_emergency: bool
    rendered_email_subject: str = ""
    rendered_sms_body: str = ""


class SendMessageResult(BaseModel):
    emails_sent: int
    sms_sent: int


class NotificationPreferenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    first_name: str
    phone: str | None
    sms_opt_in: bool
    email_always_on: bool = True


class NotificationPreferenceUpdate(BaseModel):
    sms_opt_in: bool
    phone: str | None = None


class PermitNotificationStatus(BaseModel):
    permit_id: uuid.UUID
    name: str
    lot_assignment: str
    email: str | None
    phone: str | None
    sms_opt_in: bool
    preference_url: str
