import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ResidentPlateCreate(BaseModel):
    plate: str
    plate_state: str = ""
    street_id: uuid.UUID | None = None
    notes: str | None = None


class ResidentPlateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate: str
    plate_state: str
    street_id: uuid.UUID | None
    notes: str | None
    added_by: str
    created_at: datetime
