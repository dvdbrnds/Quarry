import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LegacyRecord(Base):
    __tablename__ = "legacy_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plate_normalized: Mapped[str] = mapped_column(Text, nullable=False, index=True, unique=True)
    plate_raw: Mapped[str] = mapped_column(Text, default="")
    plate_state: Mapped[str] = mapped_column(Text, default="")
    owner_name: Mapped[str] = mapped_column(Text, default="")
    permit_number: Mapped[str] = mapped_column(Text, default="")
    permit_type: Mapped[str] = mapped_column(Text, default="")
    permit_status: Mapped[str] = mapped_column(Text, default="")
    lot_zone: Mapped[str] = mapped_column(Text, default="")
    vehicle_color: Mapped[str] = mapped_column(Text, default="")
    vehicle_make: Mapped[str] = mapped_column(Text, default="")
    vehicle_model: Mapped[str] = mapped_column(Text, default="")
    vehicle_year: Mapped[str] = mapped_column(Text, default="")
    vehicle_description: Mapped[str] = mapped_column(Text, default="")
    record_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(Text, default="omnigo")
    imported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
