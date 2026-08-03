import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user_or_impersonated, require_admin
from ..database import get_db
from ..models.coupon import Coupon
from ..models.coupon_usage import CouponUsage

router = APIRouter()

admin_router = APIRouter(dependencies=[Depends(require_admin())])


# ── Schemas ──────────────────────────────────────────────────────────────────

class CouponCreate(BaseModel):
    code: str
    program_name: str = ""
    discount_type: str  # "percent", "flat", "full"
    discount_value: Decimal = Decimal("0.00")
    applicable_permit_codes: list[str] = []
    max_uses: int | None = None
    is_active: bool = True
    expires_at: datetime | None = None


class CouponUpdate(BaseModel):
    code: str | None = None
    program_name: str | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = None
    applicable_permit_codes: list[str] | None = None
    max_uses: int | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None


class CouponRead(BaseModel):
    id: str
    code: str
    program_name: str
    discount_type: str
    discount_value: Decimal
    applicable_permit_codes: list[str]
    max_uses: int | None
    current_uses: int
    is_active: bool
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class CouponValidateRequest(BaseModel):
    code: str
    permit_type_code: str


class CouponValidateResponse(BaseModel):
    valid: bool
    discount_type: str | None = None
    discount_value: Decimal | None = None
    program_name: str | None = None
    message: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

def _to_read(c: Coupon) -> CouponRead:
    return CouponRead(
        id=str(c.id),
        code=c.code,
        program_name=c.program_name,
        discount_type=c.discount_type,
        discount_value=c.discount_value,
        applicable_permit_codes=list(c.applicable_permit_codes or []),
        max_uses=c.max_uses,
        current_uses=c.current_uses,
        is_active=c.is_active,
        expires_at=c.expires_at,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _validate_coupon(coupon: Coupon, permit_type_code: str) -> str | None:
    """Return an error message if the coupon is invalid for the given permit type, else None."""
    if not coupon.is_active:
        return "This coupon is no longer active."
    if coupon.expires_at and datetime.now(timezone.utc) > coupon.expires_at:
        return "This coupon has expired."
    if coupon.max_uses is not None and coupon.current_uses >= coupon.max_uses:
        return "This coupon has reached its usage limit."
    if coupon.applicable_permit_codes and permit_type_code not in coupon.applicable_permit_codes:
        return "This coupon does not apply to the selected permit type."
    return None


# ── Admin endpoints ──────────────────────────────────────────────────────────

@admin_router.get("", response_model=list[CouponRead])
async def list_coupons(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Coupon).order_by(Coupon.created_at.desc()))
    return [_to_read(c) for c in result.scalars().all()]


@admin_router.post("", response_model=CouponRead, status_code=201)
async def create_coupon(data: CouponCreate, db: AsyncSession = Depends(get_db)):
    if data.discount_type not in ("percent", "flat", "full"):
        raise HTTPException(400, "discount_type must be 'percent', 'flat', or 'full'")
    if data.discount_type == "percent" and (data.discount_value < 0 or data.discount_value > 100):
        raise HTTPException(400, "Percent discount must be between 0 and 100")

    existing = await db.execute(
        select(Coupon).where(func.upper(Coupon.code) == data.code.upper().strip())
    )
    if existing.scalar():
        raise HTTPException(409, "A coupon with this code already exists")

    coupon = Coupon(
        code=data.code.upper().strip(),
        program_name=data.program_name.strip(),
        discount_type=data.discount_type,
        discount_value=data.discount_value if data.discount_type != "full" else Decimal("0.00"),
        applicable_permit_codes=data.applicable_permit_codes,
        max_uses=data.max_uses,
        is_active=data.is_active,
        expires_at=data.expires_at,
    )
    db.add(coupon)
    await db.flush()
    await db.refresh(coupon)
    return _to_read(coupon)


@admin_router.put("/{coupon_id}", response_model=CouponRead)
async def update_coupon(
    coupon_id: uuid.UUID,
    data: CouponUpdate,
    db: AsyncSession = Depends(get_db),
):
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise HTTPException(404, "Coupon not found")

    if data.code is not None:
        new_code = data.code.upper().strip()
        if new_code != coupon.code:
            existing = await db.execute(
                select(Coupon).where(func.upper(Coupon.code) == new_code, Coupon.id != coupon_id)
            )
            if existing.scalar():
                raise HTTPException(409, "A coupon with this code already exists")
            coupon.code = new_code
    if data.program_name is not None:
        coupon.program_name = data.program_name.strip()
    if data.discount_type is not None:
        if data.discount_type not in ("percent", "flat", "full"):
            raise HTTPException(400, "discount_type must be 'percent', 'flat', or 'full'")
        coupon.discount_type = data.discount_type
    if data.discount_value is not None:
        coupon.discount_value = data.discount_value
    if data.applicable_permit_codes is not None:
        coupon.applicable_permit_codes = data.applicable_permit_codes
    if data.max_uses is not None:
        coupon.max_uses = data.max_uses
    if data.is_active is not None:
        coupon.is_active = data.is_active
    if data.expires_at is not None:
        coupon.expires_at = data.expires_at

    await db.flush()
    await db.refresh(coupon)
    return _to_read(coupon)


