import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DeviceCreate(BaseModel):
    name: str
    device_type: str = "ipad"


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    api_key: str
    device_type: str
    last_seen: datetime | None = None
    created_at: datetime
