import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PlateCorrection(Base):
    __tablename__ = "plate_corrections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ocr_plate: Mapped[str] = mapped_column(String(20))
    correct_plate: Mapped[str] = mapped_column(String(20))
    plate_state: Mapped[str] = mapped_column(String(4), default="")
    lot: Mapped[str] = mapped_column(String(128), default="")
    officer_name: Mapped[str] = mapped_column(String(256), default="")
    officer_email: Mapped[str] = mapped_column(String(256), default="")
    device_name: Mapped[str] = mapped_column(String(256), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
