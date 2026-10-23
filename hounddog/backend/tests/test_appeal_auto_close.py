"""Paying or voiding a ticket closes its pending appeal and open committee case (real Postgres).

Destroys and recreates every table in TEST_DATABASE_URL. Skipped unless it is set:
    TEST_DATABASE_URL=postgresql+asyncpg://localhost/quarry_policy_test pytest tests/test_appeal_auto_close.py
"""

import asyncio
import os
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")


@pytest.fixture
def factory():
    from app.database import Base
    import app.models  # noqa: F401

    engine = create_async_engine(DB_URL, poolclass=NullPool)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    yield async_sessionmaker(engine, expire_on_commit=False)
    asyncio.run(engine.dispose())


def _ticket(**kw):
    from app.models.ticket import Ticket
    base = dict(plate="ABC123", lot="A", fine_amount=Decimal("50.00"), status="appealed",
                appeal_note="not mine", appeal_decision="pending")
    base.update(kw)
    return Ticket(**base)


def _run(factory, status, **kw):
    from app.models.ticket import Ticket

    async def go():
        async with factory() as db:
            t = _ticket(**kw)
            db.add(t)
            await db.commit()
            t.status = status
            await db.commit()
        async with factory() as db:
            return await db.get(Ticket, t.id)

    return asyncio.run(go())


def test_paid_closes_pending_appeal(factory):
    t = _run(factory, "paid")
    assert t.appeal_decision == "closed"
    assert t.appeal_decided_by == "system"
    assert "paid" in t.appeal_decision_reason


def test_voided_closes_open_committee_case(factory):
    t = _run(factory, "voided", committee_status="voting")
    assert t.appeal_decision == "closed"
    assert t.committee_status == "decided"
    assert t.committee_decision == "closed"


def test_unresolved_status_leaves_appeal_pending(factory):
    t = _run(factory, "pending_payment")
    assert t.appeal_decision == "pending"


def test_decided_appeal_is_not_overwritten(factory):
    t = _run(factory, "voided", appeal_decision="approved")
    assert t.appeal_decision == "approved"
