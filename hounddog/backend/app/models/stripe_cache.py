import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import String, DateTime, Numeric, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class StripeTransactionCache(Base):
    __tablename__ = "stripe_transaction_cache"

    id: Mapped[str] = mapped_column(String(256), primary_key=True)
    source: Mapped[str] = mapped_column(String(32), default="charge")
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    amount_refunded: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    fee: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(8), default="usd")
    status: Mapped[str] = mapped_column(String(32), default="succeeded")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    customer_name: Mapped[str | None] = mapped_column(String(256), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    payment_method_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payment_method_last4: Mapped[str | None] = mapped_column(String(8), nullable=True)
    payment_method_brand: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    livemode: Mapped[bool] = mapped_column(Boolean, default=False)
    cached_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
