import uuid
from datetime import datetime

from sqlalchemy import String, Boolean, Integer, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class VisitorPreset(Base):
    __tablename__ = "visitor_presets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String(256), nullable=False)
    company_name: Mapped[str] = mapped_column(String(256), default="")
    sponsor_name: Mapped[str] = mapped_column(String(256), default="")
    sponsor_email: Mapped[str] = mapped_column(String(256), default="")
    sponsor_department: Mapped[str] = mapped_column(String(256), default="")
    default_duration: Mapped[str] = mapped_column(String(32), default="semester")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
