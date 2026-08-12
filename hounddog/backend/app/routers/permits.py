import csv
import io
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, or_, desc, asc, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from decimal import Decimal

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings
from ..database import get_db
from ..services.lottery_runner import run_lottery, verify_lottery, LotteryResult
from ..models.audit_log import AuditLog
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.ticket import Ticket
from ..models.payment import Payment
from ..schemas.permit import (
    PermitCreate,
    PermitList,
    PermitRead,
    PermitUpdate,
    PermitImportPayload,
    PermitImportResult,
)
from ..services.permit_lifecycle import (
    compute_hold,
    find_duplicates,
    get_permit_stats,
)
from ..services.permit_numbering import next_permit_number
from ..services.timeutils import today_local
from ..services.lot_assignment import effective_lot_assignment, permit_lot_matches

router = APIRouter(dependencies=[Depends(get_current_user)])

SORTABLE_FIELDS = {
    "permit_number": Permit.permit_number,
    "name": Permit.name,
    "student_id": Permit.student_id,
    "status": Permit.status,
    "permit_type": Permit.permit_type,
    "lot_assignment": Permit.lot_assignment,
    "start_date": Permit.start_date,
    "end_date": Permit.end_date,
    "created_at": Permit.created_at,
}


def _permit_search_clause(search: str) -> ColumnElement[bool]:
    """Substring match on name/ID/permit # and any plate in the plates array."""
    like = f"%{search}%"
    # plates.any() is exact-only; array_to_string enables partial plate search-as-you-type
    return or_(
        Permit.name.ilike(like),
        Permit.student_id.ilike(like),
        Permit.permit_number.ilike(like),
        Permit.email.ilike(like),
        func.array_to_string(Permit.plates, ",").ilike(like),
    )


@router.get("/stats")
async def permit_stats(db: AsyncSession = Depends(get_db)):
    return await get_permit_stats(db)


