#!/usr/bin/env python3
"""
Convert Report Exec XLSX export to a bundled JSON file for the Bird Dog iOS app.

Usage:
    python3 scripts/convert_permits.py "All Parking Permits.xlsx"

Output:
    BirdDog/Resources/permits.json
"""

import json
import sys
import os
from datetime import datetime

try:
    import openpyxl
except ImportError:
    print("Installing openpyxl...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "openpyxl"])
    import openpyxl


def normalize_plate(text: str) -> str:
    """Match the iOS app's PlatePatternMatcher.normalize() logic."""
    result = text.upper()
    for ch in " -.*#@©®™()[]{}:;'\",=+|!?•·●°":
        result = result.replace(ch, "")
    cyrillic_map = {
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H",
        "К": "K", "М": "M", "О": "O", "Р": "P", "Т": "T",
        "У": "Y", "Х": "X",
    }
    result = "".join(cyrillic_map.get(c, c) for c in result)
    return result


def parse_lot_zone(location: str) -> str:
    if " : " in location:
        return location.split(" : ")[-1].strip()
    if location.startswith("_"):
        return location[1:].strip()
    return location.strip()


def build_vehicle_desc(year: str, color: str, make: str, model: str) -> str:
    parts = [p.strip() for p in [year, color, make, model] if p.strip() and p.strip() != "UNKNOWN"]
    return " ".join(parts)


def build_owner_name(owner: str, first: str, last: str) -> str:
    cleaned = owner.strip().strip(",").strip()
    if cleaned and cleaned != "UNKNOWN":
        return cleaned
    f = first.strip()
    l = last.strip()
    if f and f != "UNKNOWN" and l and l != "UNKNOWN":
        return f"{f} {l}"
    if l and l != "UNKNOWN":
        return l
    if f and f != "UNKNOWN":
        return f
    return ""


def convert(xlsx_path: str, output_path: str):
    wb = openpyxl.load_workbook(xlsx_path, read_only=True)
    ws = wb["Sheet1"]

    rows = list(ws.iter_rows(values_only=True))
    headers = [str(h).strip() if h else "" for h in rows[0]]
    col = {name: idx for idx, name in enumerate(headers)}

    required = ["Plate", "Status", "Permit Number"]
    for r in required:
        if r not in col:
            print(f"ERROR: Missing required column: {r}")
            sys.exit(1)

    def get(row, name):
        idx = col.get(name)
        if idx is None or idx >= len(row):
            return ""
        val = row[idx]
        return str(val).strip() if val else ""

    deduped = {}
    stats = {"total_rows": 0, "skipped_no_plate": 0, "skipped_duplicate": 0}

    for row in rows[1:]:
        stats["total_rows"] += 1
        plate_raw = get(row, "Plate")
        if not plate_raw:
            stats["skipped_no_plate"] += 1
            continue

        status = get(row, "Status")
        if status not in ("Valid", "Expired"):
            continue

        plates = [p.strip() for p in plate_raw.split(",")]
        states = [s.strip() for s in get(row, "Plate State").split(",")]

        owner_name = build_owner_name(
            get(row, "Owner"), get(row, "First Name"), get(row, "Last Name")
        )
        lot_zone = parse_lot_zone(get(row, "Location"))
        vehicle_desc = build_vehicle_desc(
            get(row, "Vehicle Year"), get(row, "Vehicle Color"),
            get(row, "Vehicle Make"), get(row, "Vehicle Model")
        )
        record_date = get(row, "Record Date")
        expiration_date = get(row, "Expiration Date")
        permit_number = get(row, "Permit Number")
        contact_type = get(row, "Contact Type")

        for i, plate in enumerate(plates):
            plate = plate.strip()
            if not plate:
                continue
            state = states[i] if i < len(states) else (states[-1] if states else "")
            normalized = normalize_plate(plate)
            if not normalized:
                continue

            entry = {
                "plateNormalized": normalized,
                "plateRaw": plate,
                "plateState": state,
                "ownerName": owner_name,
                "permitNumber": permit_number,
                "permitType": contact_type,
                "permitStatus": status,
                "lotZone": lot_zone,
                "vehicleDescription": vehicle_desc,
                "issuedDate": record_date,
                "expirationDate": expiration_date if expiration_date else None,
            }

            if normalized in deduped:
                existing = deduped[normalized]
                # Prefer Valid over Expired, then newer issued date
                if existing["permitStatus"] == "Valid" and status != "Valid":
                    stats["skipped_duplicate"] += 1
                    continue
                if existing["permitStatus"] != "Valid" and status == "Valid":
                    stats["skipped_duplicate"] += 1
                    deduped[normalized] = entry
                    continue
                if record_date > existing["issuedDate"]:
                    deduped[normalized] = entry
                stats["skipped_duplicate"] += 1
            else:
                deduped[normalized] = entry

    permits = sorted(deduped.values(), key=lambda x: x["issuedDate"], reverse=True) if hasattr(deduped, 'values') else sorted(deduped.values(), key=lambda x: x["issuedDate"], reverse=True)

    valid_count = sum(1 for p in permits if p["permitStatus"] == "Valid")
    expired_count = sum(1 for p in permits if p["permitStatus"] == "Expired")

    output = {
        "generatedAt": datetime.now().isoformat(),
        "source": os.path.basename(xlsx_path),
        "stats": {
            "totalRows": stats["total_rows"],
            "importedCount": len(permits),
            "validCount": valid_count,
            "expiredCount": expired_count,
            "skippedNoPlate": stats["skipped_no_plate"],
            "skippedDuplicate": stats["skipped_duplicate"],
        },
        "permits": permits,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, separators=(",", ":"))

    print(f"Converted {stats['total_rows']} rows -> {len(permits)} unique plates")
    print(f"  Valid: {valid_count}")
    print(f"  Expired: {expired_count}")
    print(f"  Skipped (no plate): {stats['skipped_no_plate']}")
    print(f"  Skipped (duplicate): {stats['skipped_duplicate']}")
    print(f"  Output: {output_path}")
    print(f"  Size: {os.path.getsize(output_path) / 1024:.1f} KB")

    wb.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <xlsx_file>")
        sys.exit(1)

    xlsx_file = sys.argv[1]
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(script_dir)
    output_file = os.path.join(project_root, "BirdDog", "Resources", "permits.json")

    convert(xlsx_file, output_file)
