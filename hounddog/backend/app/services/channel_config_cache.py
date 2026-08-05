"""In-memory cache for channel_config rows.

Loaded once at startup, refreshed on every admin save.  Synchronous
reads so channel code can call get_setting() without awaiting.
"""

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("quarry.channel_config")

_cache: dict[str, dict] = {}


async def load_config(db: AsyncSession) -> None:
    """Load all channel_config rows into the in-memory cache."""
    from ..models.channel_config import ChannelConfig

    result = await db.execute(select(ChannelConfig))
    rows = result.scalars().all()
    _cache.clear()
    for row in rows:
        _cache[row.name] = {
            "enabled": row.enabled,
            "settings": row.settings or {},
            "categories": row.categories or [],
            "updated_at": row.updated_at,
            "updated_by": row.updated_by,
        }
    logger.info("Channel config cache loaded: %d channels", len(_cache))


def get_channel_config(name: str) -> dict | None:
    return _cache.get(name)


def is_channel_enabled(name: str) -> bool:
    cfg = _cache.get(name)
    if cfg is None:
        return True
    return cfg["enabled"]


def get_channel_categories(name: str) -> list[str]:
    cfg = _cache.get(name)
    if cfg is None:
        return []
    return cfg.get("categories") or []


async def save_channel_config(
    name: str,
    data: dict[str, Any],
    user_email: str,
    db: AsyncSession,
) -> dict:
    """Upsert a channel_config row and refresh the cache entry."""
    from ..models.channel_config import ChannelConfig

    row = await db.get(ChannelConfig, name)
    if not row:
        row = ChannelConfig(name=name)
        db.add(row)

    if "enabled" in data:
        row.enabled = data["enabled"]
    if "settings" in data:
        existing = row.settings or {}
        incoming = data["settings"] or {}
        merged = {**existing, **incoming}
        merged = {k: v for k, v in merged.items() if v is not None}
        row.settings = merged
    if "categories" in data:
        row.categories = data["categories"]

    row.updated_by = user_email

    await db.flush()
    await db.refresh(row)

    entry = {
        "enabled": row.enabled,
        "settings": row.settings or {},
        "categories": row.categories or [],
        "updated_at": row.updated_at,
        "updated_by": row.updated_by,
    }
    _cache[name] = entry
    return entry


async def seed_missing_channels(db: AsyncSession) -> None:
    """Create a channel_config row for each registered channel that
    doesn't already have one in the database."""
    from ..models.channel_config import ChannelConfig
    from .channels import get_registry

    existing = set(_cache.keys())
    for ch in get_registry():
        if ch.name not in existing:
            row = ChannelConfig(
                name=ch.name,
                enabled=True,
                settings={},
                categories=ch.default_categories,
                updated_by="system",
            )
            db.add(row)
            _cache[ch.name] = {
                "enabled": True,
                "settings": {},
                "categories": ch.default_categories,
                "updated_at": None,
                "updated_by": "system",
            }

    await db.flush()
