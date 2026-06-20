import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, Boolean, Integer, ARRAY, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class PermitType(Base):
    __tablename__ = "permit_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(256))
    eligible: Mapped[str] = mapped_column(String(512), default="")
    price: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("0.00"))
    max_capacity: Mapped[int] = mapped_column(Integer, default=0)
    valid_days: Mapped[int] = mapped_column(Integer, default=365)
    lot_assignments: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    time_restriction: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_purchasable_online: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
