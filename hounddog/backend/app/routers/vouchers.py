import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user_or_impersonated, require_admin
from ..database import get_db
from ..models.branding_settings import BrandingSettings
from ..models.voucher import Voucher
from ..models.voucher_usage import VoucherUsage

router = APIRouter()

admin_router = APIRouter(dependencies=[Depends(require_admin())])


# ── Schemas ──────────────────────────────────────────────────────────────────

class VoucherCreate(BaseModel):
    code: str
    program_name: str = ""
    discount_type: str  # "percent", "flat", "full"
    discount_value: Decimal = Decimal("0.00")
    applicable_permit_codes: list[str] = []
    max_uses: int | None = None
    is_active: bool = True
    expires_at: datetime | None = None


class VoucherUpdate(BaseModel):
    code: str | None = None
    program_name: str | None = None
    discount_type: str | None = None
    discount_value: Decimal | None = None
    applicable_permit_codes: list[str] | None = None
    max_uses: int | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None


class VoucherRead(BaseModel):
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


class VoucherValidateRequest(BaseModel):
    code: str
    permit_type_code: str


class VoucherValidateResponse(BaseModel):
    valid: bool
    discount_type: str | None = None
    discount_value: Decimal | None = None
    program_name: str | None = None
    message: str = ""


# ── Helpers ──────────────────────────────────────────────────────────────────

async def vouchers_are_enabled(db: AsyncSession) -> bool:
    result = await db.execute(select(BrandingSettings).where(BrandingSettings.id == 1))
    row = result.scalar()
    if not row or row.vouchers_enabled is None:
        return True
    return bool(row.vouchers_enabled)


def _to_read(c: Voucher) -> VoucherRead:
    return VoucherRead(
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


def _validate_voucher(voucher: Voucher, permit_type_code: str) -> str | None:
    """Return an error message if the voucher is invalid for the given permit type, else None."""
    if not voucher.is_active:
        return "This voucher is no longer active."
    if voucher.expires_at and datetime.now(timezone.utc) > voucher.expires_at:
        return "This voucher has expired."
    if voucher.max_uses is not None and voucher.current_uses >= voucher.max_uses:
        return "This voucher has reached its usage limit."
    if voucher.applicable_permit_codes and permit_type_code not in voucher.applicable_permit_codes:
        return "This voucher does not apply to the selected permit type."
    return None


# ── Admin endpoints ──────────────────────────────────────────────────────────

@admin_router.get("", response_model=list[VoucherRead])
async def list_vouchers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Voucher).order_by(Voucher.created_at.desc()))
    return [_to_read(c) for c in result.scalars().all()]


@admin_router.post("", response_model=VoucherRead, status_code=201)
async def create_voucher(data: VoucherCreate, db: AsyncSession = Depends(get_db)):
    if not await vouchers_are_enabled(db):
        raise HTTPException(403, "Vouchers are not enabled for this school.")
    if data.discount_type not in ("percent", "flat", "full"):
        raise HTTPException(400, "discount_type must be 'percent', 'flat', or 'full'")
    if data.discount_type == "percent" and (data.discount_value < 0 or data.discount_value > 100):
        raise HTTPException(400, "Percent discount must be between 0 and 100")

    existing = await db.execute(
        select(Voucher).where(func.upper(Voucher.code) == data.code.upper().strip())
    )
    if existing.scalar():
        raise HTTPException(409, "A voucher with this code already exists")

    voucher = Voucher(
        code=data.code.upper().strip(),
        program_name=data.program_name.strip(),
        discount_type=data.discount_type,
        discount_value=data.discount_value if data.discount_type != "full" else Decimal("0.00"),
        applicable_permit_codes=data.applicable_permit_codes,
        max_uses=data.max_uses,
        is_active=data.is_active,
        expires_at=data.expires_at,
    )
    db.add(voucher)
    await db.flush()
    await db.refresh(voucher)
    return _to_read(voucher)


