from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Integer, Boolean, Numeric, ARRAY, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class EnforcementSettings(Base):
    __tablename__ = "enforcement_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    payment_due_days: Mapped[int] = mapped_column(Integer, default=5)
    appeal_window_days: Mapped[int] = mapped_column(Integer, default=5)
    academic_year_start_month: Mapped[int] = mapped_column(Integer, default=8)
    academic_year_start_day: Mapped[int] = mapped_column(Integer, default=1)
    escalation_threshold: Mapped[int] = mapped_column(Integer, default=3)
    permit_fine_reduction: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    unpaid_blocks_registration: Mapped[bool] = mapped_column(Boolean, default=True)
    towing_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    towing_violation_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String), default=lambda: ["disability_area", "fire_hydrant"]
    )
    snow_emergency_active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[str] = mapped_column(String(256), default="system")
