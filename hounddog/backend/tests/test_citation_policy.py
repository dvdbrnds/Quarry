"""Citation Policy v2 timeline, fee, and Barnacle eligibility rules (see BUSINESS_RULES.md).

Pure-function tests; the database-backed job tests live in test_citation_policy_job.py.
"""

from datetime import date, timedelta
from decimal import Decimal

from app.services.citation_policy import timeline as tl
from app.services.citation_policy.timeline import CitationState, Pause, PolicyConfig, WarningRecord

D = date(2026, 9, 1)
CFG = PolicyConfig(effective_date=date(2026, 8, 1), legacy_deadline=date(2026, 9, 15))
BCFG = PolicyConfig(effective_date=date(2026, 8, 1), barnacle_enabled=True)


def day(n: int) -> date:
    return D + timedelta(days=n)


# ── Rollout ────────────────────────────────────────────────────────────────

def test_policy_inactive_without_effective_date():
    assert tl.policy_assignment(D, PolicyConfig()) == (None, None)


def test_pre_effective_date_citation_is_legacy_starting_at_deadline():
    assert tl.policy_assignment(date(2026, 7, 31), CFG) == (tl.LEGACY, date(2026, 9, 15))
    assert not tl.on_timeline(tl.LEGACY, date(2026, 9, 15), date(2026, 9, 14))
    assert tl.on_timeline(tl.LEGACY, date(2026, 9, 15), date(2026, 9, 15))


def test_post_effective_date_citation_is_v2_from_issue_day():
    assert tl.policy_assignment(date(2026, 8, 1), CFG) == (tl.V2, date(2026, 8, 1))


def test_no_fees_before_legacy_citation_enters_timeline():
    # A legacy citation with no timeline start yet is never on the timeline.
    assert not tl.on_timeline(tl.LEGACY, None, day(100))
    assert not tl.on_timeline(None, None, day(100))


# ── Stages and fees ────────────────────────────────────────────────────────

def test_stage_boundaries():
    assert tl.stage_for(10, CFG) == tl.STAGE_CURRENT
    assert tl.stage_for(11, CFG) == tl.STAGE_DELINQUENT
    assert tl.stage_for(30, CFG) == tl.STAGE_DELINQUENT
    assert tl.stage_for(31, CFG) == tl.STAGE_FINAL


def test_fees_due_by_day():
    assert tl.fees_due(10, CFG) == []
    assert tl.fees_due(11, CFG) == [tl.LATE_FEE_1]
    assert tl.fees_due(31, CFG) == [tl.LATE_FEE_1, tl.LATE_FEE_2]


def test_notice_due_only_current_stage():
    assert tl.notice_due(6, CFG) is None
    assert tl.notice_due(7, CFG) == tl.NOTICE_REMINDER
    assert tl.notice_due(11, CFG) == tl.NOTICE_DELINQUENCY_1
    assert tl.notice_due(35, CFG) == tl.NOTICE_FINAL


def test_late_fee_cap_is_35():
    assert tl.late_fee_amount(tl.LATE_FEE_1, Decimal("0"), CFG) == Decimal("15.00")
    assert tl.late_fee_amount(tl.LATE_FEE_2, Decimal("15.00"), CFG) == Decimal("20.00")
    assert tl.late_fee_amount(tl.LATE_FEE_2, Decimal("30.00"), CFG) == Decimal("5.00")
    assert tl.late_fee_amount(tl.LATE_FEE_2, Decimal("35.00"), CFG) == Decimal("0.00")


def test_next_escalation():
    assert tl.next_escalation(5, day(5), CFG) == ("delinquent", day(11))
    assert tl.next_escalation(20, day(20), CFG) == ("final", day(31))
    assert tl.next_escalation(31, day(31), CFG) is None


# ── Clock: appeals, grace, plans ───────────────────────────────────────────

def test_elapsed_without_pauses():
    assert tl.effective_elapsed_days(D, D, []) == 0
    assert tl.effective_elapsed_days(D, day(11), []) == 11


def test_appeal_pause_stops_and_resumes_clock():
    open_pause = [Pause(start=day(5))]
    assert tl.effective_elapsed_days(D, day(40), open_pause) == 5
    closed = [Pause(start=day(5), end=day(25))]
    assert tl.effective_elapsed_days(D, day(25), closed) == 5
    assert tl.effective_elapsed_days(D, day(31), closed) == 11


def test_denied_appeal_grace_then_delinquent_on_day_11():
    # Appealed day 3, denied day 20 with 10-day grace: pause [day 3, day 31) with floor 11.
    pauses = [
        Pause(start=day(3), end=day(20), reason=tl.PAUSE_APPEAL),
        Pause(start=day(20), end=day(31), floor_elapsed=11, reason=tl.PAUSE_APPEAL_GRACE),
    ]
    assert tl.effective_elapsed_days(D, day(30), pauses) == 3
    assert tl.stage_for(tl.effective_elapsed_days(D, day(30), pauses), CFG) == tl.STAGE_CURRENT
    assert tl.effective_elapsed_days(D, day(31), pauses) == 11
    assert tl.stage_for(11, CFG) == tl.STAGE_DELINQUENT
    assert tl.effective_elapsed_days(D, day(32), pauses) == 12


