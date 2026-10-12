import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ClassificationOverride(Base):
    """Manual override for a person's parking classification.

    override_status values:
      R  = Student (Resident)
      C  = Student (Commuter)
      O  = Student (Off Campus)
      F  = Faculty
      S  = Staff
    """
    __tablename__ = "housing_overrides"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("gen_random_uuid()"))
    moravian_id: Mapped[str] = mapped_column(String(32), default="", index=True)
    student_name: Mapped[str] = mapped_column(String(256), default="")
    student_email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    override_status: Mapped[str] = mapped_column(String(8), nullable=False)
    reason: Mapped[str] = mapped_column(String(512), default="")
    created_by: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# Backwards compat alias
HousingOverride = ClassificationOverride
