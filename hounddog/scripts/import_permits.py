#!/usr/bin/env python3
"""Import parking permits from xlsx files into the Quarry database.

Reads both the historical and recent xlsx exports, deduplicates by plate
(newer record wins), and inserts into the running Postgres via the API.
"""

import sys
import json
from datetime import datetime
from pathlib import Path

import openpyxl
import httpx

API_BASE = "http://localhost:8000"

COLUMN_MAP = {
    "Permit Number": "permit_number",
    "Record Date": "record_date",
    "Location": "location",
    "Status": "status",
    "First Name": "first_name",
    "Last Name": "last_name",
    "Contact Type": "contact_type",
    "Vehicle Color": "vehicle_color",
    "Vehicle Make": "vehicle_make",
    "Vehicle Model": "vehicle_model",
    "Plate": "plate",
    "Plate State": "plate_state",
    "Vehicle Year": "vehicle_year",
    "Expiration Date": "expiration_date",
    "Owner": "owner",
}


def parse_xlsx(path: str) -> list[dict]:
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [str(h).strip() if h else "" for h in rows[0]]
    records = []
    for row in rows[1:]:
        raw = dict(zip(headers, row))
        rec = {}
        for xlsx_col, key in COLUMN_MAP.items():
            rec[key] = raw.get(xlsx_col) or ""
            if rec[key] is None:
                rec[key] = ""
        records.append(rec)
    return records


def normalize_plate(plate: str) -> str:
    return "".join(c for c in plate.upper().strip() if c.isalnum())


def parse_date(val) -> str | None:
    if not val:
        return None
    if isinstance(val, datetime):
        return val.date().isoformat()
    s = str(val).strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def clean_location(loc: str) -> str:
    loc = str(loc).strip()
    for prefix in ("_PARKING LOTS : ", "_PARKING LOTS", "PARKING LOTS : ", "PARKING LOTS"):
        if loc.upper().startswith(prefix):
            loc = loc[len(prefix):].strip()
            break
    return loc or "GENERAL"


def map_status(raw: str) -> str:
    raw = str(raw).strip().lower()
    if raw in ("valid", "active"):
        return "active"
    if raw in ("expired",):
        return "expired"
    if raw in ("revoked", "suspended"):
        return "revoked"
    return "active"


def map_permit_type(contact_type: str) -> str:
    ct = str(contact_type).strip().lower()
    if "faculty" in ct or "staff" in ct:
        return "faculty"
    if "visitor" in ct:
        return "visitor"
    return "student"


def merge_records(old_records: list[dict], new_records: list[dict]) -> list[dict]:
    by_plate: dict[str, dict] = {}

    for rec in old_records:
        plate = normalize_plate(rec.get("plate", ""))
        if plate:
            by_plate[plate] = rec

    for rec in new_records:
        plate = normalize_plate(rec.get("plate", ""))
        if plate:
            by_plate[plate] = rec

    return list(by_plate.values())


def to_api_payload(records: list[dict]) -> list[dict]:
    permits = []
    for rec in records:
        plate = normalize_plate(rec.get("plate", ""))
        if not plate:
            continue

        owner = str(rec.get("owner", "")).strip()
        if not owner:
            first = str(rec.get("first_name", "")).strip()
            last = str(rec.get("last_name", "")).strip()
            owner = f"{first} {last}".strip() or plate

        color = str(rec.get("vehicle_color", "")).strip()
        make = str(rec.get("vehicle_make", "")).strip()
        model = str(rec.get("vehicle_model", "")).strip()
        year = str(rec.get("vehicle_year", "")).strip()
        vehicle_desc = " ".join(p for p in [color, year, make, model] if p and p != "UNKNOWN")

        permits.append({
            "plate_normalized": plate,
            "plate_state": str(rec.get("plate_state", "")).strip() or "PA",
            "owner_name": owner,
            "permit_number": str(rec.get("permit_number", "")).strip(),
            "permit_type": map_permit_type(rec.get("contact_type", "")),
            "permit_status": map_status(rec.get("status", "")),
            "lot_zone": clean_location(rec.get("location", "")),
            "vehicle_description": vehicle_desc,
            "issued_date": parse_date(rec.get("record_date")),
            "expiration_date": parse_date(rec.get("expiration_date")),
        })

    return permits


def main():
    repo_root = Path(__file__).resolve().parent.parent.parent

    old_file = repo_root / "All Parking Permits.xlsx"
    new_file = repo_root / "BirdDog" / "Parking Permits Export (1-1-25 to 6-11-26).xlsx"

    print(f"Reading {old_file.name}...")
    old_records = parse_xlsx(str(old_file))
    print(f"  → {len(old_records)} rows")

    print(f"Reading {new_file.name}...")
    new_records = parse_xlsx(str(new_file))
    print(f"  → {len(new_records)} rows")

    print("Merging and deduplicating by plate...")
    merged = merge_records(old_records, new_records)
    print(f"  → {len(merged)} unique permits")

    permits = to_api_payload(merged)
    print(f"  → {len(permits)} with valid plates")

    BATCH_SIZE = 500
    total_inserted = 0
    total_updated = 0
    total_skipped = 0

    for i in range(0, len(permits), BATCH_SIZE):
        batch = permits[i : i + BATCH_SIZE]
        print(f"  Importing batch {i // BATCH_SIZE + 1} ({len(batch)} permits)...")

        resp = httpx.post(
            f"{API_BASE}/api/permits/import",
            json={"permits": batch},
            timeout=120,
        )

        if resp.status_code != 200:
            print(f"  ERROR: {resp.status_code} — {resp.text}")
            sys.exit(1)

        result = resp.json()
        total_inserted += result["inserted"]
        total_updated += result["updated"]
        total_skipped += result["skipped"]

    print()
    print(f"Done! Inserted: {total_inserted}, Updated: {total_updated}, Skipped: {total_skipped}")


if __name__ == "__main__":
    main()
