from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class EnforcementSettingsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    payment_due_days: int
    appeal_window_days: int
    academic_year_start_month: int
    academic_year_start_day: int
    escalation_threshold: int
    permit_fine_reduction: Decimal
    unpaid_blocks_registration: bool
    towing_enabled: bool
    towing_violation_codes: list[str]
    snow_emergency_active: bool
    conduct_officer_emails: str
    updated_at: datetime
    updated_by: str

    policy_effective_date: date | None = None
    legacy_resolution_deadline: date | None = None
    policy_reminder_day: int = 7
    policy_due_day: int = 10
    policy_late_fee_1_day: int = 11
    policy_late_fee_2_day: int = 31
    late_fee_1_amount: Decimal = Decimal("15.00")
    late_fee_2_amount: Decimal = Decimal("20.00")
    late_fee_cap: Decimal = Decimal("35.00")
    denied_appeal_grace_days: int = 10
    owner_notification_fee: Decimal = Decimal("25.00")
    policy_job_hour: int = 6
    barnacle_enabled: bool = False
    barnacle_env_enabled: bool = False
    barnacle_min_citations: int = 3
    barnacle_delinquent_days: int = 30
    barnacle_warning_wait_days: int = 10
    barnacle_warning_lookahead_days: int = 10
    barnacle_deployment_fee: Decimal = Decimal("100.00")
    removal_phone_daytime: str = ""
    removal_phone_after_hours: str = ""


class EnforcementSettingsUpdate(BaseModel):
    payment_due_days: int | None = None
    appeal_window_days: int | None = None
    academic_year_start_month: int | None = None
    academic_year_start_day: int | None = None
    escalation_threshold: int | None = None
    permit_fine_reduction: Decimal | None = None
    unpaid_blocks_registration: bool | None = None
    towing_enabled: bool | None = None
    towing_violation_codes: list[str] | None = None
    snow_emergency_active: bool | None = None
    conduct_officer_emails: str | None = None

    policy_effective_date: date | None = None
    legacy_resolution_deadline: date | None = None
    policy_reminder_day: int | None = Field(None, ge=1, le=365)
    policy_due_day: int | None = Field(None, ge=1, le=365)
    policy_late_fee_1_day: int | None = Field(None, ge=1, le=365)
    policy_late_fee_2_day: int | None = Field(None, ge=1, le=365)
    late_fee_1_amount: Decimal | None = Field(None, ge=0)
    late_fee_2_amount: Decimal | None = Field(None, ge=0)
    late_fee_cap: Decimal | None = Field(None, ge=0)
    denied_appeal_grace_days: int | None = Field(None, ge=0, le=365)
    owner_notification_fee: Decimal | None = Field(None, ge=0)
    policy_job_hour: int | None = Field(None, ge=0, le=23)
    barnacle_enabled: bool | None = None
    barnacle_min_citations: int | None = Field(None, ge=1, le=50)
    barnacle_delinquent_days: int | None = Field(None, ge=0, le=365)
    barnacle_warning_wait_days: int | None = Field(None, ge=0, le=365)
    barnacle_warning_lookahead_days: int | None = Field(None, ge=0, le=365)
    barnacle_deployment_fee: Decimal | None = Field(None, ge=0)
    removal_phone_daytime: str | None = Field(None, max_length=64)
    removal_phone_after_hours: str | None = Field(None, max_length=64)
