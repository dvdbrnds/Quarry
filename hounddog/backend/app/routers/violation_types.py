import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..database import get_db
from ..models.violation_type import ViolationType
from ..schemas.violation_type import (
    ViolationTypeCreate,
    ViolationTypeImportPayload,
    ViolationTypeImportResult,
    ViolationTypeRead,
    ViolationTypeUpdate,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


@router.get("", response_model=list[ViolationTypeRead])
async def list_violation_types(
    all: bool = Query(False, description="Include inactive types"),
    db: AsyncSession = Depends(get_db),
):
    query = select(ViolationType).order_by(ViolationType.sort_order, ViolationType.code)
    if not all:
        query = query.where(ViolationType.is_active.is_(True))
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=ViolationTypeRead, status_code=201)
async def create_violation_type(
    data: ViolationTypeCreate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    existing = await db.execute(
        select(ViolationType).where(ViolationType.code == data.code)
    )
    if existing.scalar():
        raise HTTPException(409, f"Violation type with code '{data.code}' already exists")

    vtype = ViolationType(**data.model_dump())
    db.add(vtype)
    await db.flush()
    await db.refresh(vtype)
    return vtype


@router.put("/{vtype_id}", response_model=ViolationTypeRead)
async def update_violation_type(
    vtype_id: uuid.UUID,
    data: ViolationTypeUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    vtype = await db.get(ViolationType, vtype_id)
    if not vtype:
        raise HTTPException(404, "Violation type not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(vtype, field, value)

    await db.flush()
    await db.refresh(vtype)
    return vtype


@router.delete("/{vtype_id}", status_code=204)
async def deactivate_violation_type(
    vtype_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    vtype = await db.get(ViolationType, vtype_id)
    if not vtype:
        raise HTTPException(404, "Violation type not found")
    vtype.is_active = False
    await db.flush()


@router.post("/import", response_model=ViolationTypeImportResult)
async def import_violation_types(
    payload: ViolationTypeImportPayload,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    created = 0
    updated = 0
    errors: list[str] = []

    for row in payload.violation_types:
        try:
            result = await db.execute(
                select(ViolationType).where(ViolationType.code == row.code)
            )
            existing = result.scalar()

            if existing:
                existing.label = row.label
                existing.category = row.category
                existing.fine_first = row.fine_first
                existing.fine_second = row.fine_second
                existing.fine_third_plus = row.fine_third_plus
                existing.sort_order = row.sort_order
                existing.is_active = True
                updated += 1
            else:
                vtype = ViolationType(
                    code=row.code,
                    label=row.label,
                    category=row.category,
                    fine_first=row.fine_first,
                    fine_second=row.fine_second,
                    fine_third_plus=row.fine_third_plus,
                    sort_order=row.sort_order,
                )
                db.add(vtype)
                created += 1
        except Exception as e:
            errors.append(f"Error processing '{row.code}': {e}")

    await db.flush()
    return ViolationTypeImportResult(created=created, updated=updated, errors=errors)
