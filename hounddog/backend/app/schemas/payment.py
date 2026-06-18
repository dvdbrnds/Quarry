import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID
    amount: Decimal
    method: str
    stripe_payment_id: str | None = None
    bursar_reference: str | None = None
    paid_at: datetime
    created_at: datetime


class CheckoutRequest(BaseModel):
    ticket_id: uuid.UUID
    success_url: str = "/pay/success"
    cancel_url: str = "/pay"


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


class BursarImportRow(BaseModel):
    ticket_id: str
    amount: Decimal
    reference: str
    paid_date: str | None = None


class BursarImportPayload(BaseModel):
    payments: list[BursarImportRow]


class BursarImportResult(BaseModel):
    matched: int
    unmatched: int
    errors: list[str] = []


class TicketLookup(BaseModel):
    """Public-facing ticket info for the payment portal (no sensitive fields)."""
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plate: str
    lot: str
    violation_type: str
    fine_amount: Decimal
    status: str
    issued_at: datetime


class TicketLookupList(BaseModel):
    tickets: list[TicketLookup]


class RevenueReport(BaseModel):
    total_fines_issued: Decimal
    total_collected: Decimal
    total_outstanding: Decimal
    collection_rate: float
    by_method: dict[str, Decimal]
    by_status: dict[str, int]
