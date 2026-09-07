"""Auto-retire vehicle tags when a real permit is created for the same plate.

When someone purchases a permit, any existing vehicle_tag records matching
one of the permit's plates are soft-deleted. The tag data (owner info, notes)
is preserved in the database for audit but won't sync to BirdDog anymore.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.permit import Permit

logger = logging.getLogger("quarry.tag_upgrade")


async def retire_tags_for_plates(db: AsyncSession, plates: list[str]) -> int:
    """Soft-delete active vehicle tags whose plates overlap with the given list.

    Returns the number of tags retired.
    """
    if not plates:
        return 0

    normalized = [p.strip().upper().replace(" ", "").replace("-", "") for p in plates if p.strip()]
    if not normalized:
        return 0

    result = await db.execute(
        select(Permit).where(
            Permit.is_tag_only.is_(True),
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )
    tags = result.scalars().all()

    retired = 0
    now = datetime.now(timezone.utc)
    for tag in tags:
        tag_plates = {p.strip().upper().replace(" ", "").replace("-", "") for p in (tag.plates or [])}
        if tag_plates & set(normalized):
            tag.deleted_at = now
            tag.status = "retired"
            tag.cancel_reason = "permit_purchased"
            retired += 1
            logger.info(
                "Retired vehicle tag %s (plates=%s) — permit purchased for overlapping plate",
                tag.id, tag.plates,
            )

    if retired:
        await db.flush()

    return retired
