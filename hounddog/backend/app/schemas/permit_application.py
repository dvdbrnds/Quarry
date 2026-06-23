import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ApplicationSubmit(BaseModel):
    permit_type_id: uuid.UUID
    plate: str
    student_name: str
    class_year: int
    phone: str | None = None


class ApplicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    student_sub: str
    student_email: str
    student_name: str
    class_year: int
    permit_type_id: uuid.UUID
    plate: str
    phone: str | None = None
    status: str
    lottery_rank: int | None = None
    waitlist_position: int | None = None
    offer_expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApplicationWithType(ApplicationRead):
    permit_type_label: str = ""
    permit_type_code: str = ""
    permit_type_price: Decimal = Decimal("0.00")
    lot_assignments: list[str] = []


class AvailablePermitType(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    eligible: str
    price: Decimal
    max_capacity: int
    remaining: int
    lot_assignments: list[str]
    valid_days: int
    application_closes_at: datetime | None = None
    requires_lottery: bool = False


class LotteryResult(BaseModel):
    selected: int
    waitlisted: int
    total_applicants: int


class ApplicationAdminRead(ApplicationRead):
    permit_type_code: str = ""
    permit_type_label: str = ""
