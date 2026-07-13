"""
SIS / Colleague subscriber sync.

Pulls student/staff directory from the SIS API and upserts into
alert_subscribers. Adds synced subscribers to appropriate groups based
on role/classification fields from the SIS data.
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx
from sqlalchemy import select, func

from ..config import settings
from ..database import async_session
from ..models.alert_subscriber import AlertSubscriber
from ..models.subscriber_group import SubscriberGroup, subscriber_group_members

logger = logging.getLogger("quarry.sis_sync")

_last_sync_at: datetime | None = None
_last_sync_count: int = 0


async def sync_subscribers():
    """Fetch directory from SIS and upsert into subscribers + groups."""
    global _last_sync_at, _last_sync_count

    if not settings.sis_subscriber_sync_enabled:
        return

    url = settings.sis_subscriber_sync_url
    key = settings.sis_subscriber_sync_key
    if not url:
        logger.warning("SIS sync enabled but no URL configured")
        return

    logger.info("Starting SIS subscriber sync from %s", url)

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        resp.raise_for_status()
        records = resp.json()

    if not isinstance(records, list):
        records = records.get("data", records.get("results", []))

    async with async_session() as db:
        async with db.begin():
            group_cache: dict[str, uuid.UUID] = {}
            existing_groups = await db.execute(select(SubscriberGroup))
            for g in existing_groups.scalars().all():
                group_cache[g.name.lower()] = g.id

            synced = 0
            for record in records:
                email = record.get("email", "").strip().lower()
                if not email:
                    continue

                phone = record.get("phone", "").strip()
                name = record.get("name", "").strip()
                role = record.get("role", "student").strip().lower()

                result = await db.execute(
                    select(AlertSubscriber).where(AlertSubscriber.email == email)
                )
                subscriber = result.scalar_one_or_none()

                if subscriber:
                    if phone and not subscriber.phone:
                        subscriber.phone = phone
                    if name and not subscriber.name:
                        subscriber.name = name
                else:
                    subscriber = AlertSubscriber(
                        email=email,
                        phone=phone,
                        name=name,
                        email_opt_in=True,
                        sms_opt_in=bool(phone),
                    )
                    db.add(subscriber)
                    await db.flush()
                    await db.refresh(subscriber)

                role_groups = _map_role_to_groups(role, record)
                for group_name in role_groups:
                    gn_lower = group_name.lower()
                    if gn_lower not in group_cache:
                        new_group = SubscriberGroup(
                            name=group_name,
                            description=f"Auto-created from SIS sync ({role})",
                            group_type="sis_auto",
                        )
                        db.add(new_group)
                        await db.flush()
                        await db.refresh(new_group)
                        group_cache[gn_lower] = new_group.id

                    group_id = group_cache[gn_lower]
                    existing_member = await db.execute(
                        select(subscriber_group_members).where(
                            subscriber_group_members.c.subscriber_id == subscriber.id,
                            subscriber_group_members.c.group_id == group_id,
                        )
                    )
                    if not existing_member.first():
                        await db.execute(
                            subscriber_group_members.insert().values(
                                subscriber_id=subscriber.id,
                                group_id=group_id,
                            )
                        )

                synced += 1

            _last_sync_at = datetime.now(timezone.utc)
            _last_sync_count = synced
            logger.info("SIS sync complete: %d records processed", synced)


def _map_role_to_groups(role: str, record: dict) -> list[str]:
    """Map a SIS role/classification to subscriber group names."""
    groups = ["All Campus"]

    if role in ("student", "undergraduate"):
        groups.append("All Students")
        classification = record.get("classification", "").lower()
        if classification in ("freshman", "first_year"):
            groups.append("First Year Students")
        elif classification == "sophomore":
            groups.append("Sophomore Students")
        elif classification == "junior":
            groups.append("Junior Students")
        elif classification == "senior":
            groups.append("Senior Students")

        if record.get("is_residential"):
            groups.append("Residential Students")
        if record.get("is_commuter"):
            groups.append("Commuter Students")

    elif role in ("graduate", "grad"):
        groups.extend(["All Students", "Graduate Students"])

    elif role in ("faculty", "staff", "employee"):
        groups.append("Faculty & Staff")

    return groups


def get_sync_status() -> dict:
    return {
        "enabled": settings.sis_subscriber_sync_enabled,
        "sync_url": settings.sis_subscriber_sync_url,
        "last_sync_at": _last_sync_at.isoformat() if _last_sync_at else None,
        "total_synced": _last_sync_count,
    }
