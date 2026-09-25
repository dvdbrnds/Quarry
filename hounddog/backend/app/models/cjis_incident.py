"""
CJIS Security Policy v6.1 — IR-4, IR-6.
Incident response tracking for CJIS/JNET security events.
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class CJISIncident(Base):
    __tablename__ = "cjis_incidents"
    __table_args__ = (
        {"comment": "CJIS Security Policy v6.1 — IR-4/IR-6. Security incident tracking."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True,
    )
    incident_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    affected_records_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    detected_by: Mapped[str] = mapped_column(String(256), nullable=False, default="system")

    # Reporting chain
    reported_to_iso_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # Resolution
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
