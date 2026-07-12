import random
import string
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_application import PermitApplication
from ..models.permit_type import PermitType
from ..schemas.permit_application import (
    ActivityEventRead,
    ApplicationAdminRead,
    LotteryResult,
    SimulateRequest,
    SimulatedAppResult,
    SimulationResponse,
)
from ..schemas.permit_type import (
    PermitTypeCreate,
    PermitTypeImportPayload,
    PermitTypeImportResult,
    PermitTypeRead,
    PermitTypeUpdate,
    PermitTypeWithCount,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[PermitTypeWithCount])
async def list_permit_types(
    all: bool = Query(False, description="Include inactive types"),
    db: AsyncSession = Depends(get_db),
):
    query = select(PermitType).order_by(PermitType.sort_order, PermitType.code)
    if not all:
        query = query.where(PermitType.is_active.is_(True))
    types = (await db.execute(query)).scalars().all()

    results = []
    for pt in types:
        count_result = await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )
        active_count = count_result.scalar() or 0
        remaining = max(0, pt.max_capacity - active_count)
        results.append(
            PermitTypeWithCount(
                **{k: v for k, v in pt.__dict__.items() if not k.startswith("_")},
                active_count=active_count,
                remaining=remaining,
            )
        )
    return results


@router.post("", response_model=PermitTypeRead, status_code=201)
async def create_permit_type(
    data: PermitTypeCreate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    existing = await db.execute(
        select(PermitType).where(PermitType.code == data.code)
    )
    if existing.scalar():
        raise HTTPException(409, f"Permit type with code '{data.code}' already exists")

    ptype = PermitType(**data.model_dump())
    db.add(ptype)
    await db.flush()
    await db.refresh(ptype)
    return ptype


@router.put("/{ptype_id}", response_model=PermitTypeRead)
async def update_permit_type(
    ptype_id: uuid.UUID,
    data: PermitTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    ptype = await db.get(PermitType, ptype_id)
    if not ptype:
        raise HTTPException(404, "Permit type not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(ptype, field, value)

    await db.flush()
    await db.refresh(ptype)
    return ptype


@router.delete("/{ptype_id}", status_code=204)
async def deactivate_permit_type(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    ptype = await db.get(PermitType, ptype_id)
    if not ptype:
        raise HTTPException(404, "Permit type not found")
    ptype.is_active = False
    await db.flush()


@router.post("/import", response_model=PermitTypeImportResult)
async def import_permit_types(
    payload: PermitTypeImportPayload,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    created = 0
    updated = 0
    errors: list[str] = []

    for row in payload.permit_types:
        try:
            result = await db.execute(
                select(PermitType).where(PermitType.code == row.code)
            )
            existing = result.scalar()

            if existing:
                existing.label = row.label
                existing.eligible = row.eligible
                existing.price = row.price
                existing.max_capacity = row.max_capacity
                existing.valid_days = row.valid_days
                existing.lot_assignments = row.lot_assignments
                existing.time_restriction = row.time_restriction
                existing.is_purchasable_online = row.is_purchasable_online
                existing.sort_order = row.sort_order
                existing.is_active = True
                updated += 1
            else:
                ptype = PermitType(
                    code=row.code,
                    label=row.label,
                    eligible=row.eligible,
                    price=row.price,
                    max_capacity=row.max_capacity,
                    valid_days=row.valid_days,
                    lot_assignments=row.lot_assignments,
                    time_restriction=row.time_restriction,
                    is_purchasable_online=row.is_purchasable_online,
                    sort_order=row.sort_order,
                )
                db.add(ptype)
                created += 1
        except Exception as e:
            errors.append(f"Error processing '{row.code}': {e}")

    await db.flush()
    return PermitTypeImportResult(created=created, updated=updated, errors=errors)


# ── Lottery management ──


@router.get("/{ptype_id}/applications", response_model=list[ApplicationAdminRead])
async def list_applications(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    result = await db.execute(
        select(PermitApplication)
        .where(PermitApplication.permit_type_id == ptype_id)
        .order_by(PermitApplication.created_at.asc())
    )
    apps = result.scalars().all()
    return [
        ApplicationAdminRead(
            **{k: v for k, v in a.__dict__.items() if not k.startswith("_")},
            permit_type_code=pt.code,
            permit_type_label=pt.label,
        )
        for a in apps
    ]


@router.delete("/{ptype_id}/applications/{app_id}", status_code=204)
async def delete_application(
    ptype_id: uuid.UUID,
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Delete a single lottery application."""
    app = await db.get(PermitApplication, app_id)
    if not app or app.permit_type_id != ptype_id:
        raise HTTPException(404, "Application not found")
    await db.delete(app)
    await db.flush()


@router.post("/{ptype_id}/run-lottery", response_model=LotteryResult)
async def run_lottery(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Execute a configurable lottery for a permit type."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")
    if not pt.requires_lottery:
        raise HTTPException(400, "This permit type does not use a lottery")

    pending = (await db.execute(
        select(PermitApplication)
        .where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status == "pending",
        )
    )).scalars().all()

    if not pending:
        raise HTTPException(400, "No pending applications to draw from")

    active_count = (await db.execute(
        select(func.count()).select_from(Permit).where(
            Permit.permit_type == pt.code,
            Permit.status == "active",
            Permit.deleted_at.is_(None),
        )
    )).scalar() or 0

    already_selected = (await db.execute(
        select(func.count()).select_from(PermitApplication).where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status.in_(["selected", "accepted"]),
        )
    )).scalar() or 0

    spots = max(0, pt.max_capacity - active_count - already_selected)

    from ..services.lottery import get_strategy, assign_lots
    strategy = get_strategy(pt.lottery_strategy or "seniority_weighted")
    selected_apps, remaining = strategy.rank(list(pending), spots)

    if pt.lot_assignments and len(pt.lot_assignments) > 1:
        assign_lots(selected_apps, pt.lot_assignments, pt.max_capacity)

    offer_deadline = datetime.now(timezone.utc) + timedelta(days=pt.offer_window_days)
    for rank, app in enumerate(selected_apps, 1):
        app.status = "selected"
        app.lottery_rank = rank
        app.offer_expires_at = offer_deadline

    for pos, app in enumerate(remaining, 1):
        app.status = "waitlisted"
        app.waitlist_position = pos

    pt.lottery_run_at = datetime.now(timezone.utc)
    await db.flush()

    from ..services.email import send_lottery_selection_email
    for app in selected_apps:
        await send_lottery_selection_email(
            recipient_email=app.student_email,
            student_name=app.student_name,
            permit_type_label=pt.label,
            price=str(pt.price),
            deadline=offer_deadline.strftime("%B %d, %Y"),
            portal_url=f"{settings.public_url.rstrip('/')}/parking",
            assigned_lot=app.assigned_lot,
        )

    return LotteryResult(
        selected=len(selected_apps),
        waitlisted=len(remaining),
        total_applicants=len(pending),
    )


@router.post("/{ptype_id}/advance-waitlist")
async def advance_waitlist(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Expire overdue offers and advance the next waitlisted applicant."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    now = datetime.now(timezone.utc)
    expired_result = await db.execute(
        select(PermitApplication).where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status == "selected",
            PermitApplication.offer_expires_at.isnot(None),
            PermitApplication.offer_expires_at < now,
        )
    )
    expired = expired_result.scalars().all()
    for app in expired:
        app.status = "expired"

    advanced = 0
    for _ in expired:
        next_app = (await db.execute(
            select(PermitApplication)
            .where(
                PermitApplication.permit_type_id == ptype_id,
                PermitApplication.status == "waitlisted",
            )
            .order_by(PermitApplication.waitlist_position.asc())
            .limit(1)
        )).scalar()

        if not next_app:
            break

        next_app.status = "selected"
        next_app.offer_expires_at = now + timedelta(days=pt.offer_window_days)
        advanced += 1

        from ..services.email import send_lottery_selection_email
        await send_lottery_selection_email(
            recipient_email=next_app.student_email,
            student_name=next_app.student_name,
            permit_type_label=pt.label,
            price=str(pt.price),
            deadline=next_app.offer_expires_at.strftime("%B %d, %Y"),
            portal_url=f"{settings.public_url.rstrip('/')}/parking",
            assigned_lot=next_app.assigned_lot,
        )

    await db.flush()
    return {"expired": len(expired), "advanced": advanced}


@router.post("/{ptype_id}/reset-lottery")
async def reset_lottery(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Reset all lottery results, returning every application to pending status.

    Clears lottery_run_at on the permit type and resets rank, waitlist
    position, assigned lot, and offer expiry on each application.  Does NOT
    delete applications — they stay in the pool so the lottery can be re-run.
    """
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")
    if not pt.requires_lottery:
        raise HTTPException(400, "This permit type does not use a lottery")

    all_apps = (await db.execute(
        select(PermitApplication).where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status.notin_(["declined"]),
        )
    )).scalars().all()

    reset_count = 0
    for app in all_apps:
        if app.status != "pending":
            reset_count += 1
        app.status = "pending"
        app.lottery_rank = None
        app.waitlist_position = None
        app.assigned_lot = None
        app.offer_expires_at = None

    pt.lottery_run_at = None
    await db.flush()

    return {"reset": reset_count, "total_applications": len(all_apps)}


@router.post("/{ptype_id}/open-lottery")
async def open_lottery(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """One-click: enable lottery and open the application window immediately."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    pt.requires_lottery = True
    pt.application_opens_at = datetime.now(timezone.utc)
    if not pt.lottery_strategy:
        pt.lottery_strategy = "seniority_timestamp"
    await db.flush()
    await db.refresh(pt)
    return {"status": "open", "opens_at": pt.application_opens_at.isoformat()}


@router.post("/{ptype_id}/close-applications")
async def close_applications(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Immediately close the application window by setting closes_at to now."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    pt.application_closes_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "closed", "closed_at": pt.application_closes_at.isoformat()}


@router.post("/{ptype_id}/applications/{app_id}/select")
async def manually_select_application(
    ptype_id: uuid.UUID,
    app_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Manually select an applicant, bypassing the lottery draw."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    app = await db.get(PermitApplication, app_id)
    if not app or app.permit_type_id != ptype_id:
        raise HTTPException(404, "Application not found")

    if app.status not in ("pending", "waitlisted"):
        raise HTTPException(400, f"Cannot select an application with status '{app.status}'")

    app.status = "selected"
    app.offer_expires_at = datetime.now(timezone.utc) + timedelta(days=pt.offer_window_days)

    if pt.lot_assignments and len(pt.lot_assignments) == 1:
        app.assigned_lot = pt.lot_assignments[0]

    await db.flush()

    from ..services.email import send_lottery_selection_email
    await send_lottery_selection_email(
        recipient_email=app.student_email,
        student_name=app.student_name,
        permit_type_label=pt.label,
        price=str(pt.price),
        deadline=app.offer_expires_at.strftime("%B %d, %Y"),
        portal_url=f"{settings.public_url.rstrip('/')}/parking",
        assigned_lot=app.assigned_lot,
    )

    return {
        "status": "selected",
        "student_name": app.student_name,
        "offer_expires_at": app.offer_expires_at.isoformat(),
    }


@router.post("/{ptype_id}/simulate-lottery", response_model=SimulationResponse)
async def simulate_lottery(
    ptype_id: uuid.UUID,
    data: SimulateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Dry-run the lottery without persisting any changes."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")
    if not pt.requires_lottery:
        raise HTTPException(400, "This permit type does not use a lottery")

    # Include all non-withdrawn applications so simulation works both before
    # and after the lottery has been run (dry-run treats everyone as a candidate).
    candidates = (await db.execute(
        select(PermitApplication)
        .where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status.notin_(["declined"]),
        )
    )).scalars().all()

    if not candidates:
        raise HTTPException(400, "No applications to simulate with")

    capacity = data.capacity_override if data.capacity_override else pt.max_capacity
    spots = max(0, capacity)

    from ..services.lottery import get_strategy, assign_lots
    strategy_name = data.strategy or pt.lottery_strategy or "seniority_timestamp"
    strategy = get_strategy(strategy_name)

    # Work on copies to avoid mutating DB objects
    import copy
    apps_copy = [copy.copy(a) for a in candidates]
    selected_apps, remaining = strategy.rank(apps_copy, spots)

    if pt.lot_assignments and len(pt.lot_assignments) > 1:
        assign_lots(selected_apps, pt.lot_assignments, capacity)

    selected_results = [
        SimulatedAppResult(
            id=app.id,
            student_name=app.student_name,
            student_email=app.student_email,
            class_year=app.class_year,
            plate=app.plate,
            lot_preferences=app.lot_preferences or [],
            assigned_lot=app.assigned_lot,
            rank=i + 1,
        )
        for i, app in enumerate(selected_apps)
    ]

    waitlisted_results = [
        SimulatedAppResult(
            id=app.id,
            student_name=app.student_name,
            student_email=app.student_email,
            class_year=app.class_year,
            plate=app.plate,
            lot_preferences=app.lot_preferences or [],
            assigned_lot=None,
            rank=i + 1,
        )
        for i, app in enumerate(remaining)
    ]

    return SimulationResponse(
        selected=selected_results,
        waitlisted=waitlisted_results,
        total_applicants=len(candidates),
        spots_available=spots,
        strategy_used=strategy_name,
    )


@router.get("/{ptype_id}/lottery-activity", response_model=list[ActivityEventRead])
async def lottery_activity(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Return recent application status changes for the live dashboard."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    result = await db.execute(
        select(PermitApplication)
        .where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.status != "pending",
            PermitApplication.updated_at > cutoff,
        )
        .order_by(PermitApplication.updated_at.desc())
        .limit(50)
    )
    apps = result.scalars().all()

    events = []
    for app in apps:
        old_status = "pending"
        if app.status == "accepted":
            old_status = "selected"
        elif app.status == "expired":
            old_status = "selected"
        elif app.status in ("selected", "waitlisted"):
            old_status = "pending"

        events.append(ActivityEventRead(
            id=app.id,
            student_name=app.student_name,
            old_status=old_status,
            new_status=app.status,
            timestamp=app.updated_at,
        ))

    return events


@router.delete("/{ptype_id}/test-applications")
async def purge_test_applications(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Delete all test entries for a permit type (staff tests + synthetic data)."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")

    test_apps = (await db.execute(
        select(PermitApplication).where(
            PermitApplication.permit_type_id == ptype_id,
            PermitApplication.is_test_entry.is_(True),
        )
    )).scalars().all()

    count = len(test_apps)
    for app in test_apps:
        await db.delete(app)

    await db.flush()
    return {"deleted": count}


class GenerateTestRequest(BaseModel):
    count: int = 50
    min_class_year: int = 2025
    max_class_year: int = 2028


_FIRST_NAMES = [
    "Emma", "Liam", "Olivia", "Noah", "Ava", "Ethan", "Sophia", "Mason",
    "Isabella", "James", "Mia", "Lucas", "Charlotte", "Logan", "Amelia",
    "Alexander", "Harper", "Jack", "Ella", "William", "Abigail", "Owen",
    "Emily", "Daniel", "Madison", "Henry", "Grace", "Sebastian", "Chloe",
    "Michael", "Victoria", "Benjamin", "Riley", "Aiden", "Aria", "Samuel",
    "Zoey", "Carter", "Lily", "Jayden", "Hannah", "Caleb", "Natalie",
    "Ryan", "Luna", "Nathan", "Stella", "Dylan", "Savannah", "Andrew",
]

_LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
    "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
    "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark",
    "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King",
    "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green",
    "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell",
]


def _random_plate() -> str:
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    digits = "".join(random.choices(string.digits, k=4))
    return f"{letters}{digits}"


@router.post("/{ptype_id}/generate-test-applications")
async def generate_test_applications(
    ptype_id: uuid.UUID,
    data: GenerateTestRequest,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Generate synthetic test applications for a permit type."""
    pt = await db.get(PermitType, ptype_id)
    if not pt:
        raise HTTPException(404, "Permit type not found")
    if not pt.requires_lottery:
        raise HTTPException(400, "This permit type does not use a lottery")

    count = min(max(1, data.count), 500)
    created = 0

    for i in range(count):
        first = random.choice(_FIRST_NAMES)
        last = random.choice(_LAST_NAMES)
        class_year = random.randint(data.min_class_year, data.max_class_year)
        email = f"{first.lower()}.{last.lower()}{random.randint(1, 99)}@test.moravian.edu"

        lot_prefs = list(pt.lot_assignments) if pt.lot_assignments else []
        random.shuffle(lot_prefs)

        app = PermitApplication(
            student_sub=f"test-{uuid.uuid4().hex[:12]}",
            student_email=email,
            student_name=f"{first} {last}",
            class_year=class_year,
            permit_type_id=pt.id,
            plate=_random_plate(),
            plate_state=random.choice(["PA", "NJ", "NY", "CT", "MD", "DE", "VA"]),
            phone=None,
            lot_preferences=lot_prefs,
            is_test_entry=True,
            okta_metadata={"synthetic": True, "generator": "quarry-test"},
        )
        db.add(app)
        created += 1

    await db.flush()
    return {"created": created}
