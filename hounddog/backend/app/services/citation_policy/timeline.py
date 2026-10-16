"""Pure citation-policy math. No database access, so every rule here is unit-testable.

All dates are America/New_York calendar dates. "Elapsed" always means effective elapsed
days: calendar days since the timeline start, minus days spent paused.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

V2 = "v2"
LEGACY = "legacy"

LATE_FEE_1 = "LATE_FEE_1"
LATE_FEE_2 = "LATE_FEE_2"
BARNACLE_DEPLOYMENT = "BARNACLE_DEPLOYMENT"
BARNACLE_DAMAGE = "BARNACLE_DAMAGE"
OWNER_NOTIFICATION = "OWNER_NOTIFICATION"
COLLECTION_COST = "COLLECTION_COST"
LATE_FEE_TYPES = (LATE_FEE_1, LATE_FEE_2)
BARNACLE_FEE_TYPES = (BARNACLE_DEPLOYMENT, BARNACLE_DAMAGE)
FEE_TYPES = (LATE_FEE_1, LATE_FEE_2, BARNACLE_DEPLOYMENT, BARNACLE_DAMAGE, OWNER_NOTIFICATION, COLLECTION_COST)

NOTICE_REMINDER = "REMINDER"
NOTICE_DELINQUENCY_1 = "DELINQUENCY_1"
NOTICE_FINAL = "FINAL"
NOTICE_BARNACLE_WARNING = "BARNACLE_WARNING"
NOTICE_ROLLOUT = "ROLLOUT"

STAGE_CURRENT = "current"
STAGE_DELINQUENT = "delinquent"
STAGE_FINAL = "final"

PAUSE_APPEAL = "appeal"
PAUSE_APPEAL_GRACE = "appeal_grace"
PAUSE_PAYMENT_PLAN = "payment_plan"

UNPAID_EXCLUDED_STATUSES = ("paid", "voided", "resolved_permit", "warning", "expired_magistrate")

BARNACLE_WARNING_SENTENCE = (
    "Your vehicle may be immobilized with a Barnacle on or after {date} if your qualifying "
    "unpaid citations remain unresolved. Actual deployment will result in an additional $100 fee."
)


@dataclass(frozen=True)
class PolicyConfig:
    effective_date: date | None = None
    legacy_deadline: date | None = None
    reminder_day: int = 7
    due_day: int = 10
    late_fee_1_day: int = 11
    late_fee_2_day: int = 31
    late_fee_1: Decimal = Decimal("15.00")
    late_fee_2: Decimal = Decimal("20.00")
    late_fee_cap: Decimal = Decimal("35.00")
    denied_grace_days: int = 10
    owner_notification_fee: Decimal = Decimal("25.00")
    job_hour: int = 6
    barnacle_enabled: bool = False
    barnacle_min_citations: int = 3
    barnacle_delinquent_days: int = 30
    barnacle_warning_wait_days: int = 10
    barnacle_lookahead_days: int = 10
    barnacle_fee: Decimal = Decimal("100.00")
    removal_phone_daytime: str = ""
    removal_phone_after_hours: str = ""

    @property
    def active(self) -> bool:
        return self.effective_date is not None

    @classmethod
    def from_settings(cls, es, env_barnacle_enabled: bool) -> "PolicyConfig":
        if es is None:
            return cls()
        return cls(
            effective_date=es.policy_effective_date,
            legacy_deadline=es.legacy_resolution_deadline,
            reminder_day=es.policy_reminder_day,
            due_day=es.policy_due_day,
            late_fee_1_day=es.policy_late_fee_1_day,
            late_fee_2_day=es.policy_late_fee_2_day,
            late_fee_1=Decimal(es.late_fee_1_amount),
            late_fee_2=Decimal(es.late_fee_2_amount),
            late_fee_cap=Decimal(es.late_fee_cap),
            denied_grace_days=es.denied_appeal_grace_days,
            owner_notification_fee=Decimal(es.owner_notification_fee),
            job_hour=es.policy_job_hour,
            barnacle_enabled=bool(env_barnacle_enabled and es.barnacle_enabled),
            barnacle_min_citations=es.barnacle_min_citations,
            barnacle_delinquent_days=es.barnacle_delinquent_days,
            barnacle_warning_wait_days=es.barnacle_warning_wait_days,
            barnacle_lookahead_days=es.barnacle_warning_lookahead_days,
            barnacle_fee=Decimal(es.barnacle_deployment_fee),
            removal_phone_daytime=es.removal_phone_daytime or "",
            removal_phone_after_hours=es.removal_phone_after_hours or "",
        )


@dataclass(frozen=True)
class Pause:
    start: date
    end: date | None = None  # exclusive; None = still open
    floor_elapsed: int | None = None
    reason: str = PAUSE_APPEAL


# ── Rollout ────────────────────────────────────────────────────────────────

def policy_assignment(issued_on: date, cfg: PolicyConfig) -> tuple[str | None, date | None]:
    """(policy_version, timeline_start_date) for a citation issued on issued_on."""
    if cfg.effective_date is None:
        return None, None
    if issued_on >= cfg.effective_date:
        return V2, issued_on
    return LEGACY, cfg.legacy_deadline


def on_timeline(policy_version: str | None, timeline_start: date | None, today: date) -> bool:
    return policy_version in (V2, LEGACY) and timeline_start is not None and today >= timeline_start


def appeal_deadline(issued_on: date, cfg: PolicyConfig) -> date:
    """Last calendar day a v2 citation can be appealed (inclusive)."""
    return issued_on + timedelta(days=cfg.due_day)


# ── Clock ──────────────────────────────────────────────────────────────────

def effective_elapsed_days(start: date, today: date, pauses: Iterable[Pause]) -> int:
    """Calendar days from start to today, skipping paused days.

    When a pause with floor_elapsed ends, elapsed jumps to at least that value (denied-appeal
    grace ends at the delinquency stage).
    """
    if today <= start:
        return 0
    elapsed = 0
    cursor = start
    for p in sorted(pauses, key=lambda p: p.start):
        p_start = max(p.start, cursor)
        if p_start >= today:
            break
        elapsed += (p_start - cursor).days
        if p.end is None or p.end > today:
            return elapsed
        cursor = max(cursor, p.end)
        if p.floor_elapsed is not None:
            elapsed = max(elapsed, p.floor_elapsed)
    if today > cursor:
        elapsed += (today - cursor).days
    return elapsed


def active_pause(today: date, pauses: Iterable[Pause]) -> Pause | None:
    for p in pauses:
        if p.start <= today and (p.end is None or p.end > today):
            return p
    return None


def delinquent_days(elapsed: int, cfg: PolicyConfig) -> int | None:
    """Effective days delinquent (0 on the delinquency day), or None if not yet delinquent."""
    if elapsed < cfg.late_fee_1_day:
        return None
    return elapsed - cfg.late_fee_1_day


def stage_for(elapsed: int, cfg: PolicyConfig) -> str:
    if elapsed >= cfg.late_fee_2_day:
        return STAGE_FINAL
    if elapsed >= cfg.late_fee_1_day:
        return STAGE_DELINQUENT
    return STAGE_CURRENT


def fees_due(elapsed: int, cfg: PolicyConfig) -> list[str]:
    due = []
    if elapsed >= cfg.late_fee_1_day:
        due.append(LATE_FEE_1)
    if elapsed >= cfg.late_fee_2_day:
        due.append(LATE_FEE_2)
    return due


def notice_due(elapsed: int, cfg: PolicyConfig) -> str | None:
    """The one notice for the citation's current stage. Earlier-stage notices are not sent late
    (a citation first seen on day 35 gets the final notice, not a stale reminder)."""
    if elapsed >= cfg.late_fee_2_day:
        return NOTICE_FINAL
    if elapsed >= cfg.late_fee_1_day:
        return NOTICE_DELINQUENCY_1
    if elapsed >= cfg.reminder_day:
        return NOTICE_REMINDER
    return None


def late_fee_amount(fee_type: str, existing_late_fees: Decimal, cfg: PolicyConfig) -> Decimal:
    """Amount to charge for a late fee given non-voided late fees already on the citation.
    The cap is a hard limit regardless of schedule."""
    base = cfg.late_fee_1 if fee_type == LATE_FEE_1 else cfg.late_fee_2
    room = cfg.late_fee_cap - existing_late_fees
    return max(Decimal("0.00"), min(base, room))


def next_escalation(elapsed: int, today: date, cfg: PolicyConfig) -> tuple[str, date] | None:
    """Next scheduled step and its date, assuming no new pauses."""
    if elapsed < cfg.late_fee_1_day:
        return "delinquent", today + timedelta(days=cfg.late_fee_1_day - elapsed)
    if elapsed < cfg.late_fee_2_day:
        return "final", today + timedelta(days=cfg.late_fee_2_day - elapsed)
    return None


# ── Barnacle eligibility ───────────────────────────────────────────────────

@dataclass
class CitationState:
    ticket_id: str
    plate_state: str | None
    unpaid: bool
    on_timeline: bool
    elapsed: int
    paused_reason: str | None = None


@dataclass
class WarningRecord:
    ticket_ids: set[str]
    sent_on: date | None  # None = generated but not yet delivered (e.g. waiting to be mailed)
    earliest_date: date | None = None


@dataclass
class Eligibility:
    eligible: bool
    reasons: list[str]
    conditions: dict[str, bool]
    qualifying_ticket_ids: list[str]
    earliest_date: date | None
    warning_sent_on: date | None
    should_issue_warning: bool
    warning_candidates: list[str] = field(default_factory=list)


def _delinquent_on(c: CitationState, today: date, cfg: PolicyConfig) -> date:
    return today - timedelta(days=c.elapsed - cfg.late_fee_1_day)


def _candidates(citations: Iterable[CitationState]) -> list[CitationState]:
    """Citations that can ever count: unpaid, on the timeline, known state, not paused."""
    return [
        c for c in citations
        if c.unpaid and c.on_timeline and c.plate_state and c.paused_reason is None
    ]


def valid_warning(
    warnings: Iterable[WarningRecord], ticket_ids: set[str], cfg: PolicyConfig, *, sent_only: bool
) -> WarningRecord | None:
    """Most recent warning that covers at least min_citations of the given citations."""
    best = None
    for w in warnings:
        if sent_only and w.sent_on is None:
            continue
        if len(w.ticket_ids & ticket_ids) < cfg.barnacle_min_citations:
            continue
        if best is None or (w.sent_on or date.max) > (best.sent_on or date.max):
            best = w
    return best


def barnacle_eligibility(
    citations: Iterable[CitationState],
    warnings: Iterable[WarningRecord],
    balance: Decimal,
    today: date,
    cfg: PolicyConfig,
) -> Eligibility:
    citations = list(citations)
    warnings = list(warnings)
    reasons: list[str] = []
    candidates = _candidates(citations)

    qualifying = [c for c in candidates if c.elapsed >= cfg.late_fee_1_day]
    qualifying.sort(key=lambda c: -c.elapsed)
    q_ids = {c.ticket_id for c in qualifying}

    missing_state = [c for c in citations if c.unpaid and c.on_timeline and not c.plate_state]
    paused = [c for c in citations if c.unpaid and c.on_timeline and c.paused_reason]

    cond1 = len(qualifying) >= cfg.barnacle_min_citations
    if not cond1:
        msg = (f"Only {len(qualifying)} delinquent qualifying citation(s); "
               f"{cfg.barnacle_min_citations} required.")
        if paused:
            msg += f" {len(paused)} excluded (pending appeal, appeal grace, or payment plan)."
        if missing_state:
            msg += f" {len(missing_state)} excluded for missing plate state."
        reasons.append(msg)

    oldest_days = delinquent_days(qualifying[0].elapsed, cfg) if qualifying else None
    cond2 = oldest_days is not None and oldest_days >= cfg.barnacle_delinquent_days
    if not cond2:
        reasons.append(
            f"Oldest qualifying citation delinquent {oldest_days or 0} effective day(s); "
            f"{cfg.barnacle_delinquent_days} required."
        )

    sent_warning = valid_warning(warnings, q_ids, cfg, sent_only=True) if cond1 else None
    cond3 = sent_warning is not None
    if not cond3:
        pending = valid_warning(warnings, q_ids, cfg, sent_only=False) if cond1 else None
        if pending is not None and pending.sent_on is None:
            reasons.append("Final warning generated but not yet delivered (mail notices count once marked mailed).")
        else:
            reasons.append("No Barnacle final warning covering the qualifying citations has been sent.")

    cond4_wait = bool(sent_warning and sent_warning.sent_on
                      and today >= sent_warning.sent_on + timedelta(days=cfg.barnacle_warning_wait_days))
    if sent_warning and not cond4_wait:
        reasons.append(
            f"Warning sent {sent_warning.sent_on.isoformat()}; "
            f"{cfg.barnacle_warning_wait_days} days must pass."
        )
    if balance <= 0:
        reasons.append("Balance is resolved.")
    cond4 = cond4_wait and balance > 0

    # Earliest date: when conditions 1 and 2 would both hold (no new pauses), and warning + wait.
    conditions_date = None
    delinquent_dates = sorted(_delinquent_on(c, today, cfg) for c in candidates)
    if len(delinquent_dates) >= cfg.barnacle_min_citations:
        cond1_date = delinquent_dates[cfg.barnacle_min_citations - 1]
        cond2_date = delinquent_dates[0] + timedelta(days=cfg.barnacle_delinquent_days)
        conditions_date = max(cond1_date, cond2_date, today if cond1 and cond2 else date.min)

    lookahead_end = today + timedelta(days=cfg.barnacle_lookahead_days)
    warning_candidates = sorted(
        c.ticket_id for c in candidates if _delinquent_on(c, today, cfg) <= lookahead_end
    )
    existing_any = valid_warning(warnings, set(warning_candidates), cfg, sent_only=False)
    should_issue = bool(
        conditions_date is not None and conditions_date <= lookahead_end and existing_any is None
        and len(warning_candidates) >= cfg.barnacle_min_citations and balance > 0
    )

    earliest = None
    if conditions_date is not None:
        warn_on = sent_warning.sent_on if sent_warning else (
            existing_any.sent_on if existing_any and existing_any.sent_on else today
        )
        earliest = max(conditions_date, warn_on + timedelta(days=cfg.barnacle_warning_wait_days))

    eligible = cond1 and cond2 and cond3 and cond4
    return Eligibility(
        eligible=eligible,
        reasons=[] if eligible else reasons,
        conditions={
            "min_delinquent_citations": cond1,
            "oldest_delinquent_days": cond2,
            "final_warning_sent": cond3,
            "warning_wait_and_unresolved": cond4,
        },
        qualifying_ticket_ids=[c.ticket_id for c in qualifying],
        earliest_date=earliest,
        warning_sent_on=sent_warning.sent_on if sent_warning else None,
        should_issue_warning=should_issue,
        warning_candidates=warning_candidates,
    )


def removal_allowed(balance: Decimal, override_reason: str | None) -> tuple[bool, str]:
    if balance <= 0:
        return True, "balance_zero"
    if override_reason and override_reason.strip():
        return True, "supervisor_override"
    return False, f"Outstanding balance ${balance:.2f}; removal requires a zero balance or a supervisor override."


# ── Money ──────────────────────────────────────────────────────────────────

def processing_fee_cents(total_cents: int, pct: float, fixed_cents: int) -> int:
    if total_cents <= 0:
        return 0
    return round(total_cents * pct / 100) + fixed_cents


def allocate(amount: Decimal, items: list[tuple[str, Decimal]]) -> list[tuple[str, Decimal]]:
    """Apply amount to (key, outstanding) items in order. Returns (key, applied) for each item touched."""
    out = []
    remaining = amount
    for key, outstanding in items:
        if remaining <= 0:
            break
        if outstanding <= 0:
            continue
        applied = min(outstanding, remaining)
        out.append((key, applied))
        remaining -= applied
    return out
