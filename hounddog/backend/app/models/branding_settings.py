from datetime import datetime

from sqlalchemy import String, DateTime, Integer, LargeBinary, func
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class BrandingSettings(Base):
    __tablename__ = "branding_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    brand_name: Mapped[str] = mapped_column(String(256), default="Quarry")
    primary_color: Mapped[str] = mapped_column(String(32), default="#1a2744")
    accent_color: Mapped[str] = mapped_column(String(32), default="#c9a84c")

    logo_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    logo_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)
    favicon_data: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    favicon_mime: Mapped[str | None] = mapped_column(String(64), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
