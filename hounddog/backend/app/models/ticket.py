import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Float, Integer, ForeignKey, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate: Mapped[str] = mapped_column(String(32))
    permit_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permits.id"), nullable=True
    )
    lot: Mapped[str] = mapped_column(String(128), default="")
    zone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    violation_type: Mapped[str] = mapped_column(String(64), default="no_permit")
    violation_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("violation_types.id"), nullable=True
    )
    fine_amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("50.00"))
    photo_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    officer_id: Mapped[str] = mapped_column(String(128), default="")
    officer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    officer_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(32), default="issued")

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

    # Appeal / dispute fields
    appeal_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    appeal_decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    appeal_decided_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    dispute_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dispute_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    dispute_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
