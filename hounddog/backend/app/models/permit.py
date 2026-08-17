import uuid
from datetime import date, datetime

from decimal import Decimal

from sqlalchemy import String, Date, DateTime, Boolean, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Permit(Base):
    __tablename__ = "permits"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    permit_number: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    student_id: Mapped[str] = mapped_column(String(64), default="")
    moravian_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str] = mapped_column(String(32), default="")
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    plates: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    lot_assignment: Mapped[str] = mapped_column(String(512), default="")
    permit_type: Mapped[str] = mapped_column(String(64), default="student")
    beacon_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    start_date: Mapped[date] = mapped_column(Date, default=date.today)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_plate_change: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stripe_session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    refund_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