@admin_router.put("/{voucher_id}", response_model=VoucherRead)
async def update_voucher(
    voucher_id: uuid.UUID,
    data: VoucherUpdate,
    db: AsyncSession = Depends(get_db),
):
    voucher = await db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(404, "Voucher not found")

    if data.code is not None:
        new_code = data.code.upper().strip()
        if new_code != voucher.code:
            existing = await db.execute(
                select(Voucher).where(func.upper(Voucher.code) == new_code, Voucher.id != voucher_id)
            )
            if existing.scalar():
                raise HTTPException(409, "A voucher with this code already exists")
            voucher.code = new_code
    if data.program_name is not None:
        voucher.program_name = data.program_name.strip()
    if data.discount_type is not None:
        if data.discount_type not in ("percent", "flat", "full"):
            raise HTTPException(400, "discount_type must be 'percent', 'flat', or 'full'")
        voucher.discount_type = data.discount_type
    if data.discount_value is not None:
        voucher.discount_value = data.discount_value
    if data.applicable_permit_codes is not None:
        voucher.applicable_permit_codes = data.applicable_permit_codes
    if data.max_uses is not None:
        voucher.max_uses = data.max_uses
    if data.is_active is not None:
        voucher.is_active = data.is_active
    if data.expires_at is not None:
        voucher.expires_at = data.expires_at

    await db.flush()
    await db.refresh(voucher)
    return _to_read(voucher)


@admin_router.post("/{voucher_id}/delete", status_code=204)
async def delete_voucher(voucher_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    voucher = await db.get(Voucher, voucher_id)
    if not voucher:
        raise HTTPException(404, "Voucher not found")
    await db.delete(voucher)
    await db.flush()


# ── Student endpoint ─────────────────────────────────────────────────────────

@router.post("/validate", response_model=VoucherValidateResponse)
async def validate_voucher(
    data: VoucherValidateRequest,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user_or_impersonated),
):
    """Validate a voucher code for a specific permit type. Returns discount info or error."""
    if not await vouchers_are_enabled(db):
        return VoucherValidateResponse(valid=False, message="Vouchers are not enabled for this school.")

    result = await db.execute(
        select(Voucher).where(func.upper(Voucher.code) == data.code.upper().strip())
    )
    voucher = result.scalar()
    if not voucher:
        return VoucherValidateResponse(valid=False, message="Invalid voucher code.")

    error = _validate_voucher(voucher, data.permit_type_code)
    if error:
        return VoucherValidateResponse(valid=False, message=error)

    return VoucherValidateResponse(
        valid=True,
        discount_type=voucher.discount_type,
        discount_value=voucher.discount_value,
        program_name=voucher.program_name,
        message=_discount_description(voucher),
    )


def _discount_description(voucher: Voucher) -> str:
    if voucher.discount_type == "full":
        return f"{voucher.code}: 100% off ({voucher.program_name})"
    elif voucher.discount_type == "percent":
        return f"{voucher.code}: {voucher.discount_value}% off ({voucher.program_name})"
    else:
        return f"{voucher.code}: ${voucher.discount_value} off ({voucher.program_name})"


async def record_voucher_usage(
    db: AsyncSession,
    voucher: Voucher,
    student_name: str,
    student_email: str,
    student_id: str,
    permit_type_code: str,
    original_price: Decimal,
    final_price: Decimal,
) -> None:
    """Record a voucher usage for chargeback reporting."""
    usage = VoucherUsage(
        voucher_id=voucher.id,
        voucher_code=voucher.code,
        program_name=voucher.program_name,
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

class VoucherUsageRead(BaseModel):
    id: str
    voucher_code: str
    program_name: str
    student_name: str
    student_email: str
    student_id: str
    permit_type_code: str
    original_price: Decimal
    discount_amount: Decimal
    final_price: Decimal
    used_at: datetime


@admin_router.get("/usages", response_model=list[VoucherUsageRead])
async def list_voucher_usages(db: AsyncSession = Depends(get_db)):
    """List all voucher usages for chargeback reporting."""
    result = await db.execute(select(VoucherUsage).order_by(VoucherUsage.used_at.desc()))
    return [
        VoucherUsageRead(
            id=str(u.id),
            voucher_code=u.voucher_code,
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
async def export_voucher_usages(db: AsyncSession = Depends(get_db)):
    """Export voucher usages as CSV for department chargeback."""
    import csv
    import io
    from fastapi.responses import StreamingResponse

    result = await db.execute(select(VoucherUsage).order_by(VoucherUsage.used_at.desc()))
    usages = result.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Voucher Code", "Program/Department", "Student Name",
        "Student Email", "Student ID", "Permit Type", "Original Price",
        "Discount Amount", "Amount Charged",
    ])
    for u in usages:
        writer.writerow([
            u.used_at.strftime("%Y-%m-%d %H:%M") if u.used_at else "",
            u.voucher_code,
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
        headers={"Content-Disposition": "attachment; filename=voucher_chargebacks.csv"},
    )
