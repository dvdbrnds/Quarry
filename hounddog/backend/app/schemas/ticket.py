import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TicketCreate(BaseModel):
    plate: str
    permit_id: uuid.UUID | None = None
    lot: str = ""
    zone: str | None = None
    violation_type: str = "no_permit"
    fine_amount: Decimal = Decimal("50.00")
    photo_url: str | None = None
    officer_id: str = ""


class TicketUpdate(BaseModel):
    status: str | None = None
    fine_amount: Decimal | None = None
    photo_url: str | None = None
    lot: str | None = None
    zone: str | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate: str
    permit_id: uuid.UUID | None = None
    lot: str
    zone: str | None = None
    violation_type: str
    fine_amount: Decimal
    photo_url: str | None = None
    officer_id: str
    issued_at: datetime
    status: str
    appeal_note: str | None = None
    appeal_decision: str | None = None
    appeal_decided_by: str | None = None
    created_at: datetime
    updated_at: datetime


class AppealRequest(BaseModel):
    note: str


class AppealDecision(BaseModel):
    decision: str  # approved | denied
    decided_by: str


class TicketPipeline(BaseModel):
    issued: int = 0
    pending_payment: int = 0
    paid: int = 0
    appealed: int = 0
    escalated: int = 0
    voided: int = 0
    total: int = 0


class TicketList(BaseModel):
    items: list[TicketRead]
    total: int
    page: int
    page_size: int
