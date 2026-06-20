import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_type import PermitType
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