def test_grace_floor_does_not_reduce_elapsed():
    pauses = [Pause(start=day(15), end=day(26), floor_elapsed=11)]
    assert tl.effective_elapsed_days(D, day(26), pauses) == 15


def test_payment_plan_suspends_then_default_resumes():
    plan = [Pause(start=day(12), reason=tl.PAUSE_PAYMENT_PLAN)]
    assert tl.effective_elapsed_days(D, day(60), plan) == 12
    assert tl.active_pause(day(60), plan) is not None
    defaulted = [Pause(start=day(12), end=day(60), reason=tl.PAUSE_PAYMENT_PLAN)]
    assert tl.active_pause(day(60), defaulted) is None
    assert tl.effective_elapsed_days(D, day(79), defaulted) == 31


def test_appeal_deadline_is_10_days():
    assert tl.appeal_deadline(D, CFG) == day(10)


def _t(issued, sent, email="s@moravian.edu"):
    from types import SimpleNamespace
    return SimpleNamespace(issued_at=issued, email_sent_at=sent, notification_email=email,
                           policy_version="legacy", timeline_start_date=None)


def test_appeal_window_counts_from_late_email():
    from datetime import datetime, timezone
    from app.services.citation_policy.service import appeal_deadline
    issued = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
    resent = datetime(2026, 10, 16, 21, 0, tzinfo=timezone.utc)
    cfg = PolicyConfig()
    assert appeal_deadline(_t(issued, issued), cfg, 5)[0] == issued + timedelta(days=5)
    assert appeal_deadline(_t(issued, resent), cfg, 5)[0] == resent + timedelta(days=5)
    assert appeal_deadline(_t(issued, None), cfg, 5)[0] > datetime.now(timezone.utc)
    assert appeal_deadline(_t(issued, None, email=None), cfg, 5)[0] == issued + timedelta(days=5)
    old = datetime(2026, 8, 1, tzinfo=timezone.utc)
    assert appeal_deadline(_t(old, None), cfg, 5)[0] == old + timedelta(days=5)


# ── Barnacle eligibility ───────────────────────────────────────────────────

def cit(tid: str, elapsed: int, *, state="PA", unpaid=True, paused=None) -> CitationState:
    return CitationState(ticket_id=tid, plate_state=state, unpaid=unpaid, on_timeline=True,
                         elapsed=elapsed, paused_reason=paused)


def eligible_set():
    today = day(100)
    cits = [cit("a", 45), cit("b", 20), cit("c", 15)]
    warn = [WarningRecord(ticket_ids={"a", "b", "c"}, sent_on=today - timedelta(days=10))]
    return cits, warn, Decimal("150.00"), today


def test_barnacle_all_conditions_met():
    cits, warn, bal, today = eligible_set()
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert e.eligible, e.reasons
    assert e.reasons == []
    assert all(e.conditions.values())


def test_barnacle_fails_with_only_two_delinquent():
    cits, warn, bal, today = eligible_set()
    cits[2] = cit("c", 10)
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert not e.eligible
    assert not e.conditions["min_delinquent_citations"]


def test_barnacle_paused_citation_does_not_count():
    cits, warn, bal, today = eligible_set()
    cits[2] = cit("c", 15, paused=tl.PAUSE_APPEAL)
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert not e.conditions["min_delinquent_citations"]
    assert "excluded" in e.reasons[0]


def test_barnacle_missing_plate_state_does_not_count():
    cits, warn, bal, today = eligible_set()
    cits[2] = cit("c", 15, state=None)
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert not e.conditions["min_delinquent_citations"]
    assert "plate state" in e.reasons[0]


def test_barnacle_fails_when_oldest_not_30_days_delinquent():
    cits, warn, bal, today = eligible_set()
    cits[0] = cit("a", 40)  # delinquent 29 days
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert not e.eligible
    assert not e.conditions["oldest_delinquent_days"]
    assert e.conditions["min_delinquent_citations"]


def test_barnacle_fails_without_sent_warning():
    cits, _, bal, today = eligible_set()
    e = tl.barnacle_eligibility(cits, [], bal, today, BCFG)
    assert not e.conditions["final_warning_sent"]
    unmailed = [WarningRecord(ticket_ids={"a", "b", "c"}, sent_on=None)]
    e = tl.barnacle_eligibility(cits, unmailed, bal, today, BCFG)
    assert not e.conditions["final_warning_sent"]
    assert any("not yet delivered" in r for r in e.reasons)


