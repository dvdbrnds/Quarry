#!/usr/bin/env python3
"""Migrate lots.json to HoundDog API."""

import argparse
import json
import sys

import httpx


def main():
    parser = argparse.ArgumentParser(description="Import lots.json into HoundDog")
    parser.add_argument("file", help="Path to lots.json")
    parser.add_argument("--url", default="http://localhost:8000", help="HoundDog API base URL")
    parser.add_argument("--dry-run", action="store_true", help="Parse and validate only")
    args = parser.parse_args()

    with open(args.file) as f:
        lots_raw = json.load(f)

    if not isinstance(lots_raw, list):
        lots_raw = lots_raw.get("lots", [])

    print(f"Found {len(lots_raw)} lot entries")

    if args.dry_run:
        for lot in lots_raw:
            name = lot.get("name", "unnamed")
            boundary = lot.get("boundary", [])
            print(f"  {name}: {len(boundary)} boundary points")
        print("Dry run -- skipping API calls")
        return

    created = 0
    errors = 0
    for lot in lots_raw:
        name = lot.get("name", "")
        boundary_raw = lot.get("boundary", [])
        boundary = []
        for coord in boundary_raw:
            if isinstance(coord, dict):
                boundary.append({
                    "latitude": coord.get("latitude", coord.get("lat", 0)),
                    "longitude": coord.get("longitude", coord.get("lng", coord.get("lon", 0))),
                })
            elif isinstance(coord, (list, tuple)) and len(coord) >= 2:
                boundary.append({"latitude": coord[0], "longitude": coord[1]})

        try:
            resp = httpx.post(
                f"{args.url}/api/lots",
                json={"name": name, "boundary": boundary},
                timeout=30,
            )
            resp.raise_for_status()
            created += 1
            print(f"  Created: {name}")
        except httpx.HTTPStatusError as e:
            errors += 1
            print(f"  Failed: {name} -- {e.response.status_code}: {e.response.text}")

    print(f"\nDone: {created} created, {errors} errors")


if __name__ == "__main__":
    main()
