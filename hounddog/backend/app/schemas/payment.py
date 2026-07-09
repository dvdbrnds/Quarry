import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    amount: Decimal
    method: str
    stripe_payment_id: str | None = None
    bursar_reference: str | None = None
    payment_type: str | None = None
    payer_name: str | None = None
    payer_email: str | None = None
    description: str | None = None
    plate: str | None = None
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
    ticket_category: str = "parking"
    vehicle_description: str | None = None


class TicketLookupList(BaseModel):
    tickets: list[TicketLookup]


class RevenueReport(BaseModel):
    total_fines_issued: Decimal
    total_collected: Decimal
    total_outstanding: Decimal
    collection_rate: float
    by_method: dict[str, Decimal]
    by_status: dict[str, int]
    by_payment_type: dict[str, Decimal] = {}


# --- Payment List ---


class PaymentListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_id: uuid.UUID | None = None
    amount: Decimal
    method: str
    stripe_payment_id: str | None = None
    payment_type: str | None = None
    payer_name: str | None = None
    payer_email: str | None = None
    description: str | None = None
    plate: str | None = None
    paid_at: datetime


class PaymentListResponse(BaseModel):
    items: list[PaymentListItem]
    total: int
    page: int
    page_size: int
    pages: int


# --- Revenue Time Series ---


class RevenueTimeSeriesPoint(BaseModel):
    date: str
    citations_amount: Decimal = Decimal("0")
    permits_amount: Decimal = Decimal("0")
    total: Decimal = Decimal("0")


class RevenueTimeSeries(BaseModel):
    period: str
    data: list[RevenueTimeSeriesPoint]


# --- Public Dispute ---


class DisputeRequest(BaseModel):
    name: str
    email: str
    phone: str
    explanation: str


class DisputeResponse(BaseModel):
    status: str = "received"
    ticket_id: uuid.UUID
    message: str


# --- Permit Purchase ---


class AvailablePermitType(BaseModel):
    id: uuid.UUID
    code: str
    label: str
    price: Decimal
    remaining: int
    lot_assignments: list[str]
    valid_days: int


class AvailablePermitsResponse(BaseModel):
    permit_types: list[AvailablePermitType]
    ticket_fine_after_purchase: Decimal


class PermitPurchaseRequest(BaseModel):
    ticket_id: uuid.UUID
    permit_type_id: uuid.UUID
    student_name: str
    plate: str
    email: str
    success_url: str = "/pay/success"
    cancel_url: str = "/pay"


class PermitPurchaseResponse(BaseModel):
    checkout_url: str
    session_id: str


class StandalonePermitPurchaseRequest(BaseModel):
    permit_type_id: uuid.UUID
    student_name: str
    plate: str
    email: str
    phone: str | None = None
    class_year: int | None = None
    success_url: str = "/permits/buy/success"
    cancel_url: str = "/permits/buy"


class StandalonePermitPurchaseResponse(BaseModel):
    checkout_url: str
    session_id: str
