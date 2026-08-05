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
    response_options: list[str] | None = None
    group_ids: list[uuid.UUID] | None = None
    is_checkin: bool = False
    scheduled_for: datetime | None = None
    recurrence_rule: str | None = None


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
    response_options: list[str] | None = None
    is_checkin: bool = False
    target_group_ids: list[str] | None = None
    scheduled_for: datetime | None = None
    recurrence_rule: str | None = None
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


class ChannelSettingsField(BaseModel):
    key: str
    label: str
    type: str
    required: bool = False


class ChannelConfigRead(BaseModel):
    name: str
    enabled: bool
    configured: bool
    emergency_only: bool
    settings: dict = {}
    categories: list[str] = []
    settings_schema: list[ChannelSettingsField] = []


class ChannelConfigUpdate(BaseModel):
    enabled: bool | None = None
    settings: dict | None = None
    categories: list[str] | None = None


# --- Alert Template schemas ---


class AlertTemplateCreate(BaseModel):
    name: str
    category: str
    subject: str
    body_text: str = ""
    body_sms: str = ""
    is_default: bool = False


class AlertTemplateUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    subject: str | None = None
    body_text: str | None = None
    body_sms: str | None = None
    is_default: bool | None = None


class AlertTemplateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    category: str
    subject: str
    body_text: str
    body_sms: str
    created_by: str
    is_default: bool
    created_at: datetime
    updated_at: datetime


# --- Alert Response schemas (two-way SMS) ---


class AlertResponseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    alert_id: uuid.UUID
    subscriber_id: uuid.UUID | None
    phone: str | None
    channel: str
    response_text: str
    received_at: datetime


class AlertResponseSummary(BaseModel):
    alert_id: uuid.UUID
    total_sent: int
    total_responses: int
    response_counts: dict[str, int] = {}
    non_responder_count: int
    first_response_at: datetime | None = None
    last_response_at: datetime | None = None


class CheckInStatus(BaseModel):
    alert_id: uuid.UUID
    total_subscribers: int
    responded_safe: int
    responded_help: int
    no_response: int
    help_details: list[AlertResponseRead] = []


# --- Subscriber Group schemas ---


class SubscriberGroupCreate(BaseModel):
    name: str
    description: str = ""
    group_type: str = "custom"


class SubscriberGroupUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    group_type: str | None = None


class SubscriberGroupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    group_type: str
    member_count: int = 0
    created_at: datetime
    updated_at: datetime


class GroupMembersBatch(BaseModel):
    subscriber_ids: list[uuid.UUID]


# --- Alert Scenario schemas ---


class ScenarioStep(BaseModel):
    action: str
    template_id: uuid.UUID | None = None
    group_ids: list[uuid.UUID] | None = None
    channels: list[str] | None = None
    delay_seconds: int = 0


class AlertScenarioCreate(BaseModel):
    name: str
    description: str = ""
    steps: list[ScenarioStep]


class AlertScenarioUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    steps: list[ScenarioStep] | None = None


class AlertScenarioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    steps: list[dict]
    created_by: str | None
    created_at: datetime
    updated_at: datetime


class RunningScenario(BaseModel):
    task_id: str
    scenario_id: uuid.UUID
    scenario_name: str
    current_step: int
    total_steps: int
    started_at: datetime
    started_by: str


# --- Analytics / Reporting schemas ---


class AlertDeliverySummary(BaseModel):
    total_alerts: int = 0
    total_emails: int = 0
    total_sms: int = 0
    avg_channels_per_alert: float = 0.0
    by_category: dict[str, int] = {}
    by_month: list[dict] = []


class ChannelDeliveryStats(BaseModel):
    channel: str
    total_sent: int = 0
    total_failed: int = 0
    success_rate: float = 0.0


class ResponseRateStats(BaseModel):
    alert_id: uuid.UUID
    subject: str
    category: str
    total_subscribers: int = 0
    total_responses: int = 0
    response_rate: float = 0.0
    checkin_safe: int = 0
    checkin_help: int = 0
    sent_at: datetime


class AlertAnalyticsDashboard(BaseModel):
    summary: AlertDeliverySummary
    channel_stats: list[ChannelDeliveryStats]
    recent_response_rates: list[ResponseRateStats]


class AfterActionReport(BaseModel):
    alert_id: uuid.UUID
    subject: str
    category: str
    sent_by: str
    sent_at: datetime
    cleared_at: datetime | None
    channel_results: dict | None
    total_subscribers: int
    total_responses: int
    response_rate: float
    response_breakdown: dict[str, int]
    timeline: list[dict]


class WeatherAlertConfig(BaseModel):
    enabled: bool
    zone_id: str
    poll_interval_seconds: int
    event_mappings: list[dict]


class WeatherAlertConfigUpdate(BaseModel):
    enabled: bool | None = None
    zone_id: str | None = None
    poll_interval_seconds: int | None = None
    event_mappings: list[dict] | None = None


class SisSubscriberSyncConfig(BaseModel):
    enabled: bool
    sync_url: str
    last_sync_at: datetime | None = None
    total_synced: int = 0


class SisSubscriberSyncConfigUpdate(BaseModel):
    enabled: bool | None = None
    sync_url: str | None = None
