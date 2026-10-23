import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import String, Date, DateTime, Float, Integer, ForeignKey, Numeric, Text, LargeBinary, func, JSON, event
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from ..database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    plate: Mapped[str] = mapped_column(String(32))
    plate_state: Mapped[str | None] = mapped_column(String(2), nullable=True)
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permits.id"), nullable=True
    )
    lot: Mapped[str] = mapped_column(String(128), default="")
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    violation_type: Mapped[str] = mapped_column(String(64), default="no_permit")
    violation_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("violation_types.id"), nullable=True
    )
    additional_violations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    fine_amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("50.00"))
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    photo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    photo_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    additional_photo_count: Mapped[int] = mapped_column(Integer, default=0)
    additional_photos: Mapped[list | None] = mapped_column(JSON, nullable=True)
    officer_id: Mapped[str] = mapped_column(String(128), default="")
    officer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    officer_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    owner_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permit_number: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permit_type_label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    permit_lot_zone: Mapped[str | None] = mapped_column(String(256), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="issued")

    # Citation policy v2 — status stays the payment state; stage tracks the timeline
    policy_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    timeline_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    delinquent_since: Mapped[date | None] = mapped_column(Date, nullable=True)
    appeal_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appeal_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Moving violation / traffic stop fields
    ticket_category: Mapped[str] = mapped_column(String(32), default="parking")
    offense_number: Mapped[int] = mapped_column(Integer, default=1)
    location_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_text: Mapped[str | None] = mapped_column(String(512), nullable=True)
    vehicle_description: Mapped[str | None] = mapped_column(String(256), nullable=True)
    officer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    driver_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    driver_license: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # OCR correction — stores what the camera read when the officer corrected the plate
    ocr_original_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Mail notice tracking (for guests/visitors without email)
    mailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mailed_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Appeal / dispute fields
    appeal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    appeal_decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    appeal_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Committee escalation fields
    committee_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    committee_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    committee_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    committee_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notification_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    enforcement_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    dispute_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dispute_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dispute_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


RESOLVED_STATUSES = ("paid", "voided", "resolved_permit")
_CLOSE_REASONS = {
    "paid": "Closed automatically: the citation was paid.",
    "voided": "Closed automatically: the citation was voided.",
    "resolved_permit": "Closed automatically: the citation was resolved with a permit.",
}


def close_resolved_appeal(ticket: Ticket) -> None:
    """A paid/voided/resolved ticket can't keep a pending appeal or an open committee case."""
    if ticket.status not in RESOLVED_STATUSES:
        return
    now = datetime.now(timezone.utc)
    if ticket.appeal_decision == "pending":
        ticket.appeal_decision = "closed"
        ticket.appeal_decided_by = "system"
        ticket.appeal_decided_at = now
        ticket.appeal_decision_reason = _CLOSE_REASONS[ticket.status]
    if ticket.committee_status == "voting":
        ticket.committee_status = "decided"
        ticket.committee_decision = "closed"
        ticket.committee_decided_at = now


@event.listens_for(Session, "before_flush")
def _close_appeals_on_resolution(session, flush_context, instances):
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Ticket):
            close_resolved_appeal(obj)
