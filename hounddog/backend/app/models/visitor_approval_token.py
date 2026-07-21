import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class VisitorApprovalToken(Base):
    __tablename__ = "visitor_approval_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    permit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("permits.id", ondelete="CASCADE"), nullable=False)
    sponsor_email: Mapped[str] = mapped_column(String(256), nullable=False)
    sponsor_name: Mapped[str] = mapped_column(String(256), default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
