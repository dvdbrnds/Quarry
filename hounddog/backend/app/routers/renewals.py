"""Faculty/staff permit renewal via magic-link token."""

import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, require_admin
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.permit_type import PermitType
from ..models.renewal_token import RenewalToken
from ..services.email import send_renewal_email

router = APIRouter()


class SendCampaignRequest(BaseModel):
    permit_type_codes: list[str] | None = None
    expiring_within_days: int = 60
    token_valid_days: int = 30


class SendCampaignResult(BaseModel):
    sent: int
    skipped: int
    errors: list[str] = []


class RenewalInfo(BaseModel):
    permit_holder_name: str
    email: str
    plates: list[str]
    lot_assignment: str
    permit_type: str
    end_date: str | None
    expired: bool


class ConfirmRenewalRequest(BaseModel):
    plate: str | None = None


class ConfirmRenewalResponse(BaseModel):
    status: str
    message: str


@router.post("/send-campaign", response_model=SendCampaignResult)
async def send_renewal_campaign(
    data: SendCampaignRequest,
    db: AsyncSession = Depends(get_db),
    _admin: OktaUser = Depends(require_admin()),
):
    """Generate renewal tokens and send magic-link emails to faculty/staff with expiring permits."""
    today = date.today()
    cutoff = today + timedelta(days=data.expiring_within_days)

    query = select(Permit).where(
        Permit.status.in_(["active", "expired"]),
        Permit.deleted_at.is_(None),
        Permit.email.isnot(None),
        Permit.email != "",
    )

    if data.permit_type_codes:
        query = query.where(Permit.permit_type.in_(data.permit_type_codes))
    else:
        query = query.where(Permit.permit_type == "faculty_staff")

    query = query.where(
        Permit.end_date.isnot(None),
        Permit.end_date <= cutoff,
    )

    permits = (await db.execute(query)).scalars().all()

    sent = 0
    skipped = 0
    errors: list[str] = []

    for permit in permits:
        existing_token = (await db.execute(
            select(RenewalToken).where(
                RenewalToken.permit_id == permit.id,
                RenewalToken.used_at.is_(None),
                RenewalToken.expires_at > datetime.now(timezone.utc),
            )
        )).scalar()

        if existing_token:
            skipped += 1
            continue

        token = secrets.token_urlsafe(48)
        renewal = RenewalToken(
            token=token,
            permit_id=permit.id,
            email=permit.email,
            expires_at=datetime.now(timezone.utc) + timedelta(days=data.token_valid_days),
        )
        db.add(renewal)

        base_url = settings.cors_origins[0] if settings.cors_origins else settings.public_url
        renew_url = f"{base_url}/permits/renew/{token}"

        try:
            success = await send_renewal_email(
                recipient_email=permit.email,
                name=permit.name,
                permit_type=permit.permit_type,
                lot_assignment=permit.lot_assignment,
                end_date=permit.end_date.isoformat() if permit.end_date else "N/A",
                renew_url=renew_url,
            )
            if success:
                sent += 1
            else:
                errors.append(f"Email send failed for {permit.email}")
        except Exception as e:
            errors.append(f"Error sending to {permit.email}: {str(e)}")

    await db.flush()
    return SendCampaignResult(sent=sent, skipped=skipped, errors=errors)


@router.get("/{token}", response_model=RenewalInfo)
async def get_renewal_info(token: str, db: AsyncSession = Depends(get_db)):
    """Public endpoint — validate a renewal token and return permit info."""
    renewal = (await db.execute(
        select(RenewalToken).where(RenewalToken.token == token)
    )).scalar()

    if not renewal:
        raise HTTPException(404, "Invalid or expired renewal link")

    if renewal.used_at:
        raise HTTPException(400, "This renewal link has already been used")

    if renewal.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "This renewal link has expired. Please contact Parking Services.")

    permit = await db.get(Permit, renewal.permit_id)
    if not permit:
        raise HTTPException(404, "Permit not found")

    return RenewalInfo(
        permit_holder_name=permit.name,
        email=renewal.email,
        plates=permit.plates,
        lot_assignment=permit.lot_assignment,
        permit_type=permit.permit_type,
        end_date=permit.end_date.isoformat() if permit.end_date else None,
        expired=permit.status == "expired" or (permit.end_date is not None and permit.end_date < date.today()),
    )


@router.post("/{token}/confirm", response_model=ConfirmRenewalResponse)
async def confirm_renewal(
    token: str,
    data: ConfirmRenewalRequest,
    db: AsyncSession = Depends(get_db),
):
    """Public endpoint — confirm renewal, creating a new permit for the next period."""
    renewal = (await db.execute(
        select(RenewalToken).where(RenewalToken.token == token)
    )).scalar()

    if not renewal:
        raise HTTPException(404, "Invalid or expired renewal link")

    if renewal.used_at:
        raise HTTPException(400, "This renewal link has already been used")

    if renewal.expires_at < datetime.now(timezone.utc):
        raise HTTPException(400, "This renewal link has expired")

    permit = await db.get(Permit, renewal.permit_id)
    if not permit:
        raise HTTPException(404, "Permit not found")

    pt_result = await db.execute(
        select(PermitType).where(PermitType.code == permit.permit_type)
    )
    permit_type = pt_result.scalar()
    valid_days = permit_type.valid_days if permit_type else 730

    new_plate = data.plate.upper().strip() if data.plate else None
    plates = [new_plate] if new_plate else permit.plates

    new_permit = Permit(
        name=permit.name,
        email=permit.email,
        phone=permit.phone,
        student_id=permit.student_id,
        plates=plates,
        lot_assignment=permit.lot_assignment,
        permit_type=permit.permit_type,
        beacon_id=permit.beacon_id,
        start_date=date.today(),
        end_date=date.today() + timedelta(days=valid_days),
        status="active",
    )
    db.add(new_permit)

    if permit.status == "active":
        permit.status = "renewed"
    renewal.used_at = datetime.now(timezone.utc)
    renewal.new_plate = new_plate

    await db.flush()

    return ConfirmRenewalResponse(
        status="renewed",
        message=f"Your permit has been renewed through {new_permit.end_date.isoformat()}. No payment is required.",
    )