@router.get("/live-status")
async def live_status(
    db: AsyncSession = Depends(get_db),
    current_user: OktaUser = Depends(get_current_user),
):
    """Real-time permit subscription status for admin monitoring."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    # Permit type capacity stats
    pts = (await db.execute(
        select(PermitType)
        .where(PermitType.is_active.is_(True))
        .order_by(PermitType.sort_order)
    )).scalars().all()

    type_stats = []
    for pt in pts:
        active_count = (await db.execute(
            select(func.count()).select_from(Permit).where(
                Permit.permit_type == pt.code,
                Permit.status == "active",
                Permit.deleted_at.is_(None),
            )
        )).scalar() or 0
        public_capacity = pt.max_capacity - int(pt.max_capacity * (pt.reserved_pct or 0) / 100)
        remaining = max(0, public_capacity - active_count)
        pct = round((active_count / pt.max_capacity * 100), 1) if pt.max_capacity > 0 else 0
        type_stats.append({
            "id": str(pt.id),
            "code": pt.code,
            "label": pt.label,
            "max_capacity": pt.max_capacity,
            "active_count": active_count,
            "remaining": remaining,
            "pct": pct,
            "is_purchasable_online": pt.is_purchasable_online,
            "requires_lottery": pt.requires_lottery,
        })

    # Open lottery cycle info
    from ..models.lottery_v2 import LotteryV2Cycle, LotteryV2Application
    cycle_result = await db.execute(
        select(LotteryV2Cycle)
        .where(LotteryV2Cycle.status.in_(["open", "drawn", "closed"]))
        .order_by(LotteryV2Cycle.created_at.desc())
        .limit(1)
    )
    cycle = cycle_result.scalar_one_or_none()
    lottery_cycle = None
    if cycle:
        app_count = (await db.execute(
            select(func.count()).select_from(LotteryV2Application)
            .where(LotteryV2Application.cycle_id == cycle.id)
        )).scalar() or 0
        lottery_cycle = {
            "id": str(cycle.id),
            "name": cycle.name,
            "status": cycle.status,
            "application_count": app_count,
            "auto_draw_threshold": cycle.auto_draw_threshold,
        }

    # Recent permits (last 24 hours)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    recent_result = await db.execute(
        select(Permit)
        .where(Permit.created_at >= cutoff, Permit.deleted_at.is_(None))
        .order_by(Permit.created_at.desc())
        .limit(20)
    )
    recent_permits = recent_result.scalars().all()

    # Build label lookup
    codes = list({p.permit_type for p in recent_permits if p.permit_type})
    label_map: dict[str, str] = {}
    if codes:
        pt_rows = await db.execute(
            select(PermitType.code, PermitType.label).where(PermitType.code.in_(codes))
        )
        for row in pt_rows:
            label_map[row.code] = row.label

    recent_list = []
    for p in recent_permits:
        recent_list.append({
            "id": str(p.id),
            "permit_number": p.permit_number,
            "name": p.name,
            "email": p.email,
            "plate": p.plates[0] if p.plates else "",
            "permit_type": p.permit_type,
            "permit_type_label": label_map.get(p.permit_type or "", p.permit_type or ""),
            "lot_assignment": p.lot_assignment,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "permit_types": type_stats,
        "lottery_cycle": lottery_cycle,
        "recent_permits": recent_list,
    }


@router.get("/duplicates")
async def list_duplicates(db: AsyncSession = Depends(get_db)):
    """Find all active permits that share a plate with another active permit."""
    result = await db.execute(
        select(Permit).where(Permit.status == "active", Permit.deleted_at.is_(None))
    )
    all_permits = result.scalars().all()

    plate_map: dict[str, list] = {}
    for p in all_permits:
        for plate in p.plates:
            plate_map.setdefault(plate.upper(), []).append(p)

    duplicates = []
    seen_ids = set()
    for plate, permits in plate_map.items():
        if len(permits) > 1:
            for p in permits:
                if p.id not in seen_ids:
                    seen_ids.add(p.id)
                    duplicates.append({
                        "id": str(p.id),
                        "permit_number": p.permit_number,
                        "name": p.name,
                        "plates": p.plates,
                        "conflicting_plate": plate,
                        "lot_assignment": p.lot_assignment,
                        "permit_type": p.permit_type,
                    })
    return duplicates


@router.get("", response_model=PermitList)
async def list_permits(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    search: str | None = None,
    status: str | None = None,
    lot: str | None = None,
    permit_type: str | None = None,
    max_age_years: int | None = Query(None, ge=1),
    sort: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Permit).where(Permit.deleted_at.is_(None))

    if max_age_years:
        cutoff = today_local() - timedelta(days=max_age_years * 365)
        query = query.where(Permit.start_date >= cutoff)

    if search:
        query = query.where(_permit_search_clause(search))
    if status:
        if status == "expiring_soon":
            today = today_local()
            soon = today + timedelta(days=30)
            query = query.where(
                Permit.status == "active",
                Permit.end_date.isnot(None),
                Permit.end_date <= soon,
                Permit.end_date >= today,
            )
        else:
            query = query.where(Permit.status == status)
    if lot:
        query = query.where(permit_lot_matches(lot))
    if permit_type:
        query = query.where(Permit.permit_type == permit_type)

    order_col = Permit.name
    order_dir = asc
    if sort:
        if sort.startswith("-"):
            order_dir = desc
            sort_field = sort[1:]
        else:
            sort_field = sort
        if sort_field in SORTABLE_FIELDS:
            order_col = SORTABLE_FIELDS[sort_field]

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    items = (
        await db.execute(
            query.order_by(order_dir(order_col)).offset((page - 1) * page_size).limit(page_size)
        )
    ).scalars().all()

    return PermitList(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=PermitRead, status_code=201)
async def create_permit(data: PermitCreate, db: AsyncSession = Depends(get_db)):
    fields = data.model_dump()
    type_lots: list[str] = []
    if fields.get("permit_type"):
        pt = (
            await db.execute(
                select(PermitType).where(PermitType.code == fields["permit_type"])
            )
        ).scalar_one_or_none()
        if pt:
            type_lots = list(pt.lot_assignments or [])
    # Custom lots on the permit supersede type defaults; empty → type defaults
    fields["lot_assignment"] = effective_lot_assignment(
        fields.get("lot_assignment"), type_lots
    )
    if not fields.get("permit_number"):
        fields["permit_number"] = await next_permit_number(db)
    permit = Permit(**fields)
    db.add(permit)
    await db.flush()
    await db.refresh(permit)
    await _notify_permit_change("created", 1)
    return permit


class AdminChargeRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    plates: list[str] = []
    student_id: str = ""
    lot_assignment: str = ""
    permit_type: str
    start_date: date | None = None
    end_date: date | None = None
    waive_fee: bool = False
    voucher_code: str | None = None


@router.post("/charge", status_code=201)
async def create_permit_with_charge(data: AdminChargeRequest, db: AsyncSession = Depends(get_db)):
    """Admin endpoint: create a permit with an optional charge. If not waived, a Stripe payment
    link is emailed to the permit holder and the permit stays pending_payment until paid."""
    from decimal import Decimal

    pt_result = await db.execute(
        select(PermitType).where(PermitType.code == data.permit_type)
    )
    pt = pt_result.scalar()
    if not pt:
        raise HTTPException(400, "Invalid permit type")

    permit_number = await next_permit_number(db)
    start = data.start_date or today_local()
    end = data.end_date or (start + timedelta(days=pt.valid_days))
    # Custom lots supersede type defaults
    lot_assignment = effective_lot_assignment(
        data.lot_assignment, list(pt.lot_assignments or [])
    )

    if data.waive_fee or pt.price <= 0:
        permit = Permit(
            permit_number=permit_number,
            name=data.name,
            email=data.email,
            phone=data.phone,
            plates=[p.upper().strip() for p in data.plates if p.strip()],
            student_id=data.student_id,
            lot_assignment=lot_assignment,
            permit_type=data.permit_type,
            start_date=start,
            end_date=end,
            status="active",
        )
        db.add(permit)
        await db.flush()
        await db.refresh(permit)
        await _notify_permit_change("created", 1)
        return {"permit_id": str(permit.id), "status": "active", "waived": True}

    # Calculate discounted price
    discounted_price = pt.price
    applied_voucher = None
    if data.voucher_code:
        from ..models.voucher import Voucher
        from .vouchers import _validate_voucher, vouchers_are_enabled

        if not await vouchers_are_enabled(db):
            raise HTTPException(400, "Vouchers are not enabled for this school.")

        voucher_result = await db.execute(
            select(Voucher).where(func.upper(Voucher.code) == data.voucher_code.upper().strip())
        )
        voucher = voucher_result.scalar()
        if voucher:
            error = _validate_voucher(voucher, data.permit_type)
            if not error:
                applied_voucher = voucher
                if voucher.discount_type == "full":
                    discounted_price = Decimal("0.00")
                elif voucher.discount_type == "percent":
                    discounted_price = pt.price * (1 - voucher.discount_value / 100)
                elif voucher.discount_type == "flat":
                    discounted_price = max(Decimal("0.00"), pt.price - voucher.discount_value)

    # Full waiver via voucher
    if applied_voucher and discounted_price <= 0:
        permit = Permit(
            permit_number=permit_number,
            name=data.name,
            email=data.email,
            phone=data.phone,
            plates=[p.upper().strip() for p in data.plates if p.strip()],
            student_id=data.student_id,
            lot_assignment=lot_assignment,
            permit_type=data.permit_type,
            start_date=start,
            end_date=end,
            status="active",
        )
        db.add(permit)
        applied_voucher.current_uses += 1
        from .vouchers import record_voucher_usage
        await record_voucher_usage(db, applied_voucher, data.name, data.email, data.student_id, data.permit_type, pt.price, Decimal("0.00"))
        await db.flush()
        await db.refresh(permit)
        await _notify_permit_change("created", 1)
        return {"permit_id": str(permit.id), "status": "active", "waived": True, "voucher_applied": True}

    # Create pending permit + Stripe checkout session
    if not settings.stripe_secret_key:
        raise HTTPException(503, "Stripe not configured")

    import stripe
    stripe.api_key = settings.stripe_secret_key

    permit = Permit(
        permit_number=permit_number,
        name=data.name,
        email=data.email,
        phone=data.phone,
        plates=[p.upper().strip() for p in data.plates if p.strip()],
        student_id=data.student_id,
        lot_assignment=lot_assignment,
        permit_type=data.permit_type,
        start_date=start,
        end_date=end,
        status="pending_payment",
    )
    db.add(permit)
    await db.flush()
    await db.refresh(permit)

    base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
    plate_str = ", ".join(p.upper().strip() for p in data.plates if p.strip()) or "N/A"

    session = stripe.checkout.Session.create(
        customer_email=data.email,
        line_items=[{
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": f"{pt.label} Parking Permit",
                    "description": f"Permit #{permit_number} | Plate: {plate_str}",
                },
                "unit_amount": int(discounted_price * 100),
            },
            "quantity": 1,
        }],
        mode="payment",
        payment_intent_data={
            "statement_descriptor_suffix": "PARK PERMIT",
            "metadata": {
                "type": "admin_permit_charge",
                "revenue_category": "parking_permits",
                "department": "parking_services",
                "gl_string": settings.gl_segment_separator.join([
                    settings.gl_fund, settings.gl_org,
                    settings.gl_account_permits, settings.gl_activity_permits,
                    settings.gl_segment5, settings.gl_segment6,
                ]),
                "gl_fund": settings.gl_fund,
                "gl_org": settings.gl_org,
                "gl_account": settings.gl_account_permits,
                "gl_activity": settings.gl_activity_permits,
                "permit_type_code": pt.code,
                "permit_type_label": pt.label,
                "permit_id": str(permit.id),
                "permit_number": permit_number,
                "plate": plate_str,
                "institution": settings.school_name or "moravian",
            },
        },
        success_url=f"{base_url}/parking?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{base_url}/parking?payment=cancelled",
        metadata={
            "type": "admin_permit_charge",
            "permit_id": str(permit.id),
            "permit_type_code": pt.code,
            "permit_type_label": pt.label,
            "permit_number": permit_number,
            "voucher_code": applied_voucher.code if applied_voucher else "",
        },
    )

    permit.stripe_session_id = session.id
    if applied_voucher:
        applied_voucher.current_uses += 1
        from .vouchers import record_voucher_usage
        await record_voucher_usage(db, applied_voucher, data.name, data.email, data.student_id, data.permit_type, pt.price, discounted_price)
    await db.flush()
    await _notify_permit_change("created", 1)

    # Send payment link email
    amount_display = f"${discounted_price:.2f}"
    try:
        from ..services.email import send_payment_link_email
        await send_payment_link_email(
            recipient_email=data.email,
            recipient_name=data.name,
            permit_type_label=pt.label,
            permit_number=permit_number,
            amount_display=amount_display,
            checkout_url=session.url,
        )
    except Exception:
        pass  # best-effort, admin sees the URL in the response

    return {
        "permit_id": str(permit.id),
        "status": "pending_payment",
        "waived": False,
        "checkout_url": session.url,
        "amount": str(discounted_price),
        "voucher_applied": applied_voucher is not None,
    }


@router.get("/{permit_id}", response_model=PermitRead)
async def get_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    return permit


@router.put("/{permit_id}", response_model=PermitRead)
async def update_permit(
    permit_id: uuid.UUID, data: PermitUpdate, db: AsyncSession = Depends(get_db)
):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        if field == "lot_assignment":
            type_lots: list[str] = []
            type_code = data.permit_type if data.permit_type is not None else permit.permit_type
            if type_code:
                pt = (
                    await db.execute(
                        select(PermitType).where(PermitType.code == type_code)
                    )
                ).scalar_one_or_none()
                if pt:
                    type_lots = list(pt.lot_assignments or [])
            # Custom lots supersede type defaults; clearing lots falls back to type
            value = effective_lot_assignment(value, type_lots)
        setattr(permit, field, value)

    await db.flush()
    await db.refresh(permit)
    await _notify_permit_change("updated", 1)
    return permit


class ReassignRequest(BaseModel):
    new_permit_type: str
    lot_assignment: str | None = None


class ReassignPreview(BaseModel):
    old_type: str
    old_label: str
    old_price: str
    new_type: str
    new_label: str
    new_price: str
    difference: str
    action: str  # "charge", "refund", or "none"


@router.post("/{permit_id}/reassign-preview")
async def reassign_preview(
    permit_id: uuid.UUID,
    data: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Preview the financial impact of reassigning a permit to a different type."""
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    old_pt = (
        await db.execute(select(PermitType).where(PermitType.code == permit.permit_type))
    ).scalars().first()
    new_pt = (
        await db.execute(select(PermitType).where(PermitType.code == data.new_permit_type))
    ).scalars().first()

    old_price = old_pt.price if old_pt else Decimal("0.00")
    new_price = new_pt.price if new_pt else Decimal("0.00")
    diff = new_price - old_price

    if diff > 0:
        action = "charge"
    elif diff < 0:
        action = "refund"
    else:
        action = "none"

    return ReassignPreview(
        old_type=permit.permit_type or "",
        old_label=old_pt.label if old_pt else permit.permit_type or "",
        old_price=str(old_price),
        new_type=data.new_permit_type,
        new_label=new_pt.label if new_pt else data.new_permit_type,
        new_price=str(new_price),
        difference=str(abs(diff)),
        action=action,
    )


