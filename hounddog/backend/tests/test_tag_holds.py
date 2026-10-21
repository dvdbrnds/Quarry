"""Vehicle tags count toward holds like permits once tied to a student (real Postgres).

Destroys and recreates every table in TEST_DATABASE_URL. Skipped unless it is set:
    TEST_DATABASE_URL=postgresql+asyncpg://localhost/quarry_policy_test pytest tests/test_tag_holds.py
"""

import asyncio
import os
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

BEFORE_CUTOFF = datetime(2026, 9, 1, tzinfo=timezone.utc)
AFTER_CUTOFF = datetime(2026, 10, 15, tzinfo=timezone.utc)


@pytest.fixture
def factory(monkeypatch):
    from app.database import Base
    import app.models  # noqa: F401
    from app.services import escalation, sis_hold_service

    jenzabar = []

    async def fake_set(mid, apply):
        jenzabar.append((mid, apply))
        return True

    async def noop(*a, **k):
        return None

    async def no_check(mid):
        return None

    monkeypatch.setattr(sis_hold_service, "set_jenzabar_hold", fake_set)
    monkeypatch.setattr(sis_hold_service, "check_jenzabar_hold", no_check)
    monkeypatch.setattr(escalation, "_notify_student_of_hold", noop)
    monkeypatch.setattr(escalation, "_notify_admin_of_hold", noop)
    monkeypatch.setattr(escalation, "_create_conduct_referral", noop)

    engine = create_async_engine(DB_URL, poolclass=NullPool)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            for table, ddl in (
                ("hold_exemptions", """id UUID PRIMARY KEY DEFAULT gen_random_uuid(), plate VARCHAR(32),
                    email VARCHAR(256), expires_at TIMESTAMPTZ NOT NULL"""),
                ("escalation_log", """id UUID PRIMARY KEY DEFAULT gen_random_uuid(), student_id VARCHAR(50) NOT NULL,
                    student_name VARCHAR(255), student_email VARCHAR(255), plate VARCHAR(50),
                    escalation_type VARCHAR(50) NOT NULL, ticket_count INTEGER NOT NULL, ticket_ids TEXT,
                    status VARCHAR(50) DEFAULT 'sent', details TEXT, created_at TIMESTAMP DEFAULT NOW(),
                    resolved_at TIMESTAMP, resolved_by VARCHAR(255)"""),
            ):
                await conn.execute(text(f"DROP TABLE IF EXISTS {table}"))
                await conn.execute(text(f"CREATE TABLE {table} ({ddl})"))

    asyncio.run(setup())
    f = async_sessionmaker(engine, expire_on_commit=False)
    f.jenzabar = jenzabar
    yield f
    asyncio.run(engine.dispose())


def run(coro):
    return asyncio.run(coro)


def tag(plate, created_at=BEFORE_CUTOFF, **kw):
    from app.models import Permit
    return Permit(
        name=kw.pop("name", "Tag Owner"), plates=[plate], email=kw.pop("email", ""), phone="", student_id="",
        permit_type="vehicle_tag", status="active", lot_assignment="", is_tag_only=True,
        created_at=created_at, **kw,
    )


def permit(plate, student_id, email, moravian_id):
    from app.models import Permit
    return Permit(
        name="Student", plates=[plate], email=email, phone="", student_id=student_id,
        permit_type="resident", status="active", lot_assignment="U", is_tag_only=False, moravian_id=moravian_id,
    )


def tickets(plate, n):
    from app.models import Ticket
    now = datetime.now(timezone.utc)
    return [Ticket(plate=plate, lot="Lot X", violation_type="no_permit", fine_amount=Decimal("35"),
                   officer_id="o", issued_at=now, status="issued") for _ in range(n)]


async def seed(factory, *objs):
    async with factory() as db, db.begin():
        for o in objs:
            db.add_all(o if isinstance(o, list) else [o])


async def escalate(factory, plate):
    from sqlalchemy import select
    from app.models import Permit
    from app.services.escalation import check_and_escalate, resolve_escalation_student_id

    async with factory() as db, db.begin():
        p = (await db.execute(
            select(Permit).where(Permit.plates.any(plate)).order_by(Permit.is_tag_only.asc())
        )).scalars().first()
        sid = await resolve_escalation_student_id(db, p)
        if not sid:
            return None, {}
        return sid, await check_and_escalate(db, plate, sid, p.name, p.email)


async def summary(factory, mid):
    from app.routers.conduct import _jenzabar_hold_summary
    async with factory() as db:
        return await _jenzabar_hold_summary(db, mid, live=False)


def test_tag_with_moravian_id_counts_without_verification(factory):
    run(seed(factory, tag("ZVB88S", name="MICHAEL G MCGOVERN", moravian_id="509867"), tickets("ZVB88S", 3)))
    sid, actions = run(escalate(factory, "ZVB88S"))
    assert sid == "509867"
    assert actions.get("registration_hold") and factory.jenzabar == [("509867", True)]
    s = run(summary(factory, "509867"))
    assert s["student_ids"] and s["unpaid_tickets"] == 3 and s["quarry_hold_active"]


def test_old_email_only_tag_still_needs_verification(factory):
    run(seed(factory, tag("OLD1", email="someone@moravian.edu"), tickets("OLD1", 4)))
    sid, actions = run(escalate(factory, "OLD1"))
    assert sid is None and not actions and factory.jenzabar == []


def test_new_email_tag_counts(factory):
    run(seed(factory, tag("NEW1", created_at=AFTER_CUTOFF, email="New@Moravian.edu"), tickets("NEW1", 3)))
    sid, actions = run(escalate(factory, "NEW1"))
    assert sid == "new@moravian.edu"
    assert actions.get("registration_hold")


def test_tag_tickets_add_to_students_permit(factory):
    run(seed(
        factory,
        permit("PERM1", "00uSTUDENT", "kid@moravian.edu", "555111"),
        tag("TAG1", moravian_id="555111"),
        tickets("PERM1", 1), tickets("TAG1", 2),
    ))
    sid, actions = run(escalate(factory, "TAG1"))
    assert sid == "00uSTUDENT"
    assert actions.get("unpaid_count") == 3 and actions.get("registration_hold")
    s = run(summary(factory, "555111"))
    assert s["unpaid_tickets"] == 3


def test_payment_lifts_hold_for_tag(factory):
    from sqlalchemy import update
    from app.models import Ticket
    from app.services.escalation import check_and_resolve_on_payment

    run(seed(factory, tag("PAY1", moravian_id="600600"), tickets("PAY1", 3)))
    run(escalate(factory, "PAY1"))

    async def pay_one():
        async with factory() as db, db.begin():
            t = (await db.execute(Ticket.__table__.select().where(Ticket.plate == "PAY1").limit(1))).first()
            await db.execute(update(Ticket).where(Ticket.id == t.id).values(status="paid"))
            await check_and_resolve_on_payment(db, "PAY1")

    run(pay_one())
    assert not run(summary(factory, "600600"))["quarry_hold_active"]
    assert ("600600", False) in factory.jenzabar
