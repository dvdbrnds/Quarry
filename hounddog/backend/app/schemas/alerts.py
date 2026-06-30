import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


# --- Alert Subscriber schemas ---


class SubscriberCreate(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    sms_enabled: bool = True
    email_enabled: bool = True
    categories: list[str] = []
    source: str = "admin"


class SubscriberUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    sms_enabled: bool | None = None
    email_enabled: bool | None = None
    categories: list[str] | None = None


class SubscriberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    email: str | None
    phone: str | None
    sms_enabled: bool
    email_enabled: bool
    categories: list[str]
    unsubscribe_token: str
    source: str
    created_at: datetime
    updated_at: datetime


class PublicSubscribeRequest(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    categories: list[str] = []


class PublicSubscribeResponse(BaseModel):
    message: str
    subscriber_id: uuid.UUID


# --- Alert Send / Preview schemas ---

ALERT_CATEGORIES = ["emergency", "weather", "campus_closing", "parking", "general"]


class AlertSendRequest(BaseModel):
    category: str
    subject: str
    body_text: str = ""
    body_sms: str = ""
    send_email: bool = True
    send_sms: bool = True


class AlertSendPreview(BaseModel):
    category: str
    email_recipient_count: int
    sms_recipient_count: int
    total_subscribers: int


class AlertSendResult(BaseModel):
    emails_sent: int
    sms_sent: int
    alert_id: uuid.UUID


# --- Alert History schemas ---


class AlertLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    subject: str
    body_text: str
    body_sms: str
    sent_by: str
    email_count: int
    sms_count: int
    sent_at: datetime
