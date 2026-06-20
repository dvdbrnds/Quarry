#!/usr/bin/env python3
"""Import violation types and permit types from a fixture JSON file.

Usage:
    python -m scripts.import_fixtures scripts/fixtures/moravian.json

Run from the hounddog/ directory.
"""

import asyncio
import json
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.app.database import engine, get_db, Base
from backend.app.models import ViolationType, PermitType


async def main(fixture_path: str):
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy import select

    with open(fixture_path) as f:
        data = json.load(f)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSession(engine) as db:
        # Import violation types
        vtypes = data.get("violation_types", [])
        vt_created = 0
        vt_updated = 0
        for row in vtypes:
            result = await db.execute(
                select(ViolationType).where(ViolationType.code == row["code"])
            )
            existing = result.scalar()

            if existing:
                existing.label = row["label"]
                existing.category = row.get("category", "parking")
                existing.fine_first = Decimal(str(row["fine_first"]))
                existing.fine_second = Decimal(str(row["fine_second"])) if row.get("fine_second") else None
                existing.fine_third_plus = Decimal(str(row["fine_third_plus"])) if row.get("fine_third_plus") else None
                existing.sort_order = row.get("sort_order", 0)
                existing.is_active = True
                vt_updated += 1
            else:
                vtype = ViolationType(
                    code=row["code"],
                    label=row["label"],
                    category=row.get("category", "parking"),
                    fine_first=Decimal(str(row["fine_first"])),
                    fine_second=Decimal(str(row["fine_second"])) if row.get("fine_second") else None,
                    fine_third_plus=Decimal(str(row["fine_third_plus"])) if row.get("fine_third_plus") else None,
                    sort_order=row.get("sort_order", 0),
                )
                db.add(vtype)
                vt_created += 1

        # Import permit types
        ptypes = data.get("permit_types", [])
        pt_created = 0
        pt_updated = 0
        for row in ptypes:
            result = await db.execute(
                select(PermitType).where(PermitType.code == row["code"])
            )
            existing = result.scalar()

            if existing:
                existing.label = row["label"]
                existing.eligible = row.get("eligible", "")
                existing.price = Decimal(str(row["price"]))
                existing.max_capacity = row.get("max_capacity", 0)
                existing.valid_days = row.get("valid_days", 365)
                existing.lot_assignments = row.get("lot_assignments", [])
                existing.time_restriction = row.get("time_restriction")
                existing.is_purchasable_online = row.get("is_purchasable_online", False)
                existing.sort_order = row.get("sort_order", 0)
                existing.is_active = True
                pt_updated += 1
            else:
                ptype = PermitType(
                    code=row["code"],
                    label=row["label"],
                    eligible=row.get("eligible", ""),
                    price=Decimal(str(row["price"])),
                    max_capacity=row.get("max_capacity", 0),
                    valid_days=row.get("valid_days", 365),
                    lot_assignments=row.get("lot_assignments", []),
                    time_restriction=row.get("time_restriction"),
                    is_purchasable_online=row.get("is_purchasable_online", False),
                    sort_order=row.get("sort_order", 0),
                )
                db.add(ptype)
                pt_created += 1

        await db.commit()

    print(f"Violation types: {vt_created} created, {vt_updated} updated")
    print(f"Permit types: {pt_created} created, {pt_updated} updated")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m scripts.import_fixtures <fixture.json>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
