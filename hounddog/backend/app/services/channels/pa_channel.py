"""Q-SYS PA system / siren channel via QRC (Q-SYS Remote Control) protocol.

QRC uses a TCP socket with JSON-RPC style commands. This channel connects to
the Q-SYS core, authenticates, and triggers the appropriate control (siren,
chime, or TTS announcement).

The specific control names are unique to Moravian's Q-SYS deployment and will
be provided by Craig Underwood (AV). The defaults below are placeholders.

Config:
    QSYS_CORE_HOST
    QSYS_CORE_PORT (default 1710)
    QSYS_CORE_USERNAME
    QSYS_CORE_PASSWORD
"""

import asyncio
import json
import logging

from . import AlertChannel, ChannelResult
from ...config import settings

logger = logging.getLogger("quarry.channels.pa")

# Placeholder control names — Craig will provide the actual ones
CONTROL_SIREN = "Emergency.Siren.Trigger"
CONTROL_CHIME = "Emergency.Chime.Trigger"
CONTROL_TTS_TEXT = "Emergency.TTS.Text"
CONTROL_TTS_TRIGGER = "Emergency.TTS.Trigger"
CONTROL_ALL_CLEAR = "Emergency.AllClear.Trigger"


async def _qrc_session(commands: list[dict]) -> None:
    """Open a TCP connection to Q-SYS core, authenticate, send commands."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(
            settings.qsys_core_host,
            settings.qsys_core_port,
        ),
        timeout=10,
    )

    try:
        if settings.qsys_core_username:
            login_cmd = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "Logon",
                "params": {
                    "User": settings.qsys_core_username,
                    "Password": settings.qsys_core_password,
                },
            }
            writer.write((json.dumps(login_cmd) + "\0").encode())
            await writer.drain()

            resp_data = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=5)
            resp = json.loads(resp_data.rstrip(b"\0"))
            if resp.get("error"):
                raise RuntimeError(f"QRC login failed: {resp['error']}")

        for i, cmd in enumerate(commands, start=2):
            cmd.setdefault("jsonrpc", "2.0")
            cmd.setdefault("id", i)
            writer.write((json.dumps(cmd) + "\0").encode())
            await writer.drain()

            resp_data = await asyncio.wait_for(reader.readuntil(b"\0"), timeout=5)
            resp = json.loads(resp_data.rstrip(b"\0"))
            if resp.get("error"):
                logger.warning("QRC command %s error: %s", cmd.get("method"), resp["error"])

    finally:
        writer.close()
        await writer.wait_closed()


def _build_alert_commands(alert) -> list[dict]:
    """Build QRC commands to trigger siren + TTS for an alert."""
    is_emergency = alert.category == "emergency"
    tts_text = f"{alert.subject}. {alert.body_text}".strip()

    commands = []

    if is_emergency:
        commands.append({
            "method": "Control.Set",
            "params": {"Name": CONTROL_SIREN, "Value": 1},
        })
    else:
        commands.append({
            "method": "Control.Set",
            "params": {"Name": CONTROL_CHIME, "Value": 1},
        })

    commands.append({
        "method": "Control.Set",
        "params": {"Name": CONTROL_TTS_TEXT, "Value": tts_text},
    })
    commands.append({
        "method": "Control.Set",
        "params": {"Name": CONTROL_TTS_TRIGGER, "Value": 1},
    })

    return commands


class PaChannel(AlertChannel):
    name = "pa"
    emergency_only = True
    default_categories = ["emergency"]
    settings_schema = [
        {"key": "core_host", "label": "Q-SYS Core Host", "type": "string", "required": True},
        {"key": "core_port", "label": "Q-SYS Core Port", "type": "number", "required": False},
        {"key": "core_username", "label": "Q-SYS Username", "type": "string", "required": False},
        {"key": "core_password", "label": "Q-SYS Password", "type": "password", "required": False},
    ]

    def is_configured(self) -> bool:
        return bool(self.get_setting("core_host", settings.qsys_core_host))

    async def send(self, alert, subscribers) -> ChannelResult:
        commands = _build_alert_commands(alert)

        try:
            await _qrc_session(commands)
            return ChannelResult(channel=self.name, sent=1)
        except Exception as e:
            logger.error("Q-SYS QRC alert failed: %s", e)
            return ChannelResult(channel=self.name, failed=1, error=str(e))

    async def clear(self, alert) -> None:
        if not self.is_configured():
            return

        try:
            await _qrc_session([{
                "method": "Control.Set",
                "params": {"Name": CONTROL_ALL_CLEAR, "Value": 1},
            }])
        except Exception as e:
            logger.error("Q-SYS QRC clear failed: %s", e)
