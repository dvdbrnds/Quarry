import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, Boolean, Integer, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class ViolationType(Base):
    __tablename__ = "violation_types"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    label: Mapped[str] = mapped_column(String(256))
    category: Mapped[str] = mapped_column(String(32), default="parking")
    fine_first: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=Decimal("35.00"))
    fine_second: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    fine_third_plus: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
