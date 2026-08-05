"""
Multi-channel alert delivery system.

Each channel implements AlertChannel and is registered in REGISTRY.
The alert dispatcher iterates REGISTRY and calls send() on each
configured, enabled channel.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.alert_log import AlertLog

logger = logging.getLogger("quarry.channels")


@dataclass
class ChannelResult:
    channel: str
    sent: int = 0
    failed: int = 0
    error: str | None = None


class AlertChannel:
    """Base class for alert delivery channels."""

    name: str = "base"
    emergency_only: bool = False

    settings_schema: list[dict] = []
    default_categories: list[str] = []

    async def send(self, alert: AlertLog, subscribers: list) -> ChannelResult:
        raise NotImplementedError

    async def clear(self, alert: AlertLog) -> None:
        """Called when an alert is cleared. Override for channels that
        maintain persistent state (signage, banner)."""
        pass

    def is_configured(self) -> bool:
        """Return True if this channel has the necessary config to operate."""
        return False

    def get_setting(self, key: str, fallback: str = "") -> str:
        """Read a channel setting from the DB config cache, falling back
        to the provided value (typically the env-var default)."""
        from ..channel_config_cache import get_channel_config

        cfg = get_channel_config(self.name)
        if cfg and cfg.get("settings"):
            val = cfg["settings"].get(key)
            if val is not None and val != "":
                return str(val)
        return fallback


REGISTRY: list[AlertChannel] = []


def register_channel(channel: AlertChannel) -> None:
    REGISTRY.append(channel)


def get_registry() -> list[AlertChannel]:
    return REGISTRY
