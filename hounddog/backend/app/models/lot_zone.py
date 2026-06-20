import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Boolean, ForeignKey, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LotZone(Base):
    __tablename__ = "lot_zones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parking_lots.id"))
    zone_type: Mapped[str] = mapped_column(String(64))
    label: Mapped[str] = mapped_column(String(256))
    space_count: Mapped[int] = mapped_column(Integer, default=0)
    boundary: Mapped[list] = mapped_column(JSON, default=list)
    fine_override: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_premium: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
