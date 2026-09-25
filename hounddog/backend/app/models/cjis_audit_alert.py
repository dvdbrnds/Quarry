"""
CJIS Security Policy v6.1 — AU-6(1).
Anomaly detection flags for JNET query patterns.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class CJISAuditAlert(Base):
    __tablename__ = "cjis_audit_alerts"
    __table_args__ = (
        {"comment": "CJIS Security Policy v6.1 — AU-6(1). Anomaly detection alerts for JNET queries."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    audit_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("cjis_audit_logs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Review tracking — alerts must be reviewed weekly per CJIS policy
    reviewed_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    dismiss_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
