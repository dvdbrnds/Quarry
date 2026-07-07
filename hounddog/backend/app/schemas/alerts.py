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
    configured_channels: list[str] = []


class AlertSendResult(BaseModel):
    alert_id: uuid.UUID
    emails_sent: int
    sms_sent: int
    channel_results: dict[str, dict] = {}


class AlertTestRequest(BaseModel):
    channel: str


class AlertTestSendRequest(BaseModel):
    channel: str
    category: str = "general"
    subject: str = "[TEST] Alert channel test"
    body_text: str = "This is an automated test of the alert channel. No action required."
    body_sms: str = "TEST: Alert channel test. No action required."
    test_email: str | None = None
    test_phone: str | None = None
    screen_id: str | None = None


class AlertTestSendResult(BaseModel):
    alert_id: uuid.UUID
    channel: str
    sent: int = 0
    failed: int = 0
    error: str | None = None
    status: str = "test"


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
    status: str
    cleared_at: datetime | None = None
    cleared_by: str | None = None
    channel_results: dict | None = None
    sent_at: datetime


# --- Active Alert (public) ---


class ActiveAlertRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category: str
    subject: str
    body_text: str
    sent_at: datetime
    status: str


# --- Channel config ---


class AlertChannelRead(BaseModel):
    name: str
    configured: bool
    emergency_only: bool
