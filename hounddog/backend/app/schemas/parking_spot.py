import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SpotBase(BaseModel):
    number: int
    label: str | None = None
    sensor_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class SpotCreate(SpotBase):
    pass


class SpotUpdate(BaseModel):
    number: int | None = None
    label: str | None = None
    sensor_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None


class SpotRead(SpotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lot_id: uuid.UUID
    created_at: datetime
    updated_at: datetime
