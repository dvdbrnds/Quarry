import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LotAccessInfo(BaseModel):
    name: str
    designation_code: str = ""
    is_time_restricted: bool = False
    restriction_label: str = ""


class ApplicationSubmit(BaseModel):
    permit_type_id: uuid.UUID
    plate: str
    plate_state: str = ""
    student_name: str
    class_year: int
    phone: str | None = None
    lot_preferences: list[str] = []
    sms_opt_in: bool = False


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_sub: str
    student_email: str
    student_name: str
    class_year: int
    permit_type_id: uuid.UUID
    plate: str
    plate_state: str = ""
    phone: str | None = None
    lot_preferences: list[str] = []
    assigned_lot: str | None = None
    status: str
    lottery_rank: int | None = None
    waitlist_position: int | None = None
    offer_expires_at: datetime | None = None
    is_test_entry: bool = False
    fee_exempt: bool = False
    created_at: datetime
    updated_at: datetime


class ApplicationWithType(ApplicationRead):
    permit_type_label: str = ""
    permit_type_code: str = ""
    permit_type_price: Decimal = Decimal("0.00")
    lot_assignments: list[str] = []
    lot_details: list[LotAccessInfo] = []
    waitlist_message: str | None = None
    permit_id: str | None = None
    current_plate: str | None = None
    last_plate_change: datetime | None = None
    next_swap_available: datetime | None = None
    can_swap: bool = False


class AvailablePermitType(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    eligible: str
    price: Decimal
    max_capacity: int
    remaining: int
    lot_assignments: list[str]
    lot_details: list[LotAccessInfo] = []
    valid_days: int
    min_class_year: int | None = None
    allow_multiple: bool = False
    application_closes_at: datetime | None = None
    requires_lottery: bool = False
    current_applicants: int | None = None
    approximate_odds: str | None = None


class LotteryResult(BaseModel):
    selected: int
    waitlisted: int
    total_applicants: int


class SimulateRequest(BaseModel):
    strategy: str | None = None
    capacity_override: int | None = None


class SimulatedAppResult(BaseModel):
    id: uuid.UUID
    student_name: str
    student_email: str
    class_year: int
    plate: str
    lot_preferences: list[str] = []
    assigned_lot: str | None = None
    rank: int


class SimulationResponse(BaseModel):
    selected: list[SimulatedAppResult]
    waitlisted: list[SimulatedAppResult]
    total_applicants: int
    spots_available: int
    strategy_used: str


class ActivityEventRead(BaseModel):
    id: uuid.UUID
    student_name: str
    old_status: str
    new_status: str
    timestamp: datetime


class ApplicationAdminRead(ApplicationRead):
    permit_type_code: str = ""
    permit_type_label: str = ""


class DirectPurchaseRequest(BaseModel):
    permit_type_id: uuid.UUID
    student_name: str
    plate: str
    plate_state: str
    class_year: int
    phone: str
    lot_preference: str | None = None
    sms_opt_in: bool = False
    coupon_code: str | None = None


class VehicleSwapRequest(BaseModel):
    permit_id: uuid.UUID
    new_plate: str
    new_plate_state: str = ""
