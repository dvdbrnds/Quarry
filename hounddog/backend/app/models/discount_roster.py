import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class DiscountRoster(Base):
    """Students who get an automatic flat discount (e.g. ABSN $100 off)."""

    __tablename__ = "discount_roster"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id: Mapped[str] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True, index=True)
    first_name: Mapped[str] = mapped_column(String(256), default="")
    last_name: Mapped[str] = mapped_column(String(256), default="")
    program_name: Mapped[str] = mapped_column(String(256), default="ABSN")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("100.00"))
    academic_year: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
