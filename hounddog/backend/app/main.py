import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import (
    academic_calendar,
    audit,
    auth,
    devices,
    enforcement_settings,
    lots,
    payments,
    permit_types,
    permits,
    sync,
    tickets,
    violation_types,
)
from .middleware.audit import AuditMiddleware
from .websocket import manager

logger = logging.getLogger("quarry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text
    from .database import engine, Base
    from .models import (  # noqa: F401
        Permit, ParkingLot, Device, Ticket, Payment,
        ViolationType, PermitType, AcademicSeason, LotZone, EnforcementSettings,
        AuditLog,
    )
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

    # Schema migrations for columns added after initial table creation
    async with engine.begin() as conn:
        migrations = [
            "ALTER TABLE devices ADD COLUMN IF NOT EXISTS push_token VARCHAR(256)",
            # Ticket enhancements
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_category VARCHAR(32) DEFAULT 'parking'",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS offense_number INTEGER DEFAULT 1",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_lat DOUBLE PRECISION",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_lng DOUBLE PRECISION",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_text VARCHAR(512)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS vehicle_description VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_notes TEXT",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS driver_name VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS driver_license VARCHAR(64)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS violation_type_id UUID",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_name VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_email VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_phone VARCHAR(32)",
            # Lot enhancements
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS total_spaces INTEGER DEFAULT 0",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS handicap_spaces INTEGER DEFAULT 0",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_code VARCHAR(32) DEFAULT ''",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_label VARCHAR(256) DEFAULT ''",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS access_schedule JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_snow_lot BOOLEAN DEFAULT false",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS notes TEXT",
        ]
        for migration in migrations:
            await conn.execute(text(migration))

    logger.info("Schema migrations applied.")

    # Auto-expire permits on startup
    try:
        from .services.permit_lifecycle import auto_expire_permits
        from .database import async_session
        async with async_session() as session:
            async with session.begin():
                count = await auto_expire_permits(session)
                if count:
                    logger.info(f"Auto-expired {count} permits on startup")
    except Exception as e:
        logger.warning(f"Auto-expire on startup failed: {e}")

    yield


app = FastAPI(
    title="Quarry",
    description="Quarry parking management API",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuditMiddleware)

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(devices.router, prefix="/api/devices", tags=["devices"])
app.include_router(permits.router, prefix="/api/permits", tags=["permits"])
app.include_router(lots.router, prefix="/api/lots", tags=["lots"])
app.include_router(sync.router, prefix="/api/sync", tags=["sync"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(violation_types.router, prefix="/api/violation-types", tags=["violation-types"])
app.include_router(permit_types.router, prefix="/api/permit-types", tags=["permit-types"])
app.include_router(academic_calendar.router, prefix="/api/academic-calendar", tags=["academic-calendar"])
app.include_router(enforcement_settings.router, prefix="/api/settings/enforcement", tags=["settings"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])

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
