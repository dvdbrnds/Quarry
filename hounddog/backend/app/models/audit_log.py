import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, func, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    user_email: Mapped[str] = mapped_column(String(256), index=True)
    user_sub: Mapped[str] = mapped_column(String(256), default="")
    action: Mapped[str] = mapped_column(String(16), index=True)
    resource_type: Mapped[str] = mapped_column(String(64), index=True)
    resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    endpoint: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(String(1024), default="")
    request_body: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    response_status: Mapped[int] = mapped_column(Integer, default=200)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
