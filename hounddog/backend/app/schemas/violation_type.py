import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ViolationTypeBase(BaseModel):
    code: str
    label: str
    category: str = "parking"
    fine_first: Decimal = Decimal("35.00")
    fine_second: Decimal | None = None
    fine_third_plus: Decimal | None = None
    is_active: bool = True
    sort_order: int = 0


class ViolationTypeCreate(ViolationTypeBase):
    pass


class ViolationTypeUpdate(BaseModel):
    code: str | None = None
    label: str | None = None
    category: str | None = None
    fine_first: Decimal | None = None
    fine_second: Decimal | None = None
    fine_third_plus: Decimal | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class ViolationTypeRead(ViolationTypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ViolationTypeImportRow(BaseModel):
    code: str
    label: str
    category: str = "parking"
    fine_first: Decimal = Decimal("35.00")
    fine_second: Decimal | None = None
    fine_third_plus: Decimal | None = None
    sort_order: int = 0


class ViolationTypeImportPayload(BaseModel):
    violation_types: list[ViolationTypeImportRow]


class ViolationTypeImportResult(BaseModel):
    created: int
    updated: int
    errors: list[str] = []
