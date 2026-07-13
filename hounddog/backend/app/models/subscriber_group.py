import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Text, func, ForeignKey, Column, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


subscriber_group_members = Table(
    "subscriber_group_members",
    Base.metadata,
    Column("subscriber_id", UUID(as_uuid=True), ForeignKey("alert_subscribers.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", UUID(as_uuid=True), ForeignKey("subscriber_groups.id", ondelete="CASCADE"), primary_key=True),
)


class SubscriberGroup(Base):
    __tablename__ = "subscriber_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    group_type: Mapped[str] = mapped_column(String(64), default="custom")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
