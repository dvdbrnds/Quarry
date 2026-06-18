from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.api_key import get_device
from ..database import get_db
from ..models.device import Device
from ..models.lot import ParkingLot
from ..models.permit import Permit
from ..schemas.sync import (
    PushTokenRegister,
    SyncLotsResponse,
    SyncPermitsResponse,
    SyncStatusResponse,
    TicketUpload,
)

router = APIRouter()


@router.get("/permits", response_model=SyncPermitsResponse)
async def sync_permits(
    since: datetime | None = Query(None),
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    full_sync = since is None
    query = select(Permit)

    if since:
        query = query.where(
            or_(Permit.updated_at > since, Permit.deleted_at > since)
        )
    else:
        query = query.where(Permit.deleted_at.is_(None))

    permits = (await db.execute(query.order_by(Permit.updated_at))).scalars().all()

    return SyncPermitsResponse(
        permits=permits,
        server_timestamp=datetime.now(timezone.utc),
        full_sync=full_sync,
    )


@router.get("/lots", response_model=SyncLotsResponse)
async def sync_lots(
    since: datetime | None = Query(None),
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    full_sync = since is None
    query = select(ParkingLot)

    if since:
        query = query.where(
            or_(ParkingLot.updated_at > since, ParkingLot.deleted_at > since)
        )
    else:
        query = query.where(ParkingLot.deleted_at.is_(None))

    lots = (await db.execute(query.order_by(ParkingLot.updated_at))).scalars().all()

    return SyncLotsResponse(
        lots=lots,
        server_timestamp=datetime.now(timezone.utc),
        full_sync=full_sync,
    )


@router.get("/status", response_model=SyncStatusResponse)
async def sync_status(
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    permit_count = (
        await db.execute(
            select(func.count()).select_from(Permit).where(Permit.deleted_at.is_(None))
        )
    ).scalar() or 0

    lot_count = (
        await db.execute(
            select(func.count())
            .select_from(ParkingLot)
            .where(ParkingLot.deleted_at.is_(None))
        )
    ).scalar() or 0

    device_count = (
        await db.execute(select(func.count()).select_from(Device))
    ).scalar() or 0

    return SyncStatusResponse(
        server_time=datetime.now(timezone.utc),
        permit_count=permit_count,
        lot_count=lot_count,
        device_count=device_count,
    )


@router.post("/register-push", status_code=204)
async def register_push_token(
    body: PushTokenRegister,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    device.push_token = body.token
    await db.flush()


@router.post("/tickets", status_code=202)
async def upload_ticket(
    ticket: TicketUpload,
    device: Device = Depends(get_device),
    db: AsyncSession = Depends(get_db),
):
    from ..models.ticket import Ticket as TicketModel

    new_ticket = TicketModel(
        plate=ticket.plate.upper(),
        lot=ticket.lot,
        violation_type=ticket.violation_type or "unknown",
        officer_id=device.name,
        issued_at=ticket.timestamp,
    )
    db.add(new_ticket)
    await db.flush()

    return {"status": "accepted", "ticket_id": str(new_ticket.id)}
