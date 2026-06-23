import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PermitApplication(Base):
    __tablename__ = "permit_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_sub: Mapped[str] = mapped_column(String(256))
    student_email: Mapped[str] = mapped_column(String(256))
    student_name: Mapped[str] = mapped_column(String(256))
    class_year: Mapped[int] = mapped_column(Integer)
    permit_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("permit_types.id"))
    plate: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    lottery_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waitlist_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
