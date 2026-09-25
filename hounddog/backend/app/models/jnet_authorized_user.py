"""
CJIS Security Policy v6.1 — AC-2, AC-5, AC-6.
JNET authorization tracking — standalone table (no FK to a users table
since Quarry uses stateless Okta JWT auth).
"""

import uuid
from datetime import datetime

from sqlalchemy import String, DateTime, Boolean, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class JNETAuthorizedUser(Base):
    __tablename__ = "jnet_authorized_users"
    __table_args__ = (
        {"comment": "CJIS Security Policy v6.1 — AC-2/AC-5/AC-6. JNET access authorization tracking."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    okta_sub: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False, index=True,
    )
    email: Mapped[str] = mapped_column(
        String(256), unique=True, nullable=False, index=True,
    )
    full_name: Mapped[str] = mapped_column(String(512), nullable=False, default="")

    # Role within the CJIS walled garden: 'jnet_officer' or 'cjis_admin'
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="jnet_officer")

    jnet_authorized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    jnet_authorized_by_email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    jnet_authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    jnet_background_check_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    jnet_training_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    jnet_last_activity: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    jnet_last_access_review: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
