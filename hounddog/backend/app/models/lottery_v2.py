"""Lottery V2 tables — single-entry waterfall lottery.

Isolated from the legacy per-tier lottery tables (permit_applications).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Integer, Boolean, Float, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class LotteryV2Cycle(Base):
    __tablename__ = "lottery_v2_cycles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256), default="Parking Lottery")
    status: Mapped[str] = mapped_column(String(32), default="draft")  # draft|open|closed|drawn
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    offer_window_days: Mapped[int] = mapped_column(Integer, default=5)
    drawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    drawn_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    # Auto-draw: whichever fires first — threshold or deadline
    auto_draw_threshold: Mapped[float | None] = mapped_column(nullable=True)  # e.g. 1.10 = 110%
    auto_draw_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LotteryV2Application(Base):
    __tablename__ = "lottery_v2_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lottery_v2_cycles.id"), index=True
    )
    student_sub: Mapped[str] = mapped_column(String(256))
    student_email: Mapped[str] = mapped_column(String(256))
    student_name: Mapped[str] = mapped_column(String(256))
    class_year: Mapped[int] = mapped_column(Integer)
    campus: Mapped[str] = mapped_column(String(16))  # north|south|commuter
    plate: Mapped[str] = mapped_column(String(32))
    plate_state: Mapped[str] = mapped_column(String(2), default="")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    # Ordered list of permit_type UUIDs (preference rank 1..n)
    tier_preferences: Mapped[list] = mapped_column(ARRAY(UUID(as_uuid=True)), default=list)
    assigned_permit_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("permit_types.id"), nullable=True
    )
    assigned_lot: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    lottery_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    waitlist_position: Mapped[int | None] = mapped_column(Integer, nullable=True)
    offer_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_test_entry: Mapped[bool] = mapped_column(Boolean, default=False)
    fee_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    is_upgrade: Mapped[bool] = mapped_column(Boolean, default=False)
    existing_permit_type_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    upgrade_credit: Mapped[float | None] = mapped_column(Float, nullable=True)
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class LotteryV2AuditLog(Base):
    __tablename__ = "lottery_v2_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    cycle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("lottery_v2_cycles.id"), index=True
    )
    strategy: Mapped[str] = mapped_column(String(64), default="seniority_timestamp_waterfall")
    total_applicants: Mapped[int] = mapped_column(Integer, default=0)
    eligible_applicants: Mapped[int] = mapped_column(Integer, default=0)
    selected_count: Mapped[int] = mapped_column(Integer, default=0)
    waitlisted_count: Mapped[int] = mapped_column(Integer, default=0)
    filtered_test_entries: Mapped[int] = mapped_column(Integer, default=0)
    filtered_unpaid_citations: Mapped[int] = mapped_column(Integer, default=0)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    run_by: Mapped[str] = mapped_column(String(256), default="")
    details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    warnings: Mapped[str | None] = mapped_column(Text, nullable=True)
