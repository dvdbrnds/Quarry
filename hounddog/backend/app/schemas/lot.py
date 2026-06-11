import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class Coordinate(BaseModel):
    latitude: float
    longitude: float


class LotBase(BaseModel):
    name: str
    boundary: list[Coordinate] = []


class LotCreate(LotBase):
    pass


class LotUpdate(BaseModel):
    name: str | None = None
    boundary: list[Coordinate] | None = None


class LotRead(LotBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None
