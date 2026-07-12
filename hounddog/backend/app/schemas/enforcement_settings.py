from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


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
    updated_at: datetime
    updated_by: str


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
