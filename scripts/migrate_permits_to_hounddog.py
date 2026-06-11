#!/usr/bin/env python3
"""Migrate permits.json to HoundDog API via bulk import."""

import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description="Import permits.json into HoundDog")
    parser.add_argument("file", help="Path to permits.json")
    parser.add_argument("--url", default="http://localhost:8000", help="HoundDog API base URL")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only")
    args = parser.parse_args()

    with open(args.file) as f:
        data = json.load(f)

    permits_raw = data.get("permits", data if isinstance(data, list) else [])
    print(f"Found {len(permits_raw)} permit entries")

    rows = []
    for p in permits_raw:
        plate = p.get("plateNormalized", p.get("plate_normalized", "")).strip()
        if not plate:
            continue
        rows.append({
            "plate_normalized": plate,
            "plate_raw": p.get("plateRaw", p.get("plate_raw", "")),
            "plate_state": p.get("plateState", p.get("plate_state", "")),
            "owner_name": p.get("ownerName", p.get("owner_name", "")),
            "permit_number": p.get("permitNumber", p.get("permit_number", "")),
            "permit_type": p.get("permitType", p.get("permit_type", "student")),
            "permit_status": p.get("permitStatus", p.get("permit_status", "active")),
            "lot_zone": p.get("lotZone", p.get("lot_zone", "")),
            "vehicle_description": p.get("vehicleDescription", p.get("vehicle_description", "")),
            "issued_date": p.get("issuedDate", p.get("issued_date")),
            "expiration_date": p.get("expirationDate", p.get("expiration_date")),
        })

    print(f"Prepared {len(rows)} valid plates for import")

    if args.dry_run:
        print("Dry run -- skipping API call")
        return

    resp = httpx.post(
        f"{args.url}/api/permits/import",
        json={"permits": rows},
        timeout=120,
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"Import complete: {result['inserted']} inserted, {result['updated']} updated, {result['skipped']} skipped")


if __name__ == "__main__":
    main()
