import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, Boolean, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class MessageTemplate(Base):
    __tablename__ = "message_templates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    reason_code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    reason_label: Mapped[str] = mapped_column(String(128), nullable=False)
    is_emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    email_subject: Mapped[str] = mapped_column(String(256), default="")
    email_body: Mapped[str] = mapped_column(Text, default="")
    sms_body: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
