"""
One-time fix: normalize lot_assignment on all permits to clean lot codes.

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

        canonical: dict[str, list[str]] = {}
        for pt in permit_types:
            lots = list(pt.lot_assignments or [])
            canonical[pt.code] = lots
            logger.info("Tier %-30s canonical lots = %s", pt.code, lots)

        result = await db.execute(select(Permit).where(Permit.status == "active"))
        all_permits = result.scalars().all()
        logger.info("Found %d active permits to check", len(all_permits))

        fixed = 0
        manual_review = 0

        for p in all_permits:
            tier_lots = canonical.get(p.permit_type, [])
            if not tier_lots:
                continue

            current = (p.lot_assignment or "").strip()

            if current in tier_lots:
                continue

            # For single-lot tiers, always set to that code
            if len(tier_lots) == 1:
                old = p.lot_assignment
                p.lot_assignment = tier_lots[0]
                logger.info(
                    "Fixed %-8s (%-30s %s): '%s' -> '%s' (single-lot tier)",
                    p.permit_number, p.name, p.permit_type, old, tier_lots[0],
                )
                fixed += 1
                continue

            # Multi-lot tier: try to match a lot code embedded in the messy value
            matched_lot = None
            for lot_code in tier_lots:
                if lot_code in current:
                    matched_lot = lot_code
                    break

            if matched_lot:
                old = p.lot_assignment
                p.lot_assignment = matched_lot
                logger.info(
                    "Fixed %-8s (%-30s %s): '%s' -> '%s'",
                    p.permit_number, p.name, p.permit_type, old, matched_lot,
                )
                fixed += 1
            else:
                logger.warning(
                    "MANUAL REVIEW: %-8s (%-30s %s): '%s' -- could not determine correct lot from %s",
                    p.permit_number, p.name, p.permit_type, current, tier_lots,
                )
                manual_review += 1

        if DRY_RUN:
            logger.info("DRY RUN — no changes committed. Would have fixed %d permits. %d need manual review.", fixed, manual_review)
        else:
            await db.commit()
            logger.info("Done. Fixed %d permits. %d need manual review.", fixed, manual_review)


if __name__ == "__main__":
    asyncio.run(main())
