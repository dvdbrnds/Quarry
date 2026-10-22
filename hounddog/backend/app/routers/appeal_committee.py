"""Appeals committee management: member CRUD, case escalation, voting, and decision endpoints."""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from ..utils.safe_router import SafeRouter
from pydantic import BaseModel
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ..auth.okta import get_current_user, require_admin, require_role, OktaUser
from ..database import get_db
from ..models.appeal_committee import AppealCommitteeMember, CommitteeComment, CommitteeVote
from ..models.ticket import Ticket

router = SafeRouter(dependencies=[Depends(get_current_user)])


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
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class CommentRequest(BaseModel):
    body: str


class CommentRead(BaseModel):
    id: uuid.UUID
    author_email: str
    body: str
    created_at: datetime

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
    comment_count: int = 0


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
    comments: list[CommentRead] = []
    my_vote: str | None = None  # current user's vote ("uphold"/"deny") or None


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
    await db.commit()


# ---------------------------------------------------------------------------
# Escalation (admin-only)
# ---------------------------------------------------------------------------

@router.post("/escalate/{ticket_id}")
async def escalate_to_committee(
    ticket_id: uuid.UUID,
    body: EscalateRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_role("admin", "operator")),
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

        comment_count = (await db.execute(
            select(func.count()).select_from(CommitteeComment).where(CommitteeComment.ticket_id == t.id)
        )).scalar() or 0

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
            comment_count=comment_count,
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
    my_vote_val = next((v.vote for v in vote_rows if v.voter_email.lower() == user.email.lower()), None)

    votes = [VoteRead(
        voter_email=v.voter_email,
        vote=v.vote,
        comment=v.comment,
        voted_at=v.voted_at,
        updated_at=v.updated_at,
    ) for v in vote_rows]

    comments = (await db.execute(
        select(CommitteeComment).where(CommitteeComment.ticket_id == ticket_id)
        .order_by(CommitteeComment.created_at)
    )).scalars().all()

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
        comments=[CommentRead.model_validate(c) for c in comments],
        comment_count=len(comments),
        my_vote=my_vote_val,
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
        old_vote = existing.vote
        existing.vote = body.vote
        existing.comment = body.comment.strip() if body.comment else None
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()
        return {"ok": True, "vote": body.vote, "changed_from": old_vote}

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
# Discussion (committee members + admins; never shown to students)
# ---------------------------------------------------------------------------

@router.post("/cases/{ticket_id}/comments", response_model=CommentRead, status_code=201)
async def add_comment(
    ticket_id: uuid.UUID,
    body: CommentRequest,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(_require_committee_or_admin),
):
    text_ = body.body.strip()
    if not text_:
        raise HTTPException(400, "Comment is empty")
    if len(text_) > 4000:
        raise HTTPException(400, "Comment is too long (4000 characters max)")
    ticket = await db.get(Ticket, ticket_id, options=[defer(Ticket.photo_data)])
    if not ticket or ticket.committee_status is None:
        raise HTTPException(404, "Case not found")

    comment = CommitteeComment(ticket_id=ticket_id, author_email=user.email.lower(), body=text_)
    db.add(comment)
    await db.flush()
    await db.refresh(comment)
    return comment


@router.delete("/cases/{ticket_id}/comments/{comment_id}", status_code=204)
async def delete_comment(
    ticket_id: uuid.UUID,
    comment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: OktaUser = Depends(_require_committee_or_admin),
):
    comment = await db.get(CommitteeComment, comment_id)
    if not comment or comment.ticket_id != ticket_id:
        raise HTTPException(404, "Comment not found")
    if comment.author_email.lower() != user.email.lower():
        raise HTTPException(403, "You can only delete your own comments")
    await db.delete(comment)
    await db.flush()


# ---------------------------------------------------------------------------
# Sample decision email (admin-only, always to the signed-in admin)
# ---------------------------------------------------------------------------

class SampleEmailRequest(BaseModel):
    decision: str = "denied"  # "denied" or "approved"
    committee: bool = True


@router.post("/sample-decision-email")
async def send_sample_decision_email(
    body: SampleEmailRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    from datetime import timedelta
    from ..config import settings
    from ..services.citation_policy.service import load_config
    from ..services.email import _load_branding, send_email
    from ..services.email_templates import render_appeal_decision_email
    from ..services.timeutils import today_local

    if body.decision not in ("denied", "approved"):
        raise HTTPException(400, "decision must be 'denied' or 'approved'")
    cfg = await load_config(db)
    due = today_local() + timedelta(days=cfg.denied_grace_days)
    b = await _load_branding()
    html_body, text_body = render_appeal_decision_email(
        name="Sample Student", citation="SAMPLE-0001", plate="ABC1234", violation="No Permit",
        approved=body.decision == "approved",
        reason="Sample reason: signage at the lot entrance was posted and visible.",
        by_committee=body.committee, amount_due="$35.00",
        due_date=f"{due:%A, %B} {due.day}, {due.year}",
        pay_url=f"{settings.student_facing_url}/pay",
        school_name=settings.school_name or "Campus",
        primary=b["primary_color"], accent=b["accent_color"], brand_name=b["brand_name"],
        has_logo=b["has_logo"], department_name=b.get("department_name", "Parking Authority"),
    )
    label = "Approved" if body.decision == "approved" else "Denied"
    ok = await send_email(
        [admin.email], f"[SAMPLE] Parking Appeal {label} \u2014 Citation SAMPLE-0001",
        html_body, text_body, from_override=settings.citation_from_address or None,
    )
    if not ok:
        raise HTTPException(502, "Email could not be sent (check SMTP settings and logs)")
    return {"ok": True, "sent_to": admin.email}


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
    from ..services.citation_policy.service import record_appeal_decision
    if body.decision == "upheld":
        await record_appeal_decision(
            db, ticket, "approved", f"committee ({admin.email})",
            body.reason.strip() if body.reason else "Appeal upheld by committee",
        )
    else:
        await record_appeal_decision(
            db, ticket, "denied", f"committee ({admin.email})",
            body.reason.strip() if body.reason else "Appeal denied by committee",
        )

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
