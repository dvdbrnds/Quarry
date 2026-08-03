import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class CouponUsage(Base):
    __tablename__ = "coupon_usages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    coupon_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True)
    coupon_code: Mapped[str] = mapped_column(String(64))
    program_name: Mapped[str] = mapped_column(String(256), default="")
    student_name: Mapped[str] = mapped_column(String(256), default="")
    student_email: Mapped[str] = mapped_column(String(256), default="")
    student_id: Mapped[str] = mapped_column(String(64), default="")
    permit_type_code: Mapped[str] = mapped_column(String(64), default="")
    original_price: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    final_price: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
