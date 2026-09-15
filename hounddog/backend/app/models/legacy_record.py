import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LegacyRecord(Base):
    __tablename__ = "legacy_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate_normalized: Mapped[str] = mapped_column(String(32), nullable=False, index=True, unique=True)
    plate_raw: Mapped[str] = mapped_column(String(32), default="")
    plate_state: Mapped[str] = mapped_column(String(8), default="")
    owner_name: Mapped[str] = mapped_column(String(256), default="")
    permit_number: Mapped[str] = mapped_column(String(64), default="")
    permit_type: Mapped[str] = mapped_column(String(64), default="")
    permit_status: Mapped[str] = mapped_column(String(32), default="")
    lot_zone: Mapped[str] = mapped_column(String(256), default="")
    vehicle_color: Mapped[str] = mapped_column(String(64), default="")
    vehicle_make: Mapped[str] = mapped_column(String(64), default="")
    vehicle_model: Mapped[str] = mapped_column(String(64), default="")
    vehicle_year: Mapped[str] = mapped_column(String(8), default="")
    vehicle_description: Mapped[str] = mapped_column(String(256), default="")
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="omnigo")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
