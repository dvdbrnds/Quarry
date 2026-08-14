"""Unit tests for bulk partial refund eligibility math."""

from decimal import Decimal

from app.services.bulk_refund import (
    evaluate_transaction,
    parse_money,
    proposed_refund,
    refund_idempotency_key,
)


def test_flat_hundred_on_full_charge():
    proposed, reason = proposed_refund(
        "flat", Decimal("100"), Decimal("250.00"), Decimal("0"),
    )
    assert reason is None
    assert proposed == Decimal("100.00")


def test_percent_of_original():
    proposed, reason = proposed_refund(
        "percent", Decimal("50"), Decimal("200.00"), Decimal("0"),
    )
    assert reason is None
    assert proposed == Decimal("100.00")


def test_skip_when_exceeds_refundable_balance():
    proposed, reason = proposed_refund(
        "flat", Decimal("100"), Decimal("200.00"), Decimal("120.00"),
    )
    assert proposed is None
    assert "exceeds refundable balance" in (reason or "")


def test_skip_already_fully_refunded():
    proposed, reason = proposed_refund(
        "flat", Decimal("100"), Decimal("100.00"), Decimal("100.00"),
    )
    assert proposed is None
    assert reason == "already fully refunded"


def test_skip_zero_amount():
    proposed, reason = proposed_refund(
        "flat", Decimal("0"), Decimal("100.00"), Decimal("0"),
    )
    assert proposed is None
    assert reason == "refund amount is zero"


def test_percent_over_100_skipped():
    proposed, reason = proposed_refund(
        "percent", Decimal("150"), Decimal("100.00"), Decimal("0"),
    )
    assert proposed is None
    assert "100" in (reason or "")


def test_evaluate_skips_non_succeeded():
    row = evaluate_transaction(
        txn_id="ch_abc",
        status="pending",
        original=Decimal("100"),
        already_refunded=Decimal("0"),
        mode="flat",
        amount=Decimal("50"),
    )
    assert row["eligible"] is False
    assert "not a successful charge" in row["skip_reason"]


def test_evaluate_eligible_flat():
    row = evaluate_transaction(
        txn_id="ch_abc",
        status="succeeded",
        original=Decimal("250"),
        already_refunded=Decimal("0"),
        mode="flat",
        amount=Decimal("100"),
        customer_email="student@moravian.edu",
    )
    assert row["eligible"] is True
    assert row["proposed"] == "100.00"
    assert row["refundable"] == "250.00"


def test_retry_skips_successes_already_refunded():
    """After a $100 refund posts, retrying the same $100 on a now-fully-applied
    $100 charge is skipped instead of creating a second refund."""
    row = evaluate_transaction(
        txn_id="ch_abc",
        status="succeeded",
        original=Decimal("100.00"),
        already_refunded=Decimal("100.00"),
        mode="flat",
        amount=Decimal("100"),
    )
    assert row["eligible"] is False
    assert row["skip_reason"] == "already fully refunded"


def test_idempotency_key_stable_per_txn_and_cents():
    a = refund_idempotency_key("ch_abc", 10000)
    b = refund_idempotency_key("ch_abc", 10000)
    c = refund_idempotency_key("ch_abc", 5000)
    d = refund_idempotency_key("pi_other", 10000)
    assert a == b
    assert a != c
    assert a != d
    assert a.startswith("bulk-refund:ch_abc:10000")


def test_parse_money_rounds_to_cents():
    assert parse_money("100.456") == Decimal("100.46")
    assert parse_money(100) == Decimal("100.00")


def test_dedupe_collapses_charge_pi_and_session():
    from datetime import datetime, timezone
    from app.services.bulk_refund import dedupe_stripe_rows

    ts = datetime(2026, 8, 8, 19, 13, tzinfo=timezone.utc).isoformat()
    rows = [
        {"id": "cs_1", "source": "checkout_session", "customer_email": "a@mu.edu",
         "amount": "250.00", "created": ts, "payment_intent_id": "pi_1"},
        {"id": "pi_1", "source": "payment_intent", "customer_email": "a@mu.edu",
         "amount": "250.00", "created": ts, "payment_intent_id": "pi_1"},
        {"id": "ch_1", "source": "charge", "customer_email": "a@mu.edu",
         "amount": "250.00", "created": ts, "payment_intent_id": "pi_1"},
    ]
    out = dedupe_stripe_rows(rows)
    assert len(out) == 1
    assert out[0]["id"] == "ch_1"


def test_dedupe_keeps_distinct_students():
    from datetime import datetime, timezone
    from app.services.bulk_refund import dedupe_stripe_rows

    ts = datetime(2026, 8, 8, 19, 13, tzinfo=timezone.utc).isoformat()
    rows = [
        {"id": "ch_1", "source": "charge", "customer_email": "a@mu.edu",
         "amount": "250.00", "created": ts},
        {"id": "ch_2", "source": "charge", "customer_email": "b@mu.edu",
         "amount": "250.00", "created": ts},
    ]
    out = dedupe_stripe_rows(rows)
    assert {r["id"] for r in out} == {"ch_1", "ch_2"}
