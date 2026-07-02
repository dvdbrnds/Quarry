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

    async def send(self, alert: AlertLog, subscribers: list) -> ChannelResult:
        raise NotImplementedError

    async def clear(self, alert: AlertLog) -> None:
        """Called when an alert is cleared. Override for channels that
        maintain persistent state (signage, banner)."""
        pass

    def is_configured(self) -> bool:
        """Return True if this channel has the necessary config to operate."""
        return False


REGISTRY: list[AlertChannel] = []


def register_channel(channel: AlertChannel) -> None:
    REGISTRY.append(channel)


def get_registry() -> list[AlertChannel]:
    return REGISTRY
