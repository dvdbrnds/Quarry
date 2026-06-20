import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Coordinate(BaseModel):
    latitude: float
    longitude: float


class TimeRule(BaseModel):
    start: str
    end: str
    days: list[str] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    allowed_permit_types: list[str] = []
    label: str = ""


class SeasonSchedule(BaseModel):
    season: str
    label: str = ""
    rules: list[TimeRule] = []


class LotZoneBase(BaseModel):
    zone_type: str
    label: str
    space_count: int = 0
    boundary: list[Coordinate] = []
    fine_override: str | None = None
    is_premium: bool = False
    notes: str | None = None


class LotZoneCreate(LotZoneBase):
    pass


class LotZoneUpdate(BaseModel):
    zone_type: str | None = None
    label: str | None = None
    space_count: int | None = None
    boundary: list[Coordinate] | None = None
    fine_override: str | None = None
    is_premium: bool | None = None
    notes: str | None = None


class LotZoneRead(LotZoneBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class LotBase(BaseModel):
    name: str
    boundary: list[Coordinate] = []
    total_spaces: int = 0
    handicap_spaces: int = 0
    designation_code: str = ""
    designation_label: str = ""
    access_schedule: list[SeasonSchedule] = []
    is_snow_lot: bool = False
    notes: str | None = None


class LotCreate(LotBase):
    pass


class LotUpdate(BaseModel):
    name: str | None = None
    boundary: list[Coordinate] | None = None
    total_spaces: int | None = None
    handicap_spaces: int | None = None
    designation_code: str | None = None
    designation_label: str | None = None
    access_schedule: list[SeasonSchedule] | None = None
    is_snow_lot: bool | None = None
    notes: str | None = None


class LotRead(LotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class LotReadWithZones(LotRead):
    zones: list[LotZoneRead] = []
