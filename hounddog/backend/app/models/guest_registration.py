import uuid
from datetime import datetime, date

from sqlalchemy import String, Date, DateTime, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class GuestRegistration(Base):
    __tablename__ = "guest_registrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    host_email: Mapped[str] = mapped_column(String(256), index=True)
    host_name: Mapped[str] = mapped_column(String(256))
    guest_name: Mapped[str] = mapped_column(String(256))
    guest_plate: Mapped[str | None] = mapped_column(String(32), nullable=True)
    guest_plate_state: Mapped[str] = mapped_column(String(2), default="PA")
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    roommate_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
