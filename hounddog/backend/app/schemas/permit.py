import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from ..services.timeutils import today_local


class PermitBase(BaseModel):
    permit_number: str | None = None
    student_id: str = ""
    name: str
    email: str | None = None
    phone: str = ""
    sms_opt_in: bool = False
    plates: list[str] = []
    lot_assignment: str = ""
    permit_type: str = "student"
    beacon_id: str | None = None
    start_date: date = Field(default_factory=today_local)
    end_date: date | None = None
    status: str = "active"


class PermitCreate(PermitBase):
    pass


class PermitUpdate(BaseModel):
    permit_number: str | None = None
    student_id: str | None = None
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    sms_opt_in: bool | None = None
    plates: list[str] | None = None
    lot_assignment: str | None = None
    permit_type: str | None = None
    beacon_id: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str | None = None


class PermitRead(PermitBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
    refund_id: str | None = None
    refund_amount: Decimal | None = None
    cancel_reason: str | None = None
    cancel_notes: str | None = None
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None


class PermitImportRow(BaseModel):
    plate_normalized: str
    plate_raw: str = ""
    plate_state: str = ""
    owner_name: str = ""
    email: str = ""
    permit_number: str = ""
    permit_type: str = "student"
    permit_status: str = "active"
    lot_zone: str = ""
    vehicle_description: str = ""
    issued_date: str | None = None
    expiration_date: str | None = None


class PermitImportPayload(BaseModel):
    permits: list[PermitImportRow]


class PermitImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int


class PermitList(BaseModel):
    items: list[PermitRead]
    total: int
    page: int
    page_size: int
