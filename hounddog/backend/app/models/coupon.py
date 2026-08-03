import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, Boolean, Integer, ARRAY, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class Coupon(Base):
    __tablename__ = "coupons"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    program_name: Mapped[str] = mapped_column(String(256), default="")
    discount_type: Mapped[str] = mapped_column(String(16))  # "percent", "flat", "full"
    discount_value: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    applicable_permit_codes: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    max_uses: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_uses: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
