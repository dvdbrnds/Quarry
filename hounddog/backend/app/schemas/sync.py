from datetime import datetime

from pydantic import BaseModel

from .permit import PermitRead
from .lot import LotRead


class SyncPermitsResponse(BaseModel):
    permits: list[PermitRead]
    server_timestamp: datetime
    full_sync: bool = False


class SyncLotsResponse(BaseModel):
    lots: list[LotRead]
    server_timestamp: datetime
    full_sync: bool = False


class SyncStatusResponse(BaseModel):
    status: str = "ok"
    server_time: datetime
    permit_count: int
    lot_count: int
    device_count: int


class TicketUpload(BaseModel):
    plate: str
    lot: str = ""
    violation_type: str = ""
    confidence: float = 0.0
    camera_name: str = ""
    timestamp: datetime
    photo_base64: str | None = None
