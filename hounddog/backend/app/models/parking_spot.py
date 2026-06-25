import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Float, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ParkingSpot(Base):
    __tablename__ = "parking_spots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    label: Mapped[str | None] = mapped_column(String(256), nullable=True)
    sensor_id: Mapped[str | None] = mapped_column(String(16), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
