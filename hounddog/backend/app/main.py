import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import auth, devices, permits, lots, sync, tickets, payments
from .websocket import manager

logger = logging.getLogger("quarry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from .database import engine, Base
    from .models import Permit, ParkingLot, Device, Ticket, Payment  # noqa: F401
    for attempt in range(1, 11):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database connected and tables created.")
            break
        except Exception as exc:
            logger.warning("DB connect attempt %d/10 failed: %s", attempt, exc)
            if attempt == 10:
                raise
            await asyncio.sleep(3)
    yield


app = FastAPI(
    title="Quarry",
    description="Quarry parking management API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(permits.router, prefix="/api/permits", tags=["permits"])
app.include_router(lots.router, prefix="/api/lots", tags=["lots"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])

import os as _os
_upload_dir = _os.path.join(_os.path.dirname(__file__), "..", "uploads")
_os.makedirs(_upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_upload_dir), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
