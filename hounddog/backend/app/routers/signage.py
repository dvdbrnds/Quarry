"""Digital signage screen management and SSE player endpoint."""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.okta import require_role
from ..database import get_db
from ..models.signage_screen import SignageScreen

logger = logging.getLogger("quarry.signage")

admin_router = APIRouter(dependencies=[Depends(require_role("admin", "staff"))])
public_router = APIRouter()


# --- Schemas ---

class SignageScreenCreate(BaseModel):
    name: str
    location: str = ""
    playlist: list[dict] = []


class SignageScreenUpdate(BaseModel):
    name: str | None = None
    location: str | None = None
    playlist: list[dict] | None = None


class SignageScreenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    location: str
    playlist: list[dict]
    last_seen: datetime | None = None
    is_online: bool
    created_at: datetime
    updated_at: datetime


# --- In-memory state for SSE connections ---

_sse_connections: dict[str, list[asyncio.Queue]] = {}


async def broadcast_to_screens(event: str, data: dict) -> int:
    """Push an SSE event to all connected signage players."""
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    total = 0
    for queues in _sse_connections.values():
        for q in queues:
            try:
                q.put_nowait(payload)
                total += 1
            except asyncio.QueueFull:
                pass
    return total


# --- Admin endpoints ---

@admin_router.get("/screens", response_model=list[SignageScreenRead])
async def list_screens(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SignageScreen).order_by(SignageScreen.name)
    )
    return result.scalars().all()


@admin_router.post("/screens", response_model=SignageScreenRead, status_code=201)
async def create_screen(data: SignageScreenCreate, db: AsyncSession = Depends(get_db)):
    screen = SignageScreen(
        name=data.name,
        location=data.location,
        playlist=data.playlist,
    )
    db.add(screen)
    await db.flush()
    await db.refresh(screen)
    return screen


@admin_router.put("/screens/{screen_id}", response_model=SignageScreenRead)
async def update_screen(
    screen_id: uuid.UUID,
    data: SignageScreenUpdate,
    db: AsyncSession = Depends(get_db),
):
    screen = await db.get(SignageScreen, screen_id)
    if not screen:
        raise HTTPException(404, "Screen not found")

    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(screen, field, value)

    await db.flush()
    await db.refresh(screen)
    return screen


@admin_router.delete("/screens/{screen_id}", status_code=204)
async def delete_screen(
    screen_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    screen = await db.get(SignageScreen, screen_id)
    if not screen:
        raise HTTPException(404, "Screen not found")
    await db.delete(screen)
    await db.flush()


# --- Public endpoints ---

@public_router.get("/player/{screen_id}")
async def player_sse(screen_id: uuid.UUID, request: Request, db: AsyncSession = Depends(get_db)):
    """SSE stream for a signage player. Sends playlist on connect,
    alert_override events when alerts fire, and periodic keepalives."""
    screen = await db.get(SignageScreen, screen_id)
    if not screen:
        raise HTTPException(404, "Screen not found")

    screen.last_seen = datetime.now(timezone.utc)
    await db.flush()

    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    sid = str(screen_id)
    _sse_connections.setdefault(sid, []).append(queue)

    async def event_stream():
        try:
            playlist_data = json.dumps({"playlist": screen.playlist})
            yield f"event: playlist\ndata: {playlist_data}\n\n"

            from ..services.channels.banner_channel import get_active_banner
            active = get_active_banner()
            if active:
                yield f"event: alert_override\ndata: {json.dumps(active)}\n\n"

            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            _sse_connections.get(sid, []).remove(queue)
            if not _sse_connections.get(sid):
                _sse_connections.pop(sid, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@public_router.post("/heartbeat/{screen_id}")
async def player_heartbeat(screen_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    screen = await db.get(SignageScreen, screen_id)
    if not screen:
        raise HTTPException(404, "Screen not found")
    screen.last_seen = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok"}
