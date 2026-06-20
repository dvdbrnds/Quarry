import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AcademicSeasonBase(BaseModel):
    code: str
    label: str
    start_date: date
    end_date: date
    is_default: bool = False


class AcademicSeasonCreate(AcademicSeasonBase):
    pass


class AcademicSeasonUpdate(BaseModel):
    code: str | None = None
    label: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_default: bool | None = None


class AcademicSeasonRead(AcademicSeasonBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ActiveSeasonResponse(BaseModel):
    season: AcademicSeasonRead | None = None
    fallback: str = "No active season — using default rules"
