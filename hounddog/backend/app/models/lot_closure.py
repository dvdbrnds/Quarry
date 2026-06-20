import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, Boolean, func, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LotClosure(Base):
    __tablename__ = "lot_closures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("parking_lots.id"), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), default="")
    closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reopens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_immediate: Mapped[bool] = mapped_column(Boolean, default=False)
    notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    reopen_notification_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(256), default="")
    status: Mapped[str] = mapped_column(String(32), default="scheduled")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
