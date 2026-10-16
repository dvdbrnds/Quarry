"""Daily citation-policy job against a real Postgres database.

Destroys and recreates every table in TEST_DATABASE_URL. Skipped unless it is set:
    createdb quarry_policy_test
    TEST_DATABASE_URL=postgresql+asyncpg://localhost/quarry_policy_test pytest tests/test_citation_policy_job.py
"""

import asyncio
import os
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

DB_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

TZ = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 16)
EFFECTIVE = date(2026, 9, 1)
LEGACY_DEADLINE = date(2026, 11, 1)


def issued(d: date) -> datetime:
    return datetime.combine(d, time(12, 0), TZ)


@pytest.fixture
def env(monkeypatch):
    from app.database import Base
    import app.models  # noqa: F401
    from app.services import email
    from app.services.citation_policy import job

    sent = []

    async def fake_send(to, subject, html, text=None, **kw):
        sent.append((tuple(to), subject))
        return True

    monkeypatch.setattr(email, "send_email", fake_send)
    monkeypatch.setattr(job, "now_local", lambda: datetime.combine(TODAY, time(23, 0), TZ))

    engine = create_async_engine(DB_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            await conn.execute(text("DROP TABLE IF EXISTS hold_exemptions"))
            await conn.execute(text("""
                CREATE TABLE hold_exemptions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), plate VARCHAR(32), email VARCHAR(256),
                    reason TEXT NOT NULL DEFAULT '', created_by VARCHAR(256) NOT NULL DEFAULT 'system',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(), expires_at TIMESTAMPTZ NOT NULL,
                    lifted_existing_at TIMESTAMPTZ, expiry_processed_at TIMESTAMPTZ
                )
            """))

    asyncio.run(setup())
    yield factory, sent
    asyncio.run(engine.dispose())


def run(coro):
    return asyncio.run(coro)


async def seed(factory, **tickets):
    from app.models import EnforcementSettings, Ticket

    async with factory() as db, db.begin():
        db.add(EnforcementSettings(
            id=1, policy_effective_date=EFFECTIVE, legacy_resolution_deadline=LEGACY_DEADLINE,
        ))
        ids = {}
        for name, kw in tickets.items():
            t = Ticket(
                id=uuid.uuid4(), ticket_number=name.upper(), lot="A", officer_id="o1",
                fine_amount=Decimal("50.00"), status="issued", **kw,
            )
            db.add(t)
            ids[name] = t.id
    return ids


async def counts(factory):
    from app.models.audit_log import AuditLog
    from app.models.citation_policy import CitationFee, CitationNotice, MupdReview

    async with factory() as db:
        fees = (await db.execute(select(CitationFee))).scalars().all()
        notices = (await db.execute(select(CitationNotice))).scalars().all()
        mupd = (await db.execute(select(func.count()).select_from(MupdReview))).scalar()
        audits = (await db.execute(
            select(func.count()).select_from(AuditLog).where(AuditLog.endpoint == "citation-policy")
        )).scalar()
    return fees, notices, mupd, audits


def test_job_idempotent_and_capped(env):
    from app.services.citation_policy.job import run_daily_job

    factory, sent = env
    run(seed(factory, final=dict(
        plate="ABC123", plate_state="PA", issued_at=issued(date(2026, 9, 10)),
        notification_email="student@moravian.edu",
    )))

    first = run(run_daily_job(factory, today=TODAY))
    assert first["LATE_FEE_1"] == 1 and first["LATE_FEE_2"] == 1
    fees, notices, mupd, _ = run(counts(factory))
    assert sorted((f.fee_type, f.amount) for f in fees) == [
        ("LATE_FEE_1", Decimal("15.00")), ("LATE_FEE_2", Decimal("20.00")),
    ]
    assert [n.notice_type for n in notices] == ["FINAL"]
    assert notices[0].status == "sent"
    assert len(sent) == 1

    # Same day again: the run marker short-circuits.
    assert run(run_daily_job(factory, today=TODAY)) is None
    # Forced reruns (and the next day) still never duplicate fees or notices.
    run(run_daily_job(factory, force=True, today=TODAY))
    run(run_daily_job(factory, today=TODAY + timedelta(days=1)))
    fees2, notices2, mupd2, _ = run(counts(factory))
    assert len(fees2) == 2 and len(notices2) == 1 and mupd2 == mupd
    assert sum(f.amount for f in fees2) == Decimal("35.00")
    assert len(sent) == 1


def test_no_fees_before_legacy_deadline_and_rollout_once(env):
    from app.models import Ticket
    from app.services.citation_policy.job import run_daily_job

    factory, sent = env
    ids = run(seed(factory, old=dict(
        plate="OLD1", plate_state="PA", issued_at=issued(date(2026, 5, 1)),
        notification_email="old@moravian.edu",
    ), old2=dict(
        plate="OLD1", plate_state="PA", issued_at=issued(date(2026, 6, 1)),
        notification_email="old@moravian.edu",
    )))
    run(run_daily_job(factory, today=TODAY))
    run(run_daily_job(factory, force=True, today=TODAY))
    fees, notices, _, _ = run(counts(factory))
    assert fees == []
    assert [n.notice_type for n in notices] == ["ROLLOUT"]
    assert len(notices[0].ticket_ids) == 2

    async def t():
        async with factory() as db:
            return await db.get(Ticket, ids["old"])
    old = run(t())
    assert old.policy_version == "legacy" and old.timeline_start_date == LEGACY_DEADLINE


def test_paused_citation_gets_nothing_and_dismissal_voids_fees(env):
    from app.models import Ticket
    from app.models.citation_policy import CitationClockPause, CitationFee
    from app.services.citation_policy.job import run_daily_job
    from app.services.citation_policy.service import record_appeal_decision

    factory, _ = env
    ids = run(seed(factory,
        appealed=dict(plate="P1", plate_state="PA", issued_at=issued(date(2026, 9, 10)),
                      notification_email="a@moravian.edu"),
        late=dict(plate="P2", plate_state="PA", issued_at=issued(date(2026, 9, 20)),
                  notification_email="b@moravian.edu"),
    ))

    async def pause():
        async with factory() as db, db.begin():
            db.add(CitationClockPause(
                ticket_id=ids["appealed"], reason="appeal", start_date=date(2026, 9, 13), created_by="t",
            ))
    run(pause())
    run(run_daily_job(factory, today=TODAY))

    fees, _, _, _ = run(counts(factory))
    by_ticket = {}
    async def links():
        from app.models.citation_policy import CitationFeeTicket
        async with factory() as db:
            return (await db.execute(select(CitationFeeTicket.ticket_id, CitationFeeTicket.fee_id))).all()
    for tid, fid in run(links()):
        by_ticket.setdefault(tid, []).append(fid)
    assert ids["appealed"] not in by_ticket
    assert len(by_ticket[ids["late"]]) == 1  # 26 days: late fee 1 only

    async def dismiss():
        async with factory() as db, db.begin():
            t = await db.get(Ticket, ids["late"])
            await record_appeal_decision(db, t, "approved", "tester", "signage missing")
    run(dismiss())
    fees, _, _, _ = run(counts(factory))
    assert [f.status for f in fees] == ["voided"]


def test_payment_plan_default_resumes_clock(env):
    from app.models.citation_policy import (
        CitationClockPause, PaymentPlan, PaymentPlanCitation, PaymentPlanInstallment,
    )
    from app.services.citation_policy.job import run_daily_job

    factory, _ = env
    ids = run(seed(factory, planned=dict(
        plate="PL1", plate_state="PA", issued_at=issued(date(2026, 9, 10)),
        notification_email="p@moravian.edu",
    )))
    plan_id = uuid.uuid4()

    async def plan():
        async with factory() as db, db.begin():
            db.add(PaymentPlan(id=plan_id, payer_name="P", status="active", created_by="t"))
            await db.flush()
            db.add(PaymentPlanCitation(plan_id=plan_id, ticket_id=ids["planned"]))
            db.add(PaymentPlanInstallment(plan_id=plan_id, due_date=TODAY - timedelta(days=1),
                                          amount=Decimal("25.00")))
            db.add(CitationClockPause(ticket_id=ids["planned"], reason="payment_plan",
                                      start_date=date(2026, 9, 15), plan_id=plan_id, created_by="t"))
    run(plan())
    result = run(run_daily_job(factory, today=TODAY))
    assert result["plans_defaulted"] == 1

    async def state():
        async with factory() as db:
            p = await db.get(PaymentPlan, plan_id)
            pauses = (await db.execute(select(CitationClockPause))).scalars().all()
            return p.status, [x.end_date for x in pauses]
    status, ends = run(state())
    assert status == "defaulted"
    assert ends == [TODAY]


def test_non_affiliated_delinquent_flagged_for_mupd_once(env):
    from app.services.citation_policy.job import run_daily_job

    factory, _ = env
    run(seed(factory, visitor=dict(
        plate="VIS1", plate_state="NJ", issued_at=issued(date(2026, 9, 20)),
        owner_address="1 Main St, Easton PA",
    )))
    run(run_daily_job(factory, today=TODAY))
    run(run_daily_job(factory, force=True, today=TODAY))
    _, notices, mupd, _ = run(counts(factory))
    assert mupd == 1
    assert notices[0].channel == "mail" and notices[0].status == "pending"
