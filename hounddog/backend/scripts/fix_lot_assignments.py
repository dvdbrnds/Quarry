"""
One-time fix: sync lot_assignment on all active permits to match their permit type's
lot_assignments config (comma-joined).

SILENT OPERATION — no emails, no notifications, no webhooks, no student-facing changes.
Only the lot_assignment display value changes. Permit status, payment, access unchanged.

Run from backend dir:  python -m scripts.fix_lot_assignments
Or from container:     python -m scripts.fix_lot_assignments
"""

import asyncio
import logging
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import select  # noqa: E402
from app.database import async_session  # noqa: E402
from app.models.permit import Permit  # noqa: E402
from app.models.permit_type import PermitType  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

DRY_RUN = "--dry-run" in sys.argv


async def main():
    async with async_session() as db:
        pt_result = await db.execute(select(PermitType).where(PermitType.is_active.is_(True)))
        permit_types = pt_result.scalars().all()

        canonical: dict[str, str] = {}
        for pt in permit_types:
            lots = list(pt.lot_assignments or [])
            joined = ", ".join(lots) if lots else ""
            canonical[pt.code] = joined
            logger.info("Tier %-30s canonical lots = %s", pt.code, joined)

        result = await db.execute(select(Permit).where(Permit.status == "active"))
        all_permits = result.scalars().all()
        logger.info("Found %d active permits to check", len(all_permits))

        fixed = 0
        skipped = 0

        for p in all_permits:
            expected = canonical.get(p.permit_type, "")
            if not expected:
                skipped += 1
                continue

            current = (p.lot_assignment or "").strip()
            if current == expected:
                continue

            old = p.lot_assignment
            p.lot_assignment = expected
            logger.info(
                "Fixed %-8s (%-30s %s): '%s' -> '%s'",
                p.permit_number, p.name, p.permit_type, old, expected,
            )
            fixed += 1

        if DRY_RUN:
            logger.info("DRY RUN — no changes committed. Would have fixed %d permits. %d skipped (no config).", fixed, skipped)
        else:
            await db.commit()
            logger.info("Done. Fixed %d permits. %d skipped (no config).", fixed, skipped)


if __name__ == "__main__":
    asyncio.run(main())
