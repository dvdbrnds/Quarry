import random
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_application import PermitApplication
from ..models.permit_type import PermitType
from ..schemas.permit_application import ApplicationAdminRead, LotteryResult
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


@router.post("/{ptype_id}/run-lottery", response_model=LotteryResult)
async def run_lottery(
    ptype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Execute a seniority-weighted lottery for a permit type."""
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

    # Seniority weight: lower class_year = more senior = higher weight
    max_year = max(a.class_year for a in pending)
    weights = [max_year - a.class_year + 1 for a in pending]

    selected_apps: list[PermitApplication] = []
    pool = list(zip(pending, weights))

    pick_count = min(spots, len(pool))
    for _ in range(pick_count):
        if not pool:
            break
        apps_list, w_list = zip(*pool)
        chosen = random.choices(list(apps_list), weights=list(w_list), k=1)[0]
        selected_apps.append(chosen)
        pool = [(a, w) for a, w in pool if a.id != chosen.id]

    offer_deadline = datetime.now(timezone.utc) + timedelta(days=pt.offer_window_days)
    for rank, app in enumerate(selected_apps, 1):
        app.status = "selected"
        app.lottery_rank = rank
        app.offer_expires_at = offer_deadline

    # Waitlist the rest, ordered by seniority then random
    remaining = [a for a, _ in pool]
    remaining.sort(key=lambda a: a.class_year)
    for pos, app in enumerate(remaining, 1):
        app.status = "waitlisted"
        app.waitlist_position = pos

    pt.lottery_run_at = datetime.now(timezone.utc)
    await db.flush()

    # Send notification emails to selected applicants
    from ..services.email import send_email
    for app in selected_apps:
        await send_email(
            to=[app.student_email],
            subject=f"You've been selected — {pt.label}",
            body_html=(
                f"<p>Congratulations! You've been selected in the lottery for "
                f"<strong>{pt.label}</strong>.</p>"
                f"<p>Log in to the student portal to accept and pay by "
                f"<strong>{offer_deadline.strftime('%b %d, %Y')}</strong>.</p>"
            ),
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

        from ..services.email import send_email
        await send_email(
            to=[next_app.student_email],
            subject=f"Parking Permit Offer — {pt.label}",
            body_html=(
                f"<p>A spot has opened up for <strong>{pt.label}</strong>.</p>"
                f"<p>Log in to the student portal to accept your offer before "
                f"<strong>{next_app.offer_expires_at.strftime('%b %d, %Y')}</strong>.</p>"
            ),
        )

    await db.flush()
    return {"expired": len(expired), "advanced": advanced}