def test_barnacle_warning_must_cover_min_citations():
    cits, _, bal, today = eligible_set()
    warn = [WarningRecord(ticket_ids={"a", "b", "zzz"}, sent_on=today - timedelta(days=20))]
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert not e.conditions["final_warning_sent"]


def test_barnacle_fails_before_10_day_wait():
    cits, _, bal, today = eligible_set()
    warn = [WarningRecord(ticket_ids={"a", "b", "c"}, sent_on=today - timedelta(days=9))]
    e = tl.barnacle_eligibility(cits, warn, bal, today, BCFG)
    assert e.conditions["final_warning_sent"]
    assert not e.conditions["warning_wait_and_unresolved"]
    assert e.earliest_date == today + timedelta(days=1)


def test_barnacle_fails_with_zero_balance():
    cits, warn, _, today = eligible_set()
    e = tl.barnacle_eligibility(cits, warn, Decimal("0"), today, BCFG)
    assert not e.eligible
    assert "Balance is resolved." in e.reasons


def test_barnacle_earliest_date_and_warning_lookahead():
    today = day(100)
    # Delinquent on: a = today-25, b = today+3, c = today+5.
    cits = [cit("a", 36), cit("b", 8), cit("c", 6)]
    e = tl.barnacle_eligibility(cits, [], Decimal("90"), today, BCFG)
    assert not e.eligible
    # Third citation delinquent today+5; oldest hits 30 delinquent days today+5; warning today + 10.
    assert e.earliest_date == today + timedelta(days=10)
    assert e.should_issue_warning
    assert e.warning_candidates == ["a", "b", "c"]


def test_barnacle_no_duplicate_warning():
    today = day(100)
    cits = [cit("a", 36), cit("b", 8), cit("c", 6)]
    warn = [WarningRecord(ticket_ids={"a", "b", "c"}, sent_on=None)]
    e = tl.barnacle_eligibility(cits, warn, Decimal("90"), today, BCFG)
    assert not e.should_issue_warning


def test_barnacle_no_warning_beyond_lookahead():
    today = day(100)
    cits = [cit("a", 36), cit("b", 8), cit("c", -10)]  # c delinquent in 21 days
    e = tl.barnacle_eligibility(cits, [], Decimal("90"), today, BCFG)
    assert not e.should_issue_warning


def test_warning_sentence_is_verbatim():
    assert tl.BARNACLE_WARNING_SENTENCE.format(date="October 30, 2026") == (
        "Your vehicle may be immobilized with a Barnacle on or after October 30, 2026 if your "
        "qualifying unpaid citations remain unresolved. Actual deployment will result in an "
        "additional $100 fee."
    )


# ── Removal and money ──────────────────────────────────────────────────────

def test_removal_blocked_with_balance():
    ok, why = tl.removal_allowed(Decimal("25.00"), None)
    assert not ok and "$25.00" in why
    assert tl.removal_allowed(Decimal("0"), None) == (True, "balance_zero")
    assert tl.removal_allowed(Decimal("25.00"), "Chief approved") == (True, "supervisor_override")
    assert not tl.removal_allowed(Decimal("25.00"), "   ")[0]


def test_processing_fee_on_full_total():
    assert tl.processing_fee_cents(0, 2.9, 30) == 0
    assert tl.processing_fee_cents(13500, 2.9, 30) == 392 + 30


def test_allocate_oldest_first():
    items = [("t1", Decimal("50")), ("f1", Decimal("15")), ("t2", Decimal("50"))]
    assert tl.allocate(Decimal("60"), items) == [("t1", Decimal("50")), ("f1", Decimal("10"))]
    assert tl.allocate(Decimal("0"), items) == []


def test_flag_requires_both_keys():
    class ES:
        pass
    es = ES()
    for k, v in dict(
        policy_effective_date=None, legacy_resolution_deadline=None, policy_reminder_day=7,
        policy_due_day=10, policy_late_fee_1_day=11, policy_late_fee_2_day=31,
        late_fee_1_amount=15, late_fee_2_amount=20, late_fee_cap=35, denied_appeal_grace_days=10,
        owner_notification_fee=25, policy_job_hour=6, barnacle_enabled=True,
        barnacle_min_citations=3, barnacle_delinquent_days=30, barnacle_warning_wait_days=10,
        barnacle_warning_lookahead_days=10, barnacle_deployment_fee=100,
        removal_phone_daytime=None, removal_phone_after_hours=None,
    ).items():
        setattr(es, k, v)
    assert not PolicyConfig.from_settings(es, env_barnacle_enabled=False).barnacle_enabled
    assert PolicyConfig.from_settings(es, env_barnacle_enabled=True).barnacle_enabled
    es.barnacle_enabled = False
    assert not PolicyConfig.from_settings(es, env_barnacle_enabled=True).barnacle_enabled
