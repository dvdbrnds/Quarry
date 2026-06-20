import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PermitTypeBase(BaseModel):
    code: str
    label: str
    eligible: str = ""
    price: Decimal = Decimal("0.00")
    max_capacity: int = 0
    valid_days: int = 365
    lot_assignments: list[str] = []
    time_restriction: str | None = None
    is_purchasable_online: bool = False
    is_active: bool = True
    sort_order: int = 0


class PermitTypeCreate(PermitTypeBase):
    pass


class PermitTypeUpdate(BaseModel):
    code: str | None = None
    label: str | None = None
    eligible: str | None = None
    price: Decimal | None = None
    max_capacity: int | None = None
    valid_days: int | None = None
    lot_assignments: list[str] | None = None
    time_restriction: str | None = None
    is_purchasable_online: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class PermitTypeRead(PermitTypeBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class PermitTypeWithCount(PermitTypeRead):
    active_count: int = 0
    remaining: int = 0


class PermitTypeImportRow(BaseModel):
    code: str
    label: str
    eligible: str = ""
    price: Decimal = Decimal("0.00")
    max_capacity: int = 0
    valid_days: int = 365
    lot_assignments: list[str] = []
    time_restriction: str | None = None
    is_purchasable_online: bool = False
    sort_order: int = 0


class PermitTypeImportPayload(BaseModel):
    permit_types: list[PermitTypeImportRow]


class PermitTypeImportResult(BaseModel):
    created: int
    updated: int
    errors: list[str] = []
