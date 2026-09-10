import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Text, ForeignKey, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class AppealCommitteeMember(Base):
    __tablename__ = "appeal_committee_members"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(256), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    is_chair: Mapped[bool] = mapped_column(Boolean, default=False)
    added_by: Mapped[str] = mapped_column(String(256))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CommitteeVote(Base):
    __tablename__ = "committee_votes"
    __table_args__ = (
        UniqueConstraint("ticket_id", "voter_email", name="uq_committee_vote_ticket_voter"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tickets.id"))
    voter_email: Mapped[str] = mapped_column(String(256))
    vote: Mapped[str] = mapped_column(String(16))  # "uphold" or "deny"
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    voted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
