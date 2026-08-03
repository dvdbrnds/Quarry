import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class FeeExemptRoster(Base):
    __tablename__ = "fee_exempt_roster"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(256), default="")
    last_name: Mapped[str] = mapped_column(String(256), default="")
    reason: Mapped[str] = mapped_column(String(256), default="Res Life Staff")
    building: Mapped[str | None] = mapped_column(String(256), nullable=True)
    room: Mapped[str | None] = mapped_column(String(128), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
