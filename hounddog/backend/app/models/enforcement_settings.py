from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import String, Date, DateTime, Integer, Boolean, Numeric, ARRAY, func
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
    conduct_officer_emails: Mapped[str] = mapped_column(String(1024), default="")
    updated_by: Mapped[str] = mapped_column(String(256), default="system")

    # Citation policy v2 (no effect until policy_effective_date is set)
    policy_effective_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    legacy_resolution_deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    policy_reminder_day: Mapped[int] = mapped_column(Integer, default=7, server_default="7")
    policy_due_day: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    policy_late_fee_1_day: Mapped[int] = mapped_column(Integer, default=11, server_default="11")
    policy_late_fee_2_day: Mapped[int] = mapped_column(Integer, default=31, server_default="31")
    late_fee_1_amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("15.00"), server_default="15.00")
    late_fee_2_amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("20.00"), server_default="20.00")
    late_fee_cap: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("35.00"), server_default="35.00")
    denied_appeal_grace_days: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    owner_notification_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("25.00"), server_default="25.00")
    policy_job_hour: Mapped[int] = mapped_column(Integer, default=6, server_default="6")
    barnacle_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    barnacle_min_citations: Mapped[int] = mapped_column(Integer, default=3, server_default="3")
    barnacle_delinquent_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    barnacle_warning_wait_days: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    barnacle_warning_lookahead_days: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    barnacle_deployment_fee: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("100.00"), server_default="100.00")
    removal_phone_daytime: Mapped[str] = mapped_column(String(64), default="", server_default="")
    removal_phone_after_hours: Mapped[str] = mapped_column(String(64), default="", server_default="")
