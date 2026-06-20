import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from .permit import PermitRead
from .lot import LotRead, LotZoneRead, SeasonSchedule
from .violation_type import ViolationTypeRead
from .academic_season import AcademicSeasonRead
from .enforcement_settings import EnforcementSettingsRead


class SyncPermitsResponse(BaseModel):
    permits: list[PermitRead]
    server_timestamp: datetime
    full_sync: bool = False


class SyncLotWithZones(LotRead):
    zones: list[LotZoneRead] = []


class SyncLotsResponse(BaseModel):
    lots: list[SyncLotWithZones]
    server_timestamp: datetime
    full_sync: bool = False


class SyncStatusResponse(BaseModel):
    status: str = "ok"
    server_time: datetime
    permit_count: int
    lot_count: int
    device_count: int


class SyncViolationTypesResponse(BaseModel):
    violation_types: list[ViolationTypeRead]
    server_timestamp: datetime


class SyncCalendarResponse(BaseModel):
    seasons: list[AcademicSeasonRead]
    active_season: AcademicSeasonRead | None = None
    server_timestamp: datetime


class SyncSettingsResponse(BaseModel):
    settings: EnforcementSettingsRead
    server_timestamp: datetime


class PushTokenRegister(BaseModel):
    token: str


class TicketUpload(BaseModel):
    plate: str
    lot: str = ""
    zone: str | None = None
    violation_type: str = ""
    ticket_category: str = "parking"
    fine_amount: Decimal | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    location_text: str | None = None
    vehicle_description: str | None = None
    officer_notes: str | None = None
    driver_name: str | None = None
    driver_license: str | None = None
    confidence: float = 0.0
    camera_name: str = ""
    timestamp: datetime
    photo_base64: str | None = None


class TicketUploadResponse(BaseModel):
    status: str = "accepted"
    ticket_id: uuid.UUID
    payment_url: str
    fine_amount: Decimal
    offense_number: int = 1
