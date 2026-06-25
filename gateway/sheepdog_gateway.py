#!/usr/bin/env python3
"""
SheepDog BLE Gateway — scans for occupancy puck advertisements and
relays state changes to HoundDog via HTTP.

Runs on a Raspberry Pi with Bluetooth. Requires: bleak, httpx.

Usage:
    pip install bleak httpx
    python sheepdog_gateway.py --url https://hounddog.example.com --key <api-key>

The gateway scans continuously for manufacturer-specific BLE advertisements
from SheepDog pucks (company ID 0xFFFF). It parses the 9-byte payload:

    Bytes 0-6: sensor ID (ASCII, e.g. "A-001")
    Byte  7:   type      (0x01 = occupancy)
    Byte  8:   state     (0x00 = vacant, 0x01 = occupied)

State changes are batched and POSTed to /api/sync/occupancy.
"""

import argparse
import asyncio
import logging
import struct
import time
from datetime import datetime, timezone

import httpx
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("sheepdog")

COMPANY_ID = 0xFFFF
OCCUPANCY_TYPE = 0x01
REPORT_INTERVAL = 5  # seconds between HTTP posts
STALE_TIMEOUT = 30   # forget pucks not seen in this window


class PuckState:
    def __init__(self, sensor_id: str, state: int, rssi: int):
        self.sensor_id = sensor_id
        self.state = state
        self.rssi = rssi
        self.last_seen = time.monotonic()
        self.dirty = True  # needs to be reported


known_pucks: dict[str, PuckState] = {}


def parse_manufacturer_data(mfg_data: dict[int, bytes]) -> tuple[str, int, int] | None:
    """Extract (sensor_id, type, state) from manufacturer data, or None."""
    raw = mfg_data.get(COMPANY_ID)
    if raw is None or len(raw) < 9:
        return None

    sensor_id = raw[0:7].rstrip(b"\x00").decode("ascii", errors="replace")
    msg_type = raw[7]
    state = raw[8]

    if msg_type != OCCUPANCY_TYPE:
        return None

    return sensor_id, msg_type, state


def detection_callback(device: BLEDevice, adv: AdvertisementData):
    parsed = parse_manufacturer_data(adv.manufacturer_data)
    if parsed is None:
        return

    sensor_id, _, state = parsed
    rssi = adv.rssi or -127

    existing = known_pucks.get(sensor_id)
    if existing is None:
        log.info("Discovered puck %s → %s (RSSI %d)", sensor_id, "occupied" if state else "vacant", rssi)
        known_pucks[sensor_id] = PuckState(sensor_id, state, rssi)
    else:
        existing.last_seen = time.monotonic()
        existing.rssi = rssi
        if existing.state != state:
            old = "occupied" if existing.state else "vacant"
            new = "occupied" if state else "vacant"
            log.info("State change %s: %s → %s (RSSI %d)", sensor_id, old, new, rssi)
            existing.state = state
            existing.dirty = True


async def report_loop(client: httpx.AsyncClient, url: str, api_key: str):
    endpoint = f"{url.rstrip('/')}/api/sync/occupancy"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    while True:
        await asyncio.sleep(REPORT_INTERVAL)

        now = time.monotonic()
        stale = [k for k, v in known_pucks.items() if now - v.last_seen > STALE_TIMEOUT]
        for k in stale:
            log.info("Puck %s stale, removing", k)
            del known_pucks[k]

        dirty = [p for p in known_pucks.values() if p.dirty]
        if not dirty:
            continue

        reports = []
        for p in dirty:
            reports.append({
                "sensor_id": p.sensor_id,
                "type": "occupancy",
                "payload": "occupied" if p.state else "vacant",
                "rssi": p.rssi,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        try:
            resp = await client.post(endpoint, json=reports, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            log.info("Reported %d reading(s): %d accepted, %d unknown",
                     len(reports), data.get("accepted", 0), len(data.get("unknown", [])))
            for uid in data.get("unknown", []):
                log.warning("  Unknown sensor ID: %s (not registered in HoundDog)", uid)
            for p in dirty:
                p.dirty = False
        except httpx.HTTPError as e:
            log.error("Failed to report: %s", e)


async def main(url: str, api_key: str):
    log.info("Starting SheepDog BLE gateway")
    log.info("HoundDog URL: %s", url)
    log.info("Scanning for puck advertisements (company ID 0x%04X)...", COMPANY_ID)

    scanner = BleakScanner(detection_callback=detection_callback)

    async with httpx.AsyncClient(timeout=10) as client:
        report_task = asyncio.create_task(report_loop(client, url, api_key))

        await scanner.start()
        try:
            await asyncio.Event().wait()  # run forever
        finally:
            await scanner.stop()
            report_task.cancel()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SheepDog BLE Gateway")
    parser.add_argument("--url", required=True, help="HoundDog base URL")
    parser.add_argument("--key", required=True, help="HoundDog API key (from Devices page)")
    args = parser.parse_args()

    asyncio.run(main(args.url, args.key))
