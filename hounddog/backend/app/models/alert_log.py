import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AlertLog(Base):
    __tablename__ = "alert_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    category: Mapped[str] = mapped_column(String(64))
    subject: Mapped[str] = mapped_column(String(512))
    body_text: Mapped[str] = mapped_column(Text, default="")
    body_sms: Mapped[str] = mapped_column(String(320), default="")
    sent_by: Mapped[str] = mapped_column(String(256))
    email_count: Mapped[int] = mapped_column(Integer, default=0)
    sms_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="active")
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    channel_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
