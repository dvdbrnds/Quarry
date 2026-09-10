"""Appeals committee management: member CRUD, case escalation, voting, and decision endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..auth.okta import get_current_user, require_admin, OktaUser
from ..database import get_db
from ..models.appeal_committee import AppealCommitteeMember, CommitteeVote
from ..models.ticket import Ticket

router = APIRouter(dependencies=[Depends(get_current_user)])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MemberCreate(BaseModel):
    email: str
    name: str
    is_chair: bool = False


class MemberRead(BaseModel):
    id: uuid.UUID
    email: str
    name: str
    is_chair: bool
    added_by: str
    added_at: datetime

    class Config:
        from_attributes = True


class EscalateRequest(BaseModel):
    notes: str = ""


class VoteRequest(BaseModel):
    vote: str  # "uphold" or "deny"
    comment: str = ""


class CloseRequest(BaseModel):
    decision: str  # "upheld" or "denied"
    reason: str = ""


class VoteRead(BaseModel):
    voter_email: str
    vote: str
    comment: str | None
    voted_at: datetime

    class Config:
        from_attributes = True


class CaseSummary(BaseModel):
    id: uuid.UUID
    ticket_number: str | None
    plate: str
    lot: str
    violation_type: str
    fine_amount: float
    issued_at: datetime
    appeal_note: str | None
    committee_notes: str | None
    committee_status: str | None
    committee_decision: str | None
    committee_decided_at: datetime | None
    escalated_by: str | None
    escalated_at: datetime | None
    owner_name: str | None
    officer_name: str | None
    votes_uphold: int = 0
    votes_deny: int = 0
    total_members: int = 0
    has_voted: bool = False


class CaseDetail(CaseSummary):
    officer_email: str | None
    officer_notes: str | None
    ticket_category: str = "parking"
    status: str = "escalated"
    location_text: str | None = None
    location_lat: float | None = None
    location_lng: float | None = None
    vehicle_description: str | None = None
    driver_name: str | None = None
    driver_license: str | None = None
    dispute_name: str | None = None
    dispute_email: str | None = None
    dispute_phone: str | None = None
    photo_url: str | None = None
    additional_photo_count: int = 0
    additional_violations: list[dict] | None = None
    permit_number: str | None = None
    permit_type_label: str | None = None
    permit_lot_zone: str | None = None
    ocr_original_plate: str | None = None
    appeal_decision: str | None
    appeal_decided_by: str | None
    appeal_decision_reason: str | None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    votes: list[VoteRead] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _require_committee_or_admin(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OktaUser:
    if user.is_admin:
        return user
    member = (await db.execute(
        select(AppealCommitteeMember).where(
            func.lower(AppealCommitteeMember.email) == user.email.lower()
        )
    )).scalar()
    if not member:
        raise HTTPException(403, "Not a committee member")
    return user


async def _require_committee_member(
    user: OktaUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> OktaUser:
    member = (await db.execute(
        select(AppealCommitteeMember).where(
            func.lower(AppealCommitteeMember.email) == user.email.lower()
        )
    )).scalar()
    if not member:
        raise HTTPException(403, "Not a committee member")
    return user


# ---------------------------------------------------------------------------
# Member CRUD (admin-only)
# ---------------------------------------------------------------------------

@router.get("/members", response_model=list[MemberRead])
async def list_members(
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    rows = (await db.execute(
        select(AppealCommitteeMember).order_by(AppealCommitteeMember.added_at)
    )).scalars().all()
    return rows


@router.post("/members", response_model=MemberRead, status_code=201)
async def add_member(
    body: MemberCreate,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    existing = (await db.execute(
        select(AppealCommitteeMember).where(
            func.lower(AppealCommitteeMember.email) == body.email.strip().lower()
        )
    )).scalar()
    if existing:
        raise HTTPException(409, "Member already exists")

    member = AppealCommitteeMember(
        email=body.email.strip().lower(),
        name=body.name.strip(),
        is_chair=body.is_chair,
        added_by=admin.email,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return member


@router.delete("/members/{member_id}", status_code=204)
async def remove_member(
    member_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    member = await db.get(AppealCommitteeMember, member_id)
    if not member:
        raise HTTPException(404, "Member not found")
    await db.delete(member)
    await db.flush()


# ---------------------------------------------------------------------------
# Escalation (admin-only)
# ---------------------------------------------------------------------------

@router.post("/escalate/{ticket_id}")
async def escalate_to_committee(
    ticket_id: uuid.UUID,
    body: EscalateRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.status not in ("appealed",) and ticket.appeal_decision != "pending":
        raise HTTPException(400, "Ticket does not have a pending appeal to escalate")

    ticket.status = "escalated"
    ticket.committee_status = "voting"
    ticket.committee_notes = body.notes.strip() if body.notes else None
    ticket.escalated_by = admin.email
    ticket.escalated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(ticket)
    return {"ok": True, "ticket_id": str(ticket.id), "status": ticket.status}


# ---------------------------------------------------------------------------
# Cases (committee members + admins)
# ---------------------------------------------------------------------------

@router.get("/cases", response_model=list[CaseSummary])
async def list_cases(
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(_require_committee_or_admin),
):
    q = select(Ticket).where(Ticket.committee_status.isnot(None)).options(defer(Ticket.photo_data))

    if status == "voting":
        q = q.where(Ticket.committee_status == "voting")
    elif status == "decided":
        q = q.where(Ticket.committee_status == "decided")

    q = q.order_by(Ticket.escalated_at.desc())
    tickets = (await db.execute(q)).scalars().all()

    total_members = (await db.execute(
        select(func.count()).select_from(AppealCommitteeMember)
    )).scalar() or 0

    result = []
    for t in tickets:
        vote_counts = (await db.execute(
            select(
                func.count().filter(CommitteeVote.vote == "uphold").label("uphold"),
                func.count().filter(CommitteeVote.vote == "deny").label("deny"),
            ).where(CommitteeVote.ticket_id == t.id)
        )).one()

        user_voted = False
        if not user.is_admin or True:
            uv = (await db.execute(
                select(CommitteeVote).where(
                    CommitteeVote.ticket_id == t.id,
                    func.lower(CommitteeVote.voter_email) == user.email.lower(),
                )
            )).scalar()
            user_voted = uv is not None

        result.append(CaseSummary(
            id=t.id,
            ticket_number=t.ticket_number,
            plate=t.plate,
            lot=t.lot,
            violation_type=t.violation_type,
            fine_amount=float(t.fine_amount),
            issued_at=t.issued_at,
            appeal_note=t.appeal_note,
            committee_notes=t.committee_notes,
            committee_status=t.committee_status,
            committee_decision=t.committee_decision,
            committee_decided_at=t.committee_decided_at,
            escalated_by=t.escalated_by,
            escalated_at=t.escalated_at,
            owner_name=t.owner_name,
            officer_name=t.officer_name,
            votes_uphold=vote_counts.uphold,
            votes_deny=vote_counts.deny,
            total_members=total_members,
            has_voted=user_voted,
        ))

    return result


@router.get("/cases/{ticket_id}", response_model=CaseDetail)
async def get_case(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(_require_committee_or_admin),
):
    ticket = (await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.committee_status.isnot(None))
        .options(defer(Ticket.photo_data))
    )).scalar()
    if not ticket:
        raise HTTPException(404, "Case not found")

    total_members = (await db.execute(
        select(func.count()).select_from(AppealCommitteeMember)
    )).scalar() or 0

    vote_rows = (await db.execute(
        select(CommitteeVote).where(CommitteeVote.ticket_id == ticket_id)
        .order_by(CommitteeVote.voted_at)
    )).scalars().all()

    votes_uphold = sum(1 for v in vote_rows if v.vote == "uphold")
    votes_deny = sum(1 for v in vote_rows if v.vote == "deny")
    user_voted = any(v.voter_email.lower() == user.email.lower() for v in vote_rows)

    votes = [VoteRead(
        voter_email=v.voter_email,
        vote=v.vote,
        comment=v.comment,
        voted_at=v.voted_at,
    ) for v in vote_rows]

    return CaseDetail(
        id=ticket.id,
        ticket_number=ticket.ticket_number,
        plate=ticket.plate,
        lot=ticket.lot,
        violation_type=ticket.violation_type,
        fine_amount=float(ticket.fine_amount),
        issued_at=ticket.issued_at,
        appeal_note=ticket.appeal_note,
        committee_notes=ticket.committee_notes,
        committee_status=ticket.committee_status,
        committee_decision=ticket.committee_decision,
        committee_decided_at=ticket.committee_decided_at,
        escalated_by=ticket.escalated_by,
        escalated_at=ticket.escalated_at,
        owner_name=ticket.owner_name,
        officer_name=ticket.officer_name,
        officer_email=ticket.officer_email,
        officer_notes=ticket.officer_notes,
        ticket_category=ticket.ticket_category,
        status=ticket.status,
        location_text=ticket.location_text,
        location_lat=ticket.location_lat,
        location_lng=ticket.location_lng,
        vehicle_description=ticket.vehicle_description,
        driver_name=ticket.driver_name,
        driver_license=ticket.driver_license,
        dispute_name=ticket.dispute_name,
        dispute_email=ticket.dispute_email,
        dispute_phone=ticket.dispute_phone,
        photo_url=ticket.photo_url,
        additional_photo_count=ticket.additional_photo_count,
        additional_violations=ticket.additional_violations,
        permit_number=ticket.permit_number,
        permit_type_label=ticket.permit_type_label,
        permit_lot_zone=ticket.permit_lot_zone,
        ocr_original_plate=ticket.ocr_original_plate,
        appeal_decision=ticket.appeal_decision,
        appeal_decided_by=ticket.appeal_decided_by,
        appeal_decision_reason=ticket.appeal_decision_reason,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        votes_uphold=votes_uphold,
        votes_deny=votes_deny,
        total_members=total_members,
        has_voted=user_voted,
        votes=votes,
    )


# ---------------------------------------------------------------------------
# Voting (committee members only)
# ---------------------------------------------------------------------------

@router.post("/cases/{ticket_id}/vote")
async def cast_vote(
    ticket_id: uuid.UUID,
    body: VoteRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(_require_committee_member),
):
    if body.vote not in ("uphold", "deny"):
        raise HTTPException(400, "Vote must be 'uphold' or 'deny'")

    ticket = await db.get(Ticket, ticket_id)
    if not ticket or ticket.committee_status != "voting":
        raise HTTPException(400, "Case is not open for voting")

    existing = (await db.execute(
        select(CommitteeVote).where(
            CommitteeVote.ticket_id == ticket_id,
            func.lower(CommitteeVote.voter_email) == user.email.lower(),
        )
    )).scalar()
    if existing:
        raise HTTPException(409, "You have already voted on this case")

    vote = CommitteeVote(
        ticket_id=ticket_id,
        voter_email=user.email.lower(),
        vote=body.vote,
        comment=body.comment.strip() if body.comment else None,
    )
    db.add(vote)
    await db.flush()
    return {"ok": True, "vote": body.vote}


# ---------------------------------------------------------------------------
# Close voting (admin-only)
# ---------------------------------------------------------------------------

@router.post("/cases/{ticket_id}/close")
async def close_voting(
    ticket_id: uuid.UUID,
    body: CloseRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    if body.decision not in ("upheld", "denied"):
        raise HTTPException(400, "Decision must be 'upheld' or 'denied'")

    ticket = await db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    if ticket.committee_status != "voting":
        raise HTTPException(400, "Case is not open for voting")

    now = datetime.now(timezone.utc)
    ticket.committee_status = "decided"
    ticket.committee_decision = body.decision
    ticket.committee_decided_at = now
    ticket.appeal_decided_by = f"committee ({admin.email})"

    if body.decision == "upheld":
        ticket.status = "voided"
        ticket.appeal_decision = "approved"
        ticket.appeal_decision_reason = body.reason.strip() if body.reason else "Appeal upheld by committee"
    else:
        ticket.status = "pending_payment"
        ticket.appeal_decision = "denied"
        ticket.appeal_decision_reason = body.reason.strip() if body.reason else "Appeal denied by committee"

    await db.flush()
    await db.refresh(ticket)
    return {"ok": True, "decision": body.decision, "status": ticket.status}


# ---------------------------------------------------------------------------
# Photo proxy (so committee page can display citation photos)
# ---------------------------------------------------------------------------

@router.get("/cases/{ticket_id}/photo")
async def get_case_photo(
    ticket_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(_require_committee_or_admin),
):
    ticket = (await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.committee_status.isnot(None))
    )).scalar()
    if not ticket or not ticket.photo_data:
        raise HTTPException(404, "Photo not found")

    from fastapi.responses import Response
    return Response(
        content=ticket.photo_data,
        media_type=ticket.photo_mime or "image/jpeg",
    )


@router.get("/cases/{ticket_id}/photos/{index}")
async def get_case_additional_photo(
    ticket_id: uuid.UUID,
    index: int,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(_require_committee_or_admin),
):
    ticket = (await db.execute(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.committee_status.isnot(None))
    )).scalar()
    if not ticket or not ticket.additional_photos:
        raise HTTPException(404, "Photo not found")
    if index < 0 or index >= len(ticket.additional_photos):
        raise HTTPException(404, "Photo index out of range")

    import base64
    from fastapi.responses import Response
    entry = ticket.additional_photos[index]
    photo_bytes = base64.b64decode(entry["data"])
    return Response(
        content=photo_bytes,
        media_type=entry.get("mime", "image/jpeg"),
    )
