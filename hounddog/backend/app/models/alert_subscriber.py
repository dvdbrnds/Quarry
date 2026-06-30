import secrets
import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


def _generate_token() -> str:
    return secrets.token_hex(32)


class AlertSubscriber(Base):
    __tablename__ = "alert_subscribers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256))
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sms_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    email_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    categories: Mapped[list] = mapped_column(JSON, default=list)
    unsubscribe_token: Mapped[str] = mapped_column(String(64), unique=True, default=_generate_token)
    source: Mapped[str] = mapped_column(String(32), default="self")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
