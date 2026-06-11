import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class PermitBase(BaseModel):
    student_id: str = ""
    name: str
    plates: list[str] = []
    lot_assignment: str = ""
    permit_type: str = "student"
    beacon_id: str | None = None
    start_date: date = date.today()
    end_date: date | None = None
    status: str = "active"


class PermitCreate(PermitBase):
    pass


class PermitUpdate(BaseModel):
    student_id: str | None = None
    name: str | None = None
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


class PermitImportRow(BaseModel):
    plate_normalized: str
    plate_raw: str = ""
    plate_state: str = ""
    owner_name: str = ""
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