@router.post("/{permit_id}/reassign")
async def reassign_permit(
    permit_id: uuid.UUID,
    data: ReassignRequest,
    db: AsyncSession = Depends(get_db),
    admin: OktaUser = Depends(require_admin()),
):
    """Reassign a permit to a different type, handling billing or refunds automatically.

    - Upgrade (new costs more): creates a Stripe checkout session and emails the student.
    - Downgrade (new costs less): issues a partial Stripe refund.
    - Same price: just updates the permit type and lots.
    """
    import logging
    logger = logging.getLogger("quarry.permits")

    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    old_pt = (
        await db.execute(select(PermitType).where(PermitType.code == permit.permit_type))
    ).scalars().first()
    new_pt = (
        await db.execute(select(PermitType).where(PermitType.code == data.new_permit_type))
    ).scalars().first()
    if not new_pt:
        raise HTTPException(400, "Target permit type not found")

    old_price = old_pt.price if old_pt else Decimal("0.00")
    new_price = new_pt.price if new_pt else Decimal("0.00")
    diff = new_price - old_price

    new_lots = data.lot_assignment
    if new_lots is None:
        new_lots = ", ".join(new_pt.lot_assignments) if new_pt.lot_assignments else ""

    result: dict = {
        "permit_id": str(permit.id),
        "old_type": old_pt.label if old_pt else permit.permit_type,
        "new_type": new_pt.label,
    }

    if diff > 0:
        # ── Upgrade: charge the difference via Stripe ──
        if not permit.email:
            raise HTTPException(400, "Permit has no email — cannot send payment link")
        if not settings.stripe_secret_key:
            raise HTTPException(503, "Stripe not configured")

        import stripe
        stripe.api_key = settings.stripe_secret_key

        base_url = settings.cors_origins[0] if settings.cors_origins else "http://localhost:5173"
        plate_str = ", ".join(permit.plates) if permit.plates else "N/A"
        permit_number = permit.permit_number or ""

        session = stripe.checkout.Session.create(
            customer_email=permit.email,
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {
                        "name": f"Upgrade to {new_pt.label}",
                        "description": (
                            f"Permit #{permit_number} | "
                            f"{old_pt.label if old_pt else permit.permit_type} → {new_pt.label} | "
                            f"Plate: {plate_str}"
                        ),
                    },
                    "unit_amount": int(diff * 100),
                },
                "quantity": 1,
            }],
            mode="payment",
            payment_intent_data={
                "statement_descriptor_suffix": "PARK UPGRADE",
                "metadata": {
                    "type": "admin_permit_charge",
                    "revenue_category": "parking_permits",
                    "department": "parking_services",
                    "permit_id": str(permit.id),
                    "permit_number": permit_number,
                    "permit_type_code": new_pt.code,
                    "permit_type_label": new_pt.label,
                    "old_permit_type": permit.permit_type or "",
                    "plate": plate_str,
                    "institution": settings.school_name or "moravian",
                    "reassign_action": "upgrade",
                },
            },
            success_url=f"{base_url}/parking?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{base_url}/parking?payment=cancelled",
            metadata={
                "type": "admin_permit_charge",
                "permit_id": str(permit.id),
                "permit_type_code": new_pt.code,
                "permit_type_label": new_pt.label,
                "permit_number": permit_number,
                "reassign_action": "upgrade",
            },
        )

        # Update the permit immediately
        permit.permit_type = new_pt.code
        permit.lot_assignment = effective_lot_assignment(new_lots, list(new_pt.lot_assignments or []))
        permit.stripe_session_id = session.id
        await db.flush()
        await _notify_permit_change("updated", 1)

        # Email the student
        try:
            from ..services.email import send_payment_link_email
            await send_payment_link_email(
                recipient_email=permit.email,
                recipient_name=permit.name,
                permit_type_label=new_pt.label,
                permit_number=permit_number,
                amount_display=f"${diff:.2f}",
                checkout_url=session.url,
            )
        except Exception:
            pass

        logger.info(
            "Admin %s reassigned permit %s: %s → %s, charge $%s",
            admin.email, permit.id, old_pt.label if old_pt else "?", new_pt.label, diff,
        )
        result.update({
            "action": "charge",
            "charge_amount": str(diff),
            "checkout_url": session.url,
            "email_sent": True,
        })

    elif diff < 0:
        # ── Downgrade: issue a partial Stripe refund ──
        refund_amount = abs(diff)

        # Find the original payment
        pay_result = await db.execute(
            select(Payment).where(
                func.lower(Payment.payer_email) == (permit.email or "").lower(),
                Payment.payment_type.in_([
                    "lottery_v2_permit", "lottery_permit",
                    "permit_purchase", "standalone_permit_purchase",
                    "direct_permit_purchase", "admin_permit_charge",
                ]),
            ).order_by(Payment.amount.desc()).limit(1)
        )
        payment = pay_result.scalar()

        stripe_id = None
        if payment and payment.stripe_payment_id:
            stripe_id = payment.stripe_payment_id
        elif permit.stripe_session_id:
            stripe_id = permit.stripe_session_id

        refund_result: dict = {"action": "refund", "refund_amount": str(refund_amount)}

        if stripe_id and settings.stripe_secret_key:
            import stripe
            stripe.api_key = settings.stripe_secret_key

            try:
                # Resolve checkout session to payment intent if needed
                if stripe_id.startswith("cs_"):
                    sess = stripe.checkout.Session.retrieve(stripe_id)
                    stripe_id = sess.payment_intent

                refund = stripe.Refund.create(
                    payment_intent=stripe_id,
                    amount=int(refund_amount * 100),
                    reason="requested_by_customer",
                    metadata={
                        "type": "permit_reassign_refund",
                        "permit_id": str(permit.id),
                        "student_email": permit.email or "",
                        "old_type": permit.permit_type or "",
                        "new_type": new_pt.code,
                        "refund_amount": str(refund_amount),
                        "admin": admin.email or admin.sub,
                    },
                )
                refund_result["refund_id"] = refund.id
                refund_result["refund_status"] = refund.status
                logger.info(
                    "Admin %s reassigned permit %s: %s → %s, refund $%s (refund %s)",
                    admin.email, permit.id, old_pt.label if old_pt else "?",
                    new_pt.label, refund_amount, refund.id,
                )
            except Exception as e:
                logger.warning("Stripe refund failed for reassignment: %s", e)
                refund_result["refund_error"] = str(e)
                refund_result["manual_refund_needed"] = True
        else:
            refund_result["manual_refund_needed"] = True
            refund_result["reason"] = "No Stripe payment found on record"

        # Update the permit regardless of refund success
        permit.permit_type = new_pt.code
        permit.lot_assignment = effective_lot_assignment(new_lots, list(new_pt.lot_assignments or []))
        await db.flush()
        await _notify_permit_change("updated", 1)

        result.update(refund_result)

    else:
        # ── Same price: just update ──
        permit.permit_type = new_pt.code
        permit.lot_assignment = effective_lot_assignment(new_lots, list(new_pt.lot_assignments or []))
        await db.flush()
        await _notify_permit_change("updated", 1)

        result["action"] = "none"
        result["message"] = "Permit type changed — no price difference"

    return result


