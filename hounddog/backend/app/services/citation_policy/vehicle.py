"""Per-citation clock state and per-vehicle (plate + issuing state) Barnacle eligibility."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...models.citation_policy import (
    BarnacleDeployment, CitationNotice, PaymentPlan, PaymentPlanCitation,
)
from ...models.permit import Permit
from ...models.ticket import Ticket
from ..timeutils import today_local
from . import timeline as tl
from .service import (
    balance_for_tickets, create_fee, load_pauses, local_date, norm_plate, norm_state,
    person_balance, record_policy_event, ticket_is_unpaid, ticket_policy, tickets_for_plates,
)

ACTIVE_DEPLOYMENT_STATUSES = ("deployed", "removal_requested")


def citation_state(
    t: Ticket, pauses: list[tl.Pause], cfg: tl.PolicyConfig, today: date,
) -> tuple[tl.CitationState, date | None]:
    """Clock state for one citation, plus its timeline start."""
    version, start = ticket_policy(t, cfg)
    on = tl.on_timeline(version, start, today) and t.ticket_category in (None, "parking")
    elapsed = tl.effective_elapsed_days(start, today, pauses) if on else 0
    ap = tl.active_pause(today, pauses)
    paused_reason = ap.reason if ap else None
    if paused_reason is None and t.appeal_decision == "pending":
        paused_reason = tl.PAUSE_APPEAL
    return tl.CitationState(
        ticket_id=str(t.id),
        plate_state=norm_state(t.plate_state),
        unpaid=ticket_is_unpaid(t),
        on_timeline=on,
        elapsed=elapsed,
        paused_reason=paused_reason,
    ), start


async def warnings_for_vehicle(db: AsyncSession, plate: str, plate_state: str) -> list[tuple[CitationNotice, tl.WarningRecord]]:
    rows = (await db.execute(
        select(CitationNotice).where(
            CitationNotice.notice_type == tl.NOTICE_BARNACLE_WARNING,
            CitationNotice.plate == norm_plate(plate),
            CitationNotice.plate_state == plate_state,
            CitationNotice.status != "cancelled",
        ).order_by(CitationNotice.created_at)
    )).scalars().all()
    return [
        (n, tl.WarningRecord(
            ticket_ids=set(n.ticket_ids or []),
            sent_on=local_date(n.sent_at) if n.status == "sent" else None,
            earliest_date=n.earliest_date,
        ))
        for n in rows
    ]


async def vehicle_eligibility(
    db: AsyncSession, plate: str, plate_state: str | None, cfg: tl.PolicyConfig, today: date | None = None,
) -> dict:
    today = today or today_local()
    state = norm_state(plate_state)
    all_tickets = await tickets_for_plates(db, [plate])
    vehicle_tickets = [t for t in all_tickets if norm_state(t.plate_state) == state] if state else []
    stateless = [t for t in all_tickets if not norm_state(t.plate_state)]
    considered = vehicle_tickets + stateless
    pauses = await load_pauses(db, [t.id for t in considered])

    states = []
    rows = []
    for t in considered:
        cs, start = citation_state(t, pauses.get(t.id, []), cfg, today)
        states.append(cs)
        rows.append((t, cs, start))

    warnings = await warnings_for_vehicle(db, plate, state) if state else []
    balance = await balance_for_tickets(db, vehicle_tickets)
    elig = tl.barnacle_eligibility(states, [w for _, w in warnings], balance, today, cfg)
    return {
        "plate": norm_plate(plate),
        "plate_state": state,
        "today": today,
        "eligibility": elig,
        "rows": rows,
        "warnings": warnings,
        "balance": balance,
        "vehicle_tickets": vehicle_tickets,
    }


def eligibility_dict(elig: tl.Eligibility) -> dict:
    return {
        "eligible": elig.eligible,
        "reasons": elig.reasons,
        "conditions": elig.conditions,
        "qualifying_ticket_ids": elig.qualifying_ticket_ids,
        "earliest_date": elig.earliest_date.isoformat() if elig.earliest_date else None,
        "warning_sent_on": elig.warning_sent_on.isoformat() if elig.warning_sent_on else None,
        "should_issue_warning": elig.should_issue_warning,
    }


async def active_deployment(db: AsyncSession, plate: str, plate_state: str | None) -> BarnacleDeployment | None:
    q = select(BarnacleDeployment).where(
        BarnacleDeployment.plate == norm_plate(plate),
        BarnacleDeployment.status.in_(ACTIVE_DEPLOYMENT_STATUSES),
    )
    if plate_state:
        q = q.where(BarnacleDeployment.plate_state == norm_state(plate_state))
    return (await db.execute(q.order_by(BarnacleDeployment.deployed_at.desc()).limit(1))).scalar()


async def checklist(db: AsyncSession, plate: str, plate_state: str | None, cfg: tl.PolicyConfig) -> dict:
    """Everything an officer must see before recording a deployment, computed live."""
    state = norm_state(plate_state)
    if not state:
        raise HTTPException(400, "Issuing state is required")
    v = await vehicle_eligibility(db, plate, state, cfg)
    elig: tl.Eligibility = v["eligibility"]
    p = v["plate"]

    permits = (await db.execute(
        select(Permit).where(Permit.plates.contains([p]), Permit.deleted_at.is_(None))
    )).scalars().all()
    descriptions = sorted({t.vehicle_description for t in v["vehicle_tickets"] if t.vehicle_description})

    citations = []
    for t, cs, start in v["rows"]:
        if not cs.unpaid:
            continue
        citations.append({
            "id": str(t.id),
            "ticket_number": t.ticket_number,
            "issued_at": t.issued_at.isoformat() if t.issued_at else None,
            "plate_state": t.plate_state,
            "fine_amount": str(t.fine_amount),
            "status": t.status,
            "policy_version": t.policy_version,
            "on_timeline": cs.on_timeline,
            "elapsed_days": cs.elapsed,
            "delinquent_days": tl.delinquent_days(cs.elapsed, cfg) if cs.on_timeline else None,
            "paused_reason": cs.paused_reason,
            "appeal_decision": t.appeal_decision,
            "qualifying": cs.ticket_id in elig.qualifying_ticket_ids,
        })

    ticket_ids = [t.id for t in v["vehicle_tickets"]]
    notices = (await db.execute(
        select(CitationNotice).where(CitationNotice.plate == p).order_by(CitationNotice.created_at)
    )).scalars().all()
    plans = []
    if ticket_ids:
        plans = (await db.execute(
            select(PaymentPlan).join(PaymentPlanCitation, PaymentPlanCitation.plan_id == PaymentPlan.id)
            .where(PaymentPlanCitation.ticket_id.in_(ticket_ids)).distinct()
        )).scalars().all()
    deployment = await active_deployment(db, p, state)

    return {
        "plate": p,
        "plate_state": state,
        "vehicle": {
            "descriptions": descriptions,
            "permits": [{"name": pm.name, "permit_type": pm.permit_type, "is_tag_only": pm.is_tag_only,
                         "vehicle": " ".join(x for x in (pm.vehicle_color, pm.vehicle_year, pm.vehicle_make, pm.vehicle_model) if x)}
                        for pm in permits],
        },
        "citations": citations,
        "balance": str(v["balance"]),
        "person_balance": str(await person_balance(db, p)),
        "notices": [{
            "id": str(n.id), "notice_type": n.notice_type, "channel": n.channel, "status": n.status,
            "sent_at": n.sent_at.isoformat() if n.sent_at else None,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "earliest_date": n.earliest_date.isoformat() if n.earliest_date else None,
        } for n in notices],
        "pending_appeals": [c for c in citations if c["appeal_decision"] == "pending"],
        "payment_plans": [{"id": str(pl.id), "status": pl.status, "payer_name": pl.payer_name} for pl in plans],
        "eligibility": eligibility_dict(elig),
        "active_deployment": deployment_dict(deployment) if deployment else None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def deployment_dict(d: BarnacleDeployment) -> dict:
    return {
        "id": str(d.id), "plate": d.plate, "plate_state": d.plate_state, "status": d.status,
        "officer_email": d.officer_email, "officer_name": d.officer_name,
        "deployed_at": d.deployed_at.isoformat() if d.deployed_at else None,
        "location_text": d.location_text, "location_lat": d.location_lat, "location_lng": d.location_lng,
        "vehicle_description": d.vehicle_description,
        "removal_requested_at": d.removal_requested_at.isoformat() if d.removal_requested_at else None,
        "removal_request_contact": d.removal_request_contact,
        "override_by": d.override_by, "override_reason": d.override_reason,
        "override_at": d.override_at.isoformat() if d.override_at else None,
        "removed_at": d.removed_at.isoformat() if d.removed_at else None,
        "removed_by": d.removed_by, "removal_notes": d.removal_notes,
        "fee_id": str(d.fee_id) if d.fee_id else None,
        "ticket_ids": d.ticket_ids or [],
    }


async def record_deployment(
    db: AsyncSession, *, plate: str, plate_state: str, cfg: tl.PolicyConfig, officer_email: str,
    officer_name: str | None, location_text: str, location_lat: float | None, location_lng: float | None,
    vehicle_description: str | None, authorized_property_confirmed: bool,
) -> BarnacleDeployment:
    if not authorized_property_confirmed:
        raise HTTPException(400, "Confirm the vehicle is on property where immobilization is authorized")
    if not (location_text or "").strip():
        raise HTTPException(400, "Location is required")
    snapshot = await checklist(db, plate, plate_state, cfg)
    if snapshot["active_deployment"]:
        raise HTTPException(409, "This vehicle already has an active Barnacle deployment")
    if not snapshot["eligibility"]["eligible"]:
        raise HTTPException(409, {"message": "Vehicle is not eligible right now", "reasons": snapshot["eligibility"]["reasons"]})

    deployment = BarnacleDeployment(
        id=uuid.uuid4(), plate=snapshot["plate"], plate_state=snapshot["plate_state"], status="deployed",
        officer_email=officer_email, officer_name=officer_name, location_text=location_text.strip(),
        location_lat=location_lat, location_lng=location_lng, vehicle_description=vehicle_description,
        authorized_property_confirmed=True, checklist=snapshot,
        ticket_ids=snapshot["eligibility"]["qualifying_ticket_ids"],
    )
    db.add(deployment)
    await db.flush()
    fee = await create_fee(
        db, fee_type=tl.BARNACLE_DEPLOYMENT, amount=cfg.barnacle_fee, plate=deployment.plate,
        plate_state=deployment.plate_state,
        ticket_ids=[uuid.UUID(t) for t in deployment.ticket_ids], actor=officer_email,
        idempotency_key=f"{tl.BARNACLE_DEPLOYMENT}:{deployment.id}", deployment_id=deployment.id,
    )
    deployment.fee_id = fee.id if fee else None
    await record_policy_event(
        db, officer_email, "barnacle_deployment", deployment.id,
        f"Barnacle deployed on {deployment.plate} ({deployment.plate_state}) at {deployment.location_text}",
        {"ticket_ids": deployment.ticket_ids},
    )
    return deployment


async def request_removal(db: AsyncSession, deployment: BarnacleDeployment, contact: str, actor: str) -> dict:
    balance = await person_balance(db, deployment.plate)
    if balance > 0 and not deployment.override_at:
        return {"ok": False, "balance": str(balance)}
    if deployment.status == "deployed":
        deployment.status = "removal_requested"
        deployment.removal_requested_at = datetime.now(timezone.utc)
        deployment.removal_request_contact = (contact or "").strip()[:256] or None
        await record_policy_event(
            db, actor, "barnacle_deployment", deployment.id,
            f"Removal requested for {deployment.plate} ({deployment.plate_state})",
        )
    return {"ok": True, "balance": str(balance)}


async def record_override(db: AsyncSession, deployment: BarnacleDeployment, actor: str, reason: str) -> None:
    if not (reason or "").strip():
        raise HTTPException(400, "A reason is required")
    if deployment.status not in ACTIVE_DEPLOYMENT_STATUSES:
        raise HTTPException(400, "Deployment is not active")
    deployment.override_by = actor
    deployment.override_reason = reason.strip()
    deployment.override_at = datetime.now(timezone.utc)
    if deployment.status == "deployed":
        deployment.status = "removal_requested"
        deployment.removal_requested_at = deployment.override_at
    await record_policy_event(
        db, actor, "barnacle_deployment", deployment.id,
        f"Supervisor release override for {deployment.plate}: {reason.strip()}",
    )


async def record_removal(db: AsyncSession, deployment: BarnacleDeployment, actor: str, notes: str | None) -> None:
    if deployment.status not in ACTIVE_DEPLOYMENT_STATUSES:
        raise HTTPException(400, "Deployment is not active")
    balance = await person_balance(db, deployment.plate)
    allowed, why = tl.removal_allowed(balance, deployment.override_reason)
    if not allowed:
        raise HTTPException(409, why)
    deployment.status = "removed"
    deployment.removed_at = datetime.now(timezone.utc)
    deployment.removed_by = actor
    deployment.removal_notes = (notes or "").strip() or None
    await record_policy_event(
        db, actor, "barnacle_deployment", deployment.id,
        f"Barnacle removed from {deployment.plate} ({why})", {"basis": why},
    )
