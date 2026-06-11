#!/usr/bin/env python3
"""
SheepDog BLE-to-HTTP Gateway

Runs on the Raspberry Pi. Listens for BLE advertisements from
occupancy sensors (XIAO nRF52840), parses state changes, and
POSTs JSON to the iPad on the lot WiFi.

Usage:
    python3 gateway.py --target http://192.168.1.50:8080/api/occupancy

Dependencies:
    pip3 install bleak aiohttp --break-system-packages
"""

import asyncio
import argparse
import json
import time
from datetime import datetime, timezone

from bleak import BleakScanner
import aiohttp

# Manufacturer data format from the XIAO:
# Bytes 0-6: sensor ID (ascii)
# Byte 7:    type (0x01 = occupancy)
# Byte 8:    state (0x00 = vacant, 0x01 = occupied)

SENSOR_PREFIX = b"occ-"  # filter for our sensors
DEBOUNCE_SECONDS = 3     # ignore repeated state within this window

# Track last known state per sensor to only POST on change
sensor_states = {}
last_post_time = {}


def parse_sensor_data(manufacturer_data: dict) -> dict | None:
    """Parse manufacturer-specific data from BLE advertisement."""
    for company_id, data in manufacturer_data.items():
        if len(data) >= 9 and data[:4] == SENSOR_PREFIX:
            sensor_id = data[0:7].decode("ascii", errors="replace")
            sensor_type = "occupancy" if data[7] == 0x01 else "unknown"
            state = "occupied" if data[8] == 0x01 else "vacant"
            return {
                "sensorId": sensor_id,
                "type": sensor_type,
                "payload": state,
            }
    return None


async def post_state(session: aiohttp.ClientSession, target_url: str, payload: dict):
    """POST sensor state to the iPad."""
    try:
        async with session.post(target_url, json=payload, timeout=aiohttp.ClientTimeout(total=5)) as resp:
            print(f"  → POST {resp.status}: {payload['sensorId']} = {payload['payload']}")
    except Exception as e:
        print(f"  → POST failed: {e}")


async def scan_and_relay(target_url: str):
    """Main loop: scan for BLE advertisements and relay state changes."""
    print(f"SheepDog Gateway starting...")
    print(f"Target: {target_url}")
    print(f"Scanning for BLE sensors with prefix '{SENSOR_PREFIX.decode()}'...")
    print()

    async with aiohttp.ClientSession() as session:

        def detection_callback(device, advertisement_data):
            if not advertisement_data.manufacturer_data:
                return

            parsed = parse_sensor_data(advertisement_data.manufacturer_data)
            if not parsed:
                return

            sensor_id = parsed["sensorId"]
            state = parsed["payload"]
            now = time.time()

            # Debounce
            if sensor_id in last_post_time:
                if now - last_post_time[sensor_id] < DEBOUNCE_SECONDS:
                    return

            # Only POST on state change
            if sensor_states.get(sensor_id) == state:
                return

            sensor_states[sensor_id] = state
            last_post_time[sensor_id] = now

            payload = {
                **parsed,
                "rssi": advertisement_data.rssi,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            print(f"[{payload['timestamp']}] {sensor_id}: {state} (RSSI {payload['rssi']})")
            asyncio.get_event_loop().create_task(
                post_state(session, target_url, payload)
            )

        scanner = BleakScanner(detection_callback=detection_callback)
        await scanner.start()

        print("Scanner running. Ctrl-C to stop.\n")

        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping scanner...")
        finally:
            await scanner.stop()


def main():
    parser = argparse.ArgumentParser(description="SheepDog BLE-to-HTTP Gateway")
    parser.add_argument(
        "--target",
        required=True,
        help="URL to POST occupancy state (e.g. http://192.168.1.50:8080/api/occupancy)",
    )
    args = parser.parse_args()

    asyncio.run(scan_and_relay(args.target))


if __name__ == "__main__":
    main()
