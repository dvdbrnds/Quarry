import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, computed_field

from ..config import settings


class TicketCreate(BaseModel):
    plate: str
    permit_id: uuid.UUID | None = None
    lot: str = ""
    zone: str | None = None
    violation_type: str = "no_permit"
    violation_type_id: uuid.UUID | None = None
    fine_amount: Decimal = Decimal("50.00")
    photo_url: str | None = None
    officer_id: str = ""
    ticket_category: str = "parking"
    location_lat: float | None = None
    location_lng: float | None = None
    location_text: str | None = None
    vehicle_description: str | None = None
    officer_notes: str | None = None
    driver_name: str | None = None
    driver_license: str | None = None


class TicketUpdate(BaseModel):
    status: str | None = None
    fine_amount: Decimal | None = None
    photo_url: str | None = None
    lot: str | None = None
    zone: str | None = None
    officer_notes: str | None = None
    vehicle_description: str | None = None
    driver_name: str | None = None
    driver_license: str | None = None


class TicketRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate: str
    permit_id: uuid.UUID | None = None
    lot: str
    zone: str | None = None
    violation_type: str
    violation_type_id: uuid.UUID | None = None
    fine_amount: Decimal
    photo_url: str | None = None
    officer_id: str
    issued_at: datetime
    status: str
    ticket_category: str = "parking"
    offense_number: int = 1
    location_lat: float | None = None
    location_lng: float | None = None
    location_text: str | None = None
    vehicle_description: str | None = None
    officer_notes: str | None = None
    driver_name: str | None = None
    driver_license: str | None = None
    appeal_note: str | None = None
    appeal_decision: str | None = None
    appeal_decided_by: str | None = None
    dispute_name: str | None = None
    dispute_email: str | None = None
    dispute_phone: str | None = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def payment_url(self) -> str:
        return f"{settings.public_url}/pay?ticket={self.id}"


class AppealRequest(BaseModel):
    note: str


class AppealDecision(BaseModel):
    decision: str
    decided_by: str


class TicketPipeline(BaseModel):
    issued: int = 0
    pending_payment: int = 0
    paid: int = 0
    appealed: int = 0
    escalated: int = 0
    voided: int = 0
    resolved_permit: int = 0
    total: int = 0


class TicketList(BaseModel):
    items: list[TicketRead]
    total: int
    page: int
    page_size: int
