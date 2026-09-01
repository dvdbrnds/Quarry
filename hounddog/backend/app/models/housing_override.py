import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class HousingOverride(Base):
    __tablename__ = "housing_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    moravian_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    student_name: Mapped[str] = mapped_column(String(256), default="")
    student_email: Mapped[str] = mapped_column(String(256), default="")
    override_status: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
