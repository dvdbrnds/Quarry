"""Citation policy v2: fees, clock pauses, notices, payment plans, Barnacle, MUPD review."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, LargeBinary, Numeric,
    String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class CitationFee(Base):
    __tablename__ = "citation_fees"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    fee_type: Mapped[str] = mapped_column(String(32), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    # open | paid | waived | voided
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    plate: Mapped[str] = mapped_column(String(32), index=True)
    plate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachment_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attachment_mime: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attachment_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    deployment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    owner_notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolve_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class CitationFeeTicket(Base):
    __tablename__ = "citation_fee_tickets"

    fee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("citation_fees.id", ondelete="CASCADE"), primary_key=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class CitationClockPause(Base):
    """Half-open [start_date, end_date) interval during which a citation's clock does not run.

    floor_elapsed: when the pause ends, effective elapsed days jump to at least this value
    (a denied appeal's grace period ends at the delinquency stage).
    """
    __tablename__ = "citation_clock_pauses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), index=True
    )
    # appeal | appeal_grace | payment_plan
    reason: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    floor_elapsed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class CitationNotice(Base):
    __tablename__ = "citation_notices"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # REMINDER | DELINQUENCY_1 | FINAL | BARNACLE_WARNING | ROLLOUT
    notice_type: Mapped[str] = mapped_column(String(32), index=True)
    # email | mail
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(512), default="")
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    plate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    ticket_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    subject: Mapped[str] = mapped_column(String(512), default="")
    body_html: Mapped[str] = mapped_column(Text, default="")
    body_text: Mapped[str] = mapped_column(Text, default="")
    balance: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    earliest_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # pending | sent | failed | cancelled
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    mailed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentPlan(Base):
    __tablename__ = "payment_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payer_name: Mapped[str] = mapped_column(String(256), default="")
    payer_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # active | completed | defaulted | cancelled
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    defaulted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)


class PaymentPlanCitation(Base):
    __tablename__ = "payment_plan_citations"

    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_plans.id", ondelete="CASCADE"), primary_key=True
    )
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    added_by: Mapped[str] = mapped_column(String(256), default="system")
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PaymentPlanInstallment(Base):
    __tablename__ = "payment_plan_installments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payment_plans.id", ondelete="CASCADE"), index=True
    )
    due_date: Mapped[date] = mapped_column(Date)
    amount: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(256), nullable=True)


class BarnacleDeployment(Base):
    __tablename__ = "barnacle_deployments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate: Mapped[str] = mapped_column(String(32), index=True)
    plate_state: Mapped[str] = mapped_column(String(2))
    # deployed | removal_requested | removed
    status: Mapped[str] = mapped_column(String(24), default="deployed", index=True)
    officer_email: Mapped[str] = mapped_column(String(256))
    officer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    deployed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    location_text: Mapped[str] = mapped_column(String(512), default="")
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    vehicle_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    authorized_property_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    checklist: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ticket_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    removal_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removal_request_contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    override_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    removal_notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class OwnerNotificationEvent(Base):
    __tablename__ = "owner_notification_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate: Mapped[str] = mapped_column(String(32), index=True)
    plate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    owner_name: Mapped[str] = mapped_column(String(256))
    mailing_address: Mapped[str] = mapped_column(Text)
    lookup_source: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mailed_on: Mapped[date] = mapped_column(Date)
    ticket_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MupdReview(Base):
    __tablename__ = "mupd_reviews"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"), unique=True
    )
    plate: Mapped[str] = mapped_column(String(32), index=True)
    plate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    # open | referred | closed_no_action | closed_paid
    status: Mapped[str] = mapped_column(String(24), default="open", index=True)
    incident_documentation: Mapped[str | None] = mapped_column(Text, nullable=True)
    signage_restrictions: Mapped[str | None] = mapped_column(Text, nullable=True)
    registered_owner: Mapped[str | None] = mapped_column(Text, nullable=True)
    responsible_person_evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    exception_claimed: Mapped[str | None] = mapped_column(String(32), nullable=True)
    exception_details: Mapped[str | None] = mapped_column(Text, nullable=True)
    filing_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    court_case_number: Mapped[str | None] = mapped_column(String(128), nullable=True)
    court_outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    court_fine_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(256), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class PaymentAllocation(Base):
    """One row per item a payment covered: a citation fine, a fee, or the processing fee."""
    __tablename__ = "payment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    payment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    ticket_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    fee_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # CITATION | LATE_FEE_1 | ... | PROCESSING_FEE
    fee_type: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