@admin_router.post("/{coupon_id}/delete", status_code=204)
async def delete_coupon(coupon_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    coupon = await db.get(Coupon, coupon_id)
    if not coupon:
        raise HTTPException(404, "Coupon not found")
    await db.delete(coupon)
    await db.flush()


# ── Student endpoint ─────────────────────────────────────────────────────────

@router.post("/validate", response_model=CouponValidateResponse)
async def validate_coupon(
    data: CouponValidateRequest,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Validate a coupon code for a specific permit type. Returns discount info or error."""
    result = await db.execute(
        select(Coupon).where(func.upper(Coupon.code) == data.code.upper().strip())
    )
    coupon = result.scalar()
    if not coupon:
        return CouponValidateResponse(valid=False, message="Invalid coupon code.")

    error = _validate_coupon(coupon, data.permit_type_code)
    if error:
        return CouponValidateResponse(valid=False, message=error)

    return CouponValidateResponse(
        valid=True,
        discount_type=coupon.discount_type,
        discount_value=coupon.discount_value,
        program_name=coupon.program_name,
        message=_discount_description(coupon),
    )


def _discount_description(coupon: Coupon) -> str:
    if coupon.discount_type == "full":
        return f"{coupon.code}: 100% off ({coupon.program_name})"
    elif coupon.discount_type == "percent":
        return f"{coupon.code}: {coupon.discount_value}% off ({coupon.program_name})"
    else:
        return f"{coupon.code}: ${coupon.discount_value} off ({coupon.program_name})"


async def record_coupon_usage(
    db: AsyncSession,
    coupon: Coupon,
    student_name: str,
    student_email: str,
    student_id: str,
    permit_type_code: str,
    original_price: Decimal,
    final_price: Decimal,
) -> None:
    """Record a coupon usage for chargeback reporting."""
    usage = CouponUsage(
        coupon_id=coupon.id,
        coupon_code=coupon.code,
        program_name=coupon.program_name,
        student_name=student_name,
        student_email=student_email,
        student_id=student_id,
        permit_type_code=permit_type_code,
        original_price=original_price,
        discount_amount=original_price - final_price,
        final_price=final_price,
    )
    db.add(usage)


# ── Usage report endpoints ───────────────────────────────────────────────────

class CouponUsageRead(BaseModel):
    id: str
    coupon_code: str
    program_name: str
    student_name: str
    student_email: str
    student_id: str
    permit_type_code: str
    original_price: Decimal
    discount_amount: Decimal
    final_price: Decimal
    used_at: datetime


@admin_router.get("/usages", response_model=list[CouponUsageRead])
async def list_coupon_usages(db: AsyncSession = Depends(get_db)):
    """List all coupon usages for chargeback reporting."""
    result = await db.execute(select(CouponUsage).order_by(CouponUsage.used_at.desc()))
    return [
        CouponUsageRead(
            id=str(u.id),
            coupon_code=u.coupon_code,
            program_name=u.program_name,
            student_name=u.student_name,
            student_email=u.student_email,
            student_id=u.student_id,
            permit_type_code=u.permit_type_code,
            original_price=u.original_price,
            discount_amount=u.discount_amount,
            final_price=u.final_price,
            used_at=u.used_at,
        )
        for u in result.scalars().all()
    ]


@admin_router.get("/usages/export")
async def export_coupon_usages(db: AsyncSession = Depends(get_db)):
    """Export coupon usages as CSV for department chargeback."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    result = await db.execute(select(CouponUsage).order_by(CouponUsage.used_at.desc()))
    usages = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Coupon Code", "Program/Department", "Student Name",
        "Student Email", "Student ID", "Permit Type", "Original Price",
        "Discount Amount", "Amount Charged",
    ])
    for u in usages:
        writer.writerow([
            u.used_at.strftime("%Y-%m-%d %H:%M") if u.used_at else "",
            u.coupon_code,
            u.program_name,
            u.student_name,
            u.student_email,
            u.student_id,
            u.permit_type_code,
            f"{u.original_price:.2f}",
            f"{u.discount_amount:.2f}",
            f"{u.final_price:.2f}",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=coupon_chargebacks.csv"},
    )
