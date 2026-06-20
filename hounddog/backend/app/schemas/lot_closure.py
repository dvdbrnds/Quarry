import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LotClosureCreate(BaseModel):
    lot_id: uuid.UUID
    reason: str = ""
    closes_at: datetime
    reopens_at: datetime | None = None
    is_immediate: bool = False


class LotClosureUpdate(BaseModel):
    reason: str | None = None
    closes_at: datetime | None = None
    reopens_at: datetime | None = None
    status: str | None = None


class LotClosureRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID
    reason: str
    closes_at: datetime
    reopens_at: datetime | None
    is_immediate: bool
    notification_sent: bool
    reopen_notification_sent: bool
    created_by: str
    status: str
    created_at: datetime
    updated_at: datetime


class LotClosureWithLotName(LotClosureRead):
    lot_name: str = ""


class CloseLotNow(BaseModel):
    reason: str = ""
    reopens_at: datetime | None = None
    recipients: list[str] = []