@router.delete("/{permit_id}", status_code=204)
async def delete_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")
    permit.deleted_at = datetime.now(timezone.utc)
    await db.flush()
    await _notify_permit_change("deleted", 1)


class BulkStatusRequest(BaseModel):
    ids: list[str]
    status: str


@router.post("/bulk-status")
async def bulk_status(
    data: BulkStatusRequest, db: AsyncSession = Depends(get_db)
):
    valid_statuses = {"active", "expired", "revoked", "suspended"}
    if data.status not in valid_statuses:
        raise HTTPException(400, f"Invalid status. Must be one of: {valid_statuses}")

    updated = 0
    for permit_id in data.ids:
        try:
            permit = await db.get(Permit, uuid.UUID(permit_id))
        except ValueError:
            continue
        if permit and not permit.deleted_at:
            permit.status = data.status
            updated += 1

    await db.flush()
    if updated:
        await _notify_permit_change("bulk_status", updated)
    return {"updated": updated, "status": data.status}


@router.post("/{permit_id}/renew", response_model=PermitRead)
async def renew_permit(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    old = await db.get(Permit, permit_id)
    if not old or old.deleted_at:
        raise HTTPException(404, "Permit not found")

    old.status = "renewed"

    # Faculty/staff permits always expire on June 30
    if old.permit_type == "faculty_staff":
        new_start = today_local()
        target = date(new_start.year, 6, 30)
        if target <= new_start:
            target = date(new_start.year + 1, 6, 30)
        new_end = target
    else:
        valid_days = 365
        if old.permit_type:
            pt_result = await db.execute(
                select(PermitType).where(PermitType.code == old.permit_type)
            )
            pt = pt_result.scalar()
            if pt and pt.valid_days:
                valid_days = pt.valid_days
        new_start = today_local()
        new_end = new_start + timedelta(days=valid_days)

    renewed = Permit(
        permit_number=await next_permit_number(db),
        name=old.name,
        student_id=old.student_id,
        email=old.email,
        phone=old.phone,
        plates=list(old.plates),
        lot_assignment=old.lot_assignment,
        permit_type=old.permit_type,
        beacon_id=old.beacon_id,
        start_date=new_start,
        end_date=new_end,
        status="active",
    )
    db.add(renewed)
    await db.flush()
    await db.refresh(renewed)
    await _notify_permit_change("renewed", 1)
    return renewed


@router.get("/{permit_id}/history")
async def permit_history(permit_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    from ..models.lottery_v2 import LotteryV2Application

    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    has_hold, unpaid_amount = await compute_hold(db, permit)

    tickets_result = await db.execute(
        select(Ticket).where(
            Ticket.plate.in_(permit.plates)
        ).order_by(desc(Ticket.issued_at)).limit(50)
    )
    tickets = tickets_result.scalars().all()

    ticket_ids = [t.id for t in tickets]
    ticket_payment_filter = Payment.ticket_id.in_(ticket_ids) if ticket_ids else False

    permit_payment_types = (
        "permit_purchase", "lottery_permit", "lottery_v2_permit",
        "standalone_permit_purchase", "direct_permit_purchase",
        "admin_permit_charge",
    )
    permit_payment_filter = or_(
        Payment.payer_email == permit.email,
        Payment.plate.in_(permit.plates),
    ) if permit.email else Payment.plate.in_(permit.plates)

    payments_result = await db.execute(
        select(Payment).where(
            or_(
                ticket_payment_filter,
                (Payment.payment_type.in_(permit_payment_types)) & permit_payment_filter,
            )
        ).order_by(desc(Payment.created_at))
    )
    payments = payments_result.scalars().all()

    # Build timeline from lifecycle events instead of raw audit log
    timeline: list[dict] = []

    # Permit creation
    if permit.created_at:
        timeline.append({
            "timestamp": permit.created_at.isoformat(),
            "summary": "Permit created",
            "action": "CREATE",
            "user_email": permit.email or "system",
        })

    # Lottery application lifecycle
    app_result = await db.execute(
        select(LotteryV2Application).where(
            LotteryV2Application.student_email == permit.email,
            LotteryV2Application.plate == (permit.plates[0] if permit.plates else ""),
            LotteryV2Application.status.in_(["accepted", "selected", "waitlisted", "paid"]),
        ).order_by(desc(LotteryV2Application.created_at)).limit(1)
    )
    app = app_result.scalars().first()
    if app:
        timeline.append({
            "timestamp": app.created_at.isoformat(),
            "summary": "Application submitted",
            "action": "APPLY",
            "user_email": app.student_email,
        })
        if app.status in ("selected", "accepted", "paid") and app.updated_at and app.updated_at != app.created_at:
            timeline.append({
                "timestamp": app.updated_at.isoformat(),
                "summary": f"Application status: {app.status}",
                "action": "UPDATE",
                "user_email": "system",
            })

    # Payment events
    for pay in payments:
        label = pay.description or pay.payment_type or "Payment"
        timeline.append({
            "timestamp": (pay.paid_at or pay.created_at).isoformat(),
            "summary": f"{label} — ${pay.amount}",
            "action": "PAYMENT",
            "user_email": pay.payer_email or permit.email or "—",
        })

    # Status changes from audit log (only meaningful mutations, not GETs)
    audit_result = await db.execute(
        select(AuditLog).where(
            AuditLog.resource_type == "permits",
            AuditLog.resource_id == str(permit_id),
            AuditLog.action.in_(["POST", "PUT", "PATCH", "DELETE"]),
        ).order_by(desc(AuditLog.timestamp)).limit(50)
    )
    for a in audit_result.scalars().all():
        timeline.append({
            "timestamp": a.timestamp.isoformat(),
            "summary": a.summary,
            "action": a.action,
            "user_email": a.user_email,
        })

    timeline.sort(key=lambda e: e["timestamp"])

    prior_result = await db.execute(
        select(Permit).where(
            Permit.id != permit_id,
            Permit.deleted_at.is_(None),
            or_(
                Permit.student_id == permit.student_id,
                *[Permit.plates.any(p) for p in permit.plates]
            ) if permit.student_id else
            or_(*[Permit.plates.any(p) for p in permit.plates])
        ).order_by(desc(Permit.created_at)).limit(20)
    )
    prior_permits = prior_result.scalars().all()

    duplicates = await find_duplicates(db, permit.plates, exclude_id=permit.id)

    return {
        "permit": permit,
        "has_hold": has_hold,
        "unpaid_amount": str(unpaid_amount),
        "tickets": [
            {
                "id": str(t.id),
                "plate": t.plate,
                "lot": t.lot,
                "violation_type": t.violation_type,
                "fine_amount": str(t.fine_amount),
                "status": t.status,
                "issued_at": t.issued_at.isoformat() if t.issued_at else None,
            }
            for t in tickets
        ],
        "payments": [
            {
                "id": str(p.id),
                "ticket_id": str(p.ticket_id) if p.ticket_id else None,
                "amount": str(p.amount),
                "method": p.method,
                "payment_type": p.payment_type,
                "description": p.description,
                "status": "paid",
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in payments
        ],
        "audit_log": timeline,
        "prior_permits": [
            {
                "id": str(p.id),
                "permit_number": p.permit_number,
                "name": p.name,
                "permit_type": p.permit_type,
                "status": p.status,
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "end_date": p.end_date.isoformat() if p.end_date else None,
            }
            for p in prior_permits
        ],
        "duplicates": duplicates,
    }


@router.post("/import", response_model=PermitImportResult)
async def import_permits(
    payload: PermitImportPayload, db: AsyncSession = Depends(get_db)
):
    inserted = 0
    updated = 0
    skipped = 0

    for row in payload.permits:
        plate = row.plate_normalized.upper().strip()
        if not plate:
            skipped += 1
            continue

        existing = (
            await db.execute(
                select(Permit).where(
                    Permit.plates.any(plate), Permit.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if existing:
            if row.owner_name and row.owner_name != existing.name:
                existing.name = row.owner_name
            if row.email:
                existing.email = row.email
            if row.lot_zone:
                existing.lot_assignment = row.lot_zone
            if row.permit_type:
                existing.permit_type = row.permit_type
            if row.permit_status:
                existing.status = row.permit_status
            updated += 1
        else:
            start = None
            if row.issued_date:
                try:
                    start = date.fromisoformat(row.issued_date)
                except ValueError:
                    start = None

            end = None
            if row.expiration_date:
                try:
                    end = date.fromisoformat(row.expiration_date)
                except ValueError:
                    end = None

            permit = Permit(
                name=row.owner_name or plate,
                email=row.email or None,
                plates=[plate],
                lot_assignment=row.lot_zone,
                permit_type=row.permit_type,
                status=row.permit_status,
                permit_number=row.permit_number or None,
                start_date=start or today_local(),
                end_date=end,
            )
            db.add(permit)
            inserted += 1

    await db.flush()
    if inserted + updated > 0:
        await _notify_permit_change("imported", inserted + updated)
    return PermitImportResult(inserted=inserted, updated=updated, skipped=skipped)


@router.post("/import-csv", response_model=PermitImportResult)
async def import_permits_csv(
    file: UploadFile = File(...), db: AsyncSession = Depends(get_db)
):
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    inserted = 0
    updated = 0
    skipped = 0

    for row in reader:
        plate = (row.get("plate_normalized") or row.get("plate", "")).upper().strip()
        if not plate:
            skipped += 1
            continue

        existing = (
            await db.execute(
                select(Permit).where(
                    Permit.plates.any(plate), Permit.deleted_at.is_(None)
                )
            )
        ).scalar_one_or_none()

        if existing:
            updated += 1
        else:
            end = None
            exp_str = row.get("expiration_date", "")
            if exp_str:
                try:
                    end = date.fromisoformat(exp_str)
                except ValueError:
                    end = None

            permit = Permit(
                name=row.get("owner_name", plate),
                email=row.get("email") or None,
                plates=[plate],
                lot_assignment=row.get("lot_zone", ""),
                permit_type=row.get("permit_type", "student"),
                status=row.get("permit_status", "active"),
                permit_number=row.get("permit_number") or None,
                start_date=today_local(),
                end_date=end,
            )
            db.add(permit)
            inserted += 1

    await db.flush()
    if inserted + updated > 0:
        await _notify_permit_change("imported", inserted + updated)
    return PermitImportResult(inserted=inserted, updated=updated, skipped=skipped)


@router.get("/export/csv")
async def export_permits(
    status: str | None = None,
    permit_type: str | None = None,
    lot: str | None = None,
    search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(Permit).where(Permit.deleted_at.is_(None))
    if status:
        query = query.where(Permit.status == status)
    if permit_type:
        query = query.where(Permit.permit_type == permit_type)
    if lot:
        query = query.where(Permit.lot_assignment == lot)
    if search:
        query = query.where(_permit_search_clause(search))
    permits = (await db.execute(query.order_by(Permit.name))).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "permit_number", "name", "email", "phone",
        "plates", "lot_assignment", "permit_type", "beacon_id",
        "status", "start_date", "end_date", "created_at",
    ])
    for p in permits:
        writer.writerow([
            p.permit_number or "",
            p.name,
            p.email or "",
            p.phone or "",
            ";".join(p.plates),
            p.lot_assignment,
            p.permit_type,
            p.beacon_id or "",
            p.status,
            p.start_date.isoformat() if p.start_date else "",
            p.end_date.isoformat() if p.end_date else "",
            p.created_at.isoformat() if p.created_at else "",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=permits.csv"},
    )


@router.get("/emails")
async def permit_holder_emails(
    status: str = "active",
    db: AsyncSession = Depends(get_db),
):
    """Get emails for all permit holders, cross-referencing applications for gaps."""
    permits = (
        await db.execute(
            select(Permit)
            .where(Permit.status == status, Permit.deleted_at.is_(None))
            .order_by(Permit.name)
        )
    ).scalars().all()

    # Build a plate-to-email lookup from permit applications
    app_emails = await db.execute(
        text("""
            SELECT UPPER(plate) AS plate, student_email
            FROM permit_applications
            WHERE student_email IS NOT NULL AND student_email != ''
            ORDER BY created_at DESC
        """)
    )
    plate_email_map: dict[str, str] = {}
    for row in app_emails.mappings().all():
        plate_email_map.setdefault(row["plate"], row["student_email"])

    results = []
    has_email = 0
    missing_email = 0

    for p in permits:
        email = p.email
        source = "permit" if email else None

        if not email:
            for plate in p.plates:
                email = plate_email_map.get(plate.upper())
                if email:
                    source = "application"
                    break

        if email:
            has_email += 1
        else:
            missing_email += 1

        results.append({
            "id": str(p.id),
            "name": p.name,
            "email": email,
            "email_source": source,
            "student_id": p.student_id,
            "plates": p.plates,
            "permit_type": p.permit_type,
            "lot_assignment": p.lot_assignment,
            "status": p.status,
        })

    return {
        "total": len(results),
        "has_email": has_email,
        "missing_email": missing_email,
        "permits": results,
    }


@router.get("/emails/csv")
async def export_permit_emails_csv(
    status: str = "active",
    db: AsyncSession = Depends(get_db),
):
    """Export permit holder emails as CSV, cross-referencing applications for gaps."""
    data = await permit_holder_emails(status=status, db=db)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "email", "email_source", "student_id", "plates", "permit_type", "lot_assignment"])
    for p in data["permits"]:
        writer.writerow([
            p["name"],
            p["email"] or "",
            p["email_source"] or "missing",
            p["student_id"],
            ";".join(p["plates"]),
            p["permit_type"],
            p["lot_assignment"],
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=permit-emails-{status}.csv"},
    )


@router.get("/duplicates")
async def list_duplicate_permits(db: AsyncSession = Depends(get_db)):
    """Return groups of active permits that share at least one plate."""
    result = await db.execute(
        select(Permit).where(Permit.status == "active", Permit.deleted_at.is_(None))
    )
    active = result.scalars().all()

    plate_map: dict[str, list[Permit]] = {}
    for permit in active:
        for plate in permit.plates:
            key = plate.upper().strip()
            if key:
                plate_map.setdefault(key, []).append(permit)

    groups: list[dict] = []
    seen_ids: set = set()
    for plate, permits_for_plate in plate_map.items():
        if len(permits_for_plate) < 2:
            continue
        ids = tuple(sorted(str(p.id) for p in permits_for_plate))
        if ids in seen_ids:
            continue
        seen_ids.add(ids)
        groups.append({
            "shared_plate": plate,
            "permits": [
                {
                    "id": str(p.id),
                    "permit_number": p.permit_number,
                    "name": p.name,
                    "student_id": p.student_id,
                    "plates": p.plates,
                    "lot_assignment": p.lot_assignment,
                    "permit_type": p.permit_type,
                    "status": p.status,
                }
                for p in permits_for_plate
            ],
        })

    return {"duplicate_groups": groups, "total": len(groups)}


async def _notify_permit_change(action: str, count: int):
    """Send APNs push to devices on permit change."""
    from ..services.apns import send_permit_push
    await send_permit_push(action, count)


# ── Lottery endpoints ──


@router.post("/types/{permit_type_id}/run-lottery")
async def run_permit_lottery(
    permit_type_id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: OktaUser = Depends(get_current_user),
):
    """Run the lottery for a permit type. Admin only."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    try:
        result = await run_lottery(
            db=db,
            permit_type_id=permit_type_id,
            run_by=current_user.email or "unknown",
            force=force,
        )
        await db.commit()

        return {
            "success": True,
            "permit_type": result.permit_type_name,
            "strategy": result.strategy,
            "seed": result.seed,
            "seed_hash": result.seed_hash,
            "total_applicants": result.total_applicants,
            "eligible_applicants": result.eligible_applicants,
            "filtered": {
                "test_entries": result.filtered_test_entries,
                "unpaid_citations": result.filtered_unpaid_citations,
            },
            "spots_available": result.spots_available,
            "selected": result.selected_count,
            "waitlisted": result.waitlisted_count,
            "warnings": result.lot_assignment_warnings,
            "run_at": result.run_at.isoformat() if result.run_at else None,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/types/{permit_type_id}/lottery-results")
async def get_lottery_results(
    permit_type_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: OktaUser = Depends(get_current_user),
):
    """Get the results of the most recent lottery draw. Admin only."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    audit_result = await db.execute(
        text("""
            SELECT * FROM lottery_audit_log
            WHERE permit_type_id = :ptid
            ORDER BY run_at DESC LIMIT 1
        """),
        {"ptid": permit_type_id},
    )
    audit = audit_result.mappings().one_or_none()
    if not audit:
        raise HTTPException(status_code=404, detail="No lottery has been run for this permit type")

    apps_result = await db.execute(
        text("""
            SELECT id, student_name, student_email, class_year, plate,
                   status, lottery_rank, waitlist_position, assigned_lot,
                   offer_expires_at, admin_notes
            FROM permit_applications
            WHERE permit_type_id = :ptid
              AND status IN ('selected', 'waitlisted', 'ineligible')
            ORDER BY lottery_rank NULLS LAST, waitlist_position NULLS LAST
        """),
        {"ptid": permit_type_id},
    )
    applications = [dict(row) for row in apps_result.mappings().all()]

    for app in applications:
        for key in ("id", "offer_expires_at"):
            if key in app and app[key] is not None:
                app[key] = str(app[key])

    return {
        "audit": {
            "strategy": audit["strategy"],
            "seed_hash": audit["seed_hash"],
            "total_applicants": audit["total_applicants"],
            "eligible_applicants": audit["eligible_applicants"],
            "spots_available": audit["spots_available"],
            "selected_count": audit["selected_count"],
            "waitlisted_count": audit["waitlisted_count"],
            "filtered_test_entries": audit.get("filtered_test_entries", 0),
            "filtered_unpaid_citations": audit.get("filtered_unpaid_citations", 0),
            "run_at": str(audit["run_at"]),
            "run_by": audit["run_by"],
        },
        "applications": applications,
    }


@router.post("/types/{permit_type_id}/verify-lottery")
async def verify_permit_lottery(
    permit_type_id: str,
    seed: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: OktaUser = Depends(get_current_user),
):
    """Verify a lottery draw by providing the original seed. Admin only."""
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    verification = await verify_lottery(db, permit_type_id, seed)
    return verification
