"""Faculty/staff permit renewal via magic-link token."""

import secrets
import uuid as uuid_mod
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import OktaUser, get_current_user, require_admin
from ..config import settings
from ..database import get_db
from ..models.permit import Permit
from ..models.renewal_token import RenewalToken
from ..services.email import send_renewal_email
from ..services.permit_numbering import next_permit_number

router = APIRouter()


def _next_june_30(from_date: date | None = None) -> date:
    """Return the next June 30 that is in the future relative to from_date."""
    ref = from_date or date.today()
    target = date(ref.year, 6, 30)
    if target <= ref:
        target = date(ref.year + 1, 6, 30)
    return target


def _build_response_html(title: str, heading: str, message: str, success: bool = True) -> str:
    primary = settings.brand_primary_color or "#1a2744"
    accent = settings.brand_accent_color or "#c9a84c"
    brand = settings.brand_name or "Quarry"
    color = "#16a34a" if success else primary
    icon = "&#10003;" if success else "&#10005;"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; margin: 0; padding: 0; background: #f8f9fa; }}
.nav {{ background: {primary}; color: #f5f0e8; padding: 16px 24px; }}
.nav h1 {{ margin: 0; font-size: 18px; color: {accent}; }}
.container {{ max-width: 500px; margin: 60px auto; padding: 0 24px; text-align: center; }}
.icon {{ width: 64px; height: 64px; border-radius: 50%; background: {color}; color: white;
         font-size: 32px; line-height: 64px; margin: 0 auto 24px; }}
h2 {{ color: {primary}; margin-bottom: 12px; }}
p {{ color: #555; line-height: 1.6; }}
</style></head><body>
<div class="nav"><h1>{brand} Parking</h1></div>
<div class="container">
<div class="icon">{icon}</div>
<h2>{heading}</h2>
<p>{message}</p>
</div></body></html>"""


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

        base_url = settings.student_facing_url.rstrip("/")
        renew_url = f"{base_url}/api/renewals/{token}/quick-renew"
        decline_url = f"{base_url}/api/renewals/{token}/decline"

        try:
            success = await send_renewal_email(
                recipient_email=permit.email,
                name=permit.name,
                permit_type=permit.permit_type,
                lot_assignment=permit.lot_assignment,
                end_date=permit.end_date.isoformat() if permit.end_date else "June 30",
                renew_url=renew_url,
                decline_url=decline_url,
            )
            if success:
                sent += 1
            else:
                errors.append(f"Email send failed for {permit.email}")
        except Exception as e:
            errors.append(f"Error sending to {permit.email}: {str(e)}")

    await db.flush()
    return SendCampaignResult(sent=sent, skipped=skipped, errors=errors)


class SendSingleResult(BaseModel):
    status: str
    message: str
    token: str | None = None


class TestEmailRequest(BaseModel):
    email: str


@router.post("/send-test", response_model=SendSingleResult)
async def send_test_renewal_email(
    data: TestEmailRequest,
    _admin: OktaUser = Depends(require_admin()),
):
    """Send a sample renewal email to a given address for testing purposes."""
    base_url = settings.student_facing_url.rstrip("/")
    dummy_token = "test-preview-token"
    sample_renew = f"{base_url}/api/renewals/{dummy_token}/quick-renew"
    sample_decline = f"{base_url}/api/renewals/{dummy_token}/decline"

    success = await send_renewal_email(
        recipient_email=data.email,
        name="Test Employee",
        permit_type="faculty_staff",
        lot_assignment="Lot A, Lot B",
        end_date="2026-06-30",
        renew_url=sample_renew,
        decline_url=sample_decline,
    )

    return SendSingleResult(
        status="sent" if success else "failed",
        message=f"Test renewal email sent to {data.email}" if success
        else f"SMTP send failed for {data.email}",
    )


@router.post("/send/{permit_id}", response_model=SendSingleResult)
async def send_renewal_to_permit(
    permit_id: uuid_mod.UUID,
    db: AsyncSession = Depends(get_db),
    _user: OktaUser = Depends(get_current_user),
):
    """Send a renewal email to a single permit holder. Creates a fresh token even if one exists."""
    permit = await db.get(Permit, permit_id)
    if not permit or permit.deleted_at:
        raise HTTPException(404, "Permit not found")

    if not permit.email:
        raise HTTPException(400, "Permit has no email address")

    token = secrets.token_urlsafe(48)
    renewal = RenewalToken(
        token=token,
        permit_id=permit.id,
        email=permit.email,
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
    )
    db.add(renewal)

    base_url = settings.student_facing_url.rstrip("/")
    renew_url = f"{base_url}/api/renewals/{token}/quick-renew"
    decline_url = f"{base_url}/api/renewals/{token}/decline"

    success = await send_renewal_email(
        recipient_email=permit.email,
        name=permit.name,
        permit_type=permit.permit_type,
        lot_assignment=permit.lot_assignment,
        end_date=permit.end_date.isoformat() if permit.end_date else "June 30",
        renew_url=renew_url,
        decline_url=decline_url,
    )

    await db.flush()

    if success:
        return SendSingleResult(
            status="sent",
            message=f"Renewal email sent to {permit.email}",
            token=token,
        )
    return SendSingleResult(
        status="failed",
        message=f"SMTP send failed for {permit.email} — check server logs",
    )


@router.get("/{token}/quick-renew", response_class=HTMLResponse)
async def quick_renew(token: str, db: AsyncSession = Depends(get_db)):
    """One-click renewal from email button. Renews the permit and shows confirmation."""
    renewal = (await db.execute(
        select(RenewalToken).where(RenewalToken.token == token)
    )).scalar()

    if not renewal:
        return HTMLResponse(_build_response_html(
            "Invalid Link", "Link Not Found",
            "This renewal link is invalid. Please contact Parking Services.", False
        ), status_code=404)

    if renewal.used_at:
        if renewal.response == "renewed":
            return HTMLResponse(_build_response_html(
                "Already Renewed", "Already Renewed",
                "Your permit has already been renewed. No further action is needed."
            ))
        return HTMLResponse(_build_response_html(
            "Link Used", "Link Already Used",
            "This link has already been used. Please contact Parking Services if you need assistance.", False
        ))

    if renewal.expires_at < datetime.now(timezone.utc):
        return HTMLResponse(_build_response_html(
            "Link Expired", "Link Expired",
            "This renewal link has expired. Please contact Parking Services for assistance.", False
        ), status_code=400)

    permit = await db.get(Permit, renewal.permit_id)
    if not permit:
        return HTMLResponse(_build_response_html(
            "Not Found", "Permit Not Found",
            "The associated permit could not be found. Please contact Parking Services.", False
        ), status_code=404)

    new_end = _next_june_30()

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=permit.name,
        email=permit.email,
        phone=permit.phone,
        student_id=permit.student_id,
        plates=list(permit.plates),
        lot_assignment=permit.lot_assignment,
        permit_type=permit.permit_type,
        beacon_id=permit.beacon_id,
        start_date=date.today(),
        end_date=new_end,
        status="active",
    )
    db.add(new_permit)

    if permit.status == "active":
        permit.status = "renewed"
    renewal.used_at = datetime.now(timezone.utc)
    renewal.response = "renewed"

    await db.flush()
    await db.commit()

    end_str = new_end.strftime("%B %d, %Y")
    return HTMLResponse(_build_response_html(
        "Permit Renewed", "Thank You!",
        f"Your parking permit has been renewed through <strong>{end_str}</strong>. "
        f"Your lot assignment ({permit.lot_assignment}) remains the same. "
        f"No payment is required."
    ))


@router.get("/{token}/decline", response_class=HTMLResponse)
async def decline_renewal(token: str, db: AsyncSession = Depends(get_db)):
    """One-click decline from email button. Marks the permit as not renewing."""
    renewal = (await db.execute(
        select(RenewalToken).where(RenewalToken.token == token)
    )).scalar()

    if not renewal:
        return HTMLResponse(_build_response_html(
            "Invalid Link", "Link Not Found",
            "This renewal link is invalid. Please contact Parking Services.", False
        ), status_code=404)

    if renewal.used_at:
        if renewal.response == "declined":
            return HTMLResponse(_build_response_html(
                "Already Declined", "Already Declined",
                "You've already indicated you don't need your permit. "
                "If you change your mind, please contact Parking Services."
            ))
        if renewal.response == "renewed":
            return HTMLResponse(_build_response_html(
                "Already Renewed", "Already Renewed",
                "Your permit has already been renewed. If you'd like to cancel, "
                "please contact Parking Services."
            ))
        return HTMLResponse(_build_response_html(
            "Link Used", "Link Already Used",
            "This link has already been used.", False
        ))

    if renewal.expires_at < datetime.now(timezone.utc):
        return HTMLResponse(_build_response_html(
            "Link Expired", "Link Expired",
            "This renewal link has expired. Your permit will expire on June 30 as scheduled.", False
        ), status_code=400)

    permit = await db.get(Permit, renewal.permit_id)

    renewal.used_at = datetime.now(timezone.utc)
    renewal.response = "declined"

    if permit and not permit.deleted_at:
        permit.status = "expired"
        permit.deleted_at = datetime.now(timezone.utc)

    await db.flush()
    await db.commit()

    return HTMLResponse(_build_response_html(
        "Permit Declined", "Thank You",
        "We've recorded that you no longer need your parking permit. "
        "Your permit has been deactivated. If you change your mind, "
        "please contact Parking Services."
    ))


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

    new_end = _next_june_30()

    new_plate = data.plate.upper().strip() if data.plate else None
    plates = [new_plate] if new_plate else permit.plates

    new_permit = Permit(
        permit_number=await next_permit_number(db),
        name=permit.name,
        email=permit.email,
        phone=permit.phone,
        student_id=permit.student_id,
        plates=plates,
        lot_assignment=permit.lot_assignment,
        permit_type=permit.permit_type,
        beacon_id=permit.beacon_id,
        start_date=date.today(),
        end_date=new_end,
        status="active",
    )
    db.add(new_permit)

    if permit.status == "active":
        permit.status = "renewed"
    renewal.used_at = datetime.now(timezone.utc)
    renewal.response = "renewed"
    renewal.new_plate = new_plate

    await db.flush()

    return ConfirmRenewalResponse(
        status="renewed",
        message=f"Your permit has been renewed through {new_end.isoformat()}. No payment is required.",
    )
