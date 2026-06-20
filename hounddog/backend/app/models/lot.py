import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Boolean, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ParkingLot(Base):
    __tablename__ = "parking_lots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), unique=True)
    boundary: Mapped[list] = mapped_column(JSON, default=list)
    total_spaces: Mapped[int] = mapped_column(Integer, default=0)
    handicap_spaces: Mapped[int] = mapped_column(Integer, default=0)
    designation_code: Mapped[str] = mapped_column(String(32), default="")
    designation_label: Mapped[str] = mapped_column(String(256), default="")
    access_schedule: Mapped[list] = mapped_column(JSON, default=list)
    is_snow_lot: Mapped[bool] = mapped_column(Boolean, default=False)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
