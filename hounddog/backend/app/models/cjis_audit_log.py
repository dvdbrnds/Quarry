"""
CJIS Security Policy v6.1 — AU-2, AU-3, AU-6, AU-9, AU-11.
Append-only audit log for every JNET query.
No CJI response data is ever stored in this table.
Retain minimum 1 year.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class CJISAuditLog(Base):
    __tablename__ = "cjis_audit_logs"
    __table_args__ = (
        {"comment": "CJIS Security Policy v6.1 — AU-2/AU-3. Retain minimum 1 year. No CJI response data stored."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True, nullable=False,
    )

    # Officer identity (denormalized for audit immutability)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    user_email: Mapped[str] = mapped_column(String(256), nullable=False)
    user_full_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    # Query details
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    query_plate: Mapped[str] = mapped_column(String(16), nullable=False)
    query_state: Mapped[str] = mapped_column(String(4), nullable=False, default="PA")
    ori: Mapped[str] = mapped_column(String(16), nullable=False)

    # Request context
    source_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # Result metadata (never CJI content)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_time_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
