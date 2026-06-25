import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
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
    messaging,
    notification_preferences,
    payments,
    permit_types,
    permits,
    student_permits,
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
        Permit, PermitApplication, ParkingLot, Device, Ticket, Payment,
        ViolationType, PermitType, AcademicSeason, LotZone, EnforcementSettings,
        AuditLog, LotClosure, MessageTemplate, NotificationPreference,
    )
    # Fail fast if secret_key was not overridden from the default
    if not settings.secret_key:
        raise RuntimeError(
            "QUARRY_SECRET_KEY is not set. "
            "Set it to a strong random value before starting the server."
        )

    for attempt in range(1, 11):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database connected and tables created.")

            from .middleware.audit import verify_audit_table
            await verify_audit_table()

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
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_name VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_email VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS owner_name VARCHAR(256)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS permit_number VARCHAR(64)",
            # Appeal / dispute fields
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_note TEXT",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_decision VARCHAR(32)",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_decided_by VARCHAR(128)",
            # Lot enhancements
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS total_spaces INTEGER DEFAULT 0",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS handicap_spaces INTEGER DEFAULT 0",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_code VARCHAR(32) DEFAULT ''",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_label VARCHAR(256) DEFAULT ''",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS access_schedule JSONB DEFAULT '[]'::jsonb",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_snow_lot BOOLEAN DEFAULT false",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS notes TEXT",
            # Permit email
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS email VARCHAR(256)",
            # Lot closure tracking
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_closed BOOLEAN DEFAULT false",
            # SheepDog occupancy sensing
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS has_sheepdog BOOLEAN DEFAULT false",
            """CREATE TABLE IF NOT EXISTS parking_spots (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                lot_id UUID NOT NULL REFERENCES parking_lots(id) ON DELETE CASCADE,
                number INTEGER NOT NULL,
                label VARCHAR(256),
                sensor_id VARCHAR(16),
                latitude DOUBLE PRECISION,
                longitude DOUBLE PRECISION,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            # Messaging / SMS fields
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS phone VARCHAR(32)",
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS sms_opt_in BOOLEAN DEFAULT false",
            # Permit application lottery fields
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS requires_lottery BOOLEAN DEFAULT false",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS application_opens_at TIMESTAMPTZ",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS application_closes_at TIMESTAMPTZ",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS offer_window_days INTEGER DEFAULT 5",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS lottery_run_at TIMESTAMPTZ",
        ]
        for migration in migrations:
            await conn.execute(text(migration))

    logger.info("Schema migrations applied.")

    # Seed default violation types and permit types if none exist
    try:
        from .database import async_session
        from .models import ViolationType, PermitType
        from sqlalchemy import select, func
        from decimal import Decimal
        async with async_session() as session:
            vt_count = await session.scalar(select(func.count()).select_from(ViolationType))
            if vt_count == 0:
                default_violations = [
                    # Parking violations
                    {"code": "first_year_unauthorized", "label": "First-Year Student / Unauthorized Vehicle", "category": "parking", "fine_first": 75, "fine_second": 150, "fine_third_plus": 225, "sort_order": 1},
                    {"code": "disability_area", "label": "Disability Area Violation", "category": "parking", "fine_first": 200, "sort_order": 2},
                    {"code": "unauthorized_premium", "label": "Unauthorized in Premium/Guaranteed", "category": "parking", "fine_first": 75, "fine_second": 150, "fine_third_plus": 225, "sort_order": 3},
                    {"code": "fire_hydrant", "label": "Obstructing Fire Hydrant", "category": "parking", "fine_first": 200, "sort_order": 4},
                    {"code": "reserved_premium_visitor", "label": "Reserved Premium Visitor Area", "category": "parking", "fine_first": 75, "fine_second": 150, "fine_third_plus": 225, "sort_order": 5},
                    {"code": "reserved_visitor", "label": "Reserved Visitor Space", "category": "parking", "fine_first": 35, "sort_order": 6},
                    {"code": "prohibited_parking", "label": "Prohibited Parking", "category": "parking", "fine_first": 35, "sort_order": 7},
                    {"code": "prohibited_time", "label": "Parking During Prohibited Time", "category": "parking", "fine_first": 35, "sort_order": 8},
                    {"code": "unauthorized_permit", "label": "Unauthorized Permit Parking", "category": "parking", "fine_first": 35, "sort_order": 9},
                    {"code": "posted_signs", "label": "Failure to Obey Posted Signs", "category": "parking", "fine_first": 35, "sort_order": 10},
                    {"code": "no_permit_displayed", "label": "Registered Vehicle, No Permit Displayed", "category": "parking", "fine_first": 35, "sort_order": 11},
                    # Moving violations
                    {"code": "speeding", "label": "Speeding", "category": "moving", "fine_first": 50, "fine_second": 100, "fine_third_plus": 200, "sort_order": 100},
                    {"code": "stop_sign", "label": "Failure to Stop at Stop Sign", "category": "moving", "fine_first": 50, "fine_second": 100, "fine_third_plus": 200, "sort_order": 101},
                    {"code": "reckless_driving", "label": "Reckless Driving", "category": "moving", "fine_first": 150, "fine_second": 300, "fine_third_plus": 500, "sort_order": 102},
                    {"code": "wrong_way", "label": "Driving Wrong Way / One-Way Violation", "category": "moving", "fine_first": 75, "fine_second": 150, "fine_third_plus": 250, "sort_order": 103},
                    {"code": "pedestrian_failure_yield", "label": "Failure to Yield to Pedestrian", "category": "moving", "fine_first": 75, "fine_second": 150, "fine_third_plus": 250, "sort_order": 104},
                    {"code": "suspended_license", "label": "Driving with Suspended/Revoked License", "category": "moving", "fine_first": 200, "fine_second": 400, "sort_order": 105},
                    {"code": "dui", "label": "Driving Under the Influence", "category": "moving", "fine_first": 500, "sort_order": 106},
                    {"code": "hit_and_run", "label": "Hit and Run / Leaving Scene of Accident", "category": "moving", "fine_first": 300, "sort_order": 107},
                    {"code": "no_headlights", "label": "Operating Without Headlights", "category": "moving", "fine_first": 35, "sort_order": 108},
                    {"code": "cell_phone", "label": "Cell Phone Use While Driving", "category": "moving", "fine_first": 50, "fine_second": 100, "sort_order": 109},
                ]
                for row in default_violations:
                    session.add(ViolationType(
                        code=row["code"], label=row["label"], category=row["category"],
                        fine_first=Decimal(str(row["fine_first"])),
                        fine_second=Decimal(str(row["fine_second"])) if row.get("fine_second") else None,
                        fine_third_plus=Decimal(str(row["fine_third_plus"])) if row.get("fine_third_plus") else None,
                        sort_order=row["sort_order"],
                    ))
                await session.commit()
                logger.info("Seeded 11 default violation types")

            pt_count = await session.scalar(select(func.count()).select_from(PermitType))
            if pt_count == 0:
                default_permits = [
                    {"code": "commuter_undergrad", "label": "Regular Commuter (Undergrad)", "eligible": "Commuter undergrads", "price": 100, "max_capacity": 249, "valid_days": 365, "lot_assignments": ["X", "A", "F", "H", "M", "N", "O", "R", "S"], "is_purchasable_online": True, "sort_order": 1},
                    {"code": "commuter_grad", "label": "Regular Commuter (Grad)", "eligible": "Grad/seminary/continuing ed", "price": 100, "max_capacity": 112, "valid_days": 365, "lot_assignments": ["W", "A", "F", "H", "M", "N", "O", "R", "S"], "is_purchasable_online": True, "sort_order": 2},
                    {"code": "premium_commuter", "label": "Extended Premium Commuter", "eligible": "Commuter students", "price": 150, "max_capacity": 35, "valid_days": 365, "lot_assignments": ["W. Laurel St"], "is_purchasable_online": True, "sort_order": 3},
                    {"code": "north_premium_resident", "label": "North Premium Resident", "eligible": "Resident students (seniority-based)", "price": 400, "max_capacity": 57, "valid_days": 365, "lot_assignments": ["I", "W. Laurel St"], "is_purchasable_online": False, "sort_order": 4},
                    {"code": "north_guaranteed_resident", "label": "North Guaranteed Resident", "eligible": "Resident students (seniority-based)", "price": 250, "max_capacity": 208, "valid_days": 365, "lot_assignments": ["B", "C", "D", "G", "P", "T"], "is_purchasable_online": False, "sort_order": 5},
                    {"code": "steel_field_resident", "label": "Steel Field Resident", "eligible": "Resident students", "price": 75, "max_capacity": 42, "valid_days": 365, "lot_assignments": ["Q"], "is_purchasable_online": True, "sort_order": 6},
                    {"code": "south_premium_resident", "label": "South Premium Resident", "eligible": "Resident students (seniority-based)", "price": 400, "max_capacity": 37, "valid_days": 365, "lot_assignments": ["Z"], "is_purchasable_online": False, "sort_order": 7},
                    {"code": "south_guaranteed_resident", "label": "South Guaranteed Resident", "eligible": "Resident students (seniority-based)", "price": 250, "max_capacity": 88, "valid_days": 365, "lot_assignments": ["U", "Lehigh St", "Spring St"], "is_purchasable_online": False, "sort_order": 8},
                    {"code": "south_standalone", "label": "South Standalone", "eligible": "Resident students", "price": 100, "max_capacity": 50, "valid_days": 365, "lot_assignments": ["Lehigh St", "Spring St"], "is_purchasable_online": True, "sort_order": 9},
                    {"code": "faculty_staff", "label": "Faculty/Staff", "eligible": "Employees", "price": 0, "max_capacity": 500, "valid_days": 730, "lot_assignments": ["A", "F", "H", "M", "N", "O", "R", "S", "U", "W"], "is_purchasable_online": False, "sort_order": 10},
                ]
                for row in default_permits:
                    session.add(PermitType(
                        code=row["code"], label=row["label"], eligible=row["eligible"],
                        price=Decimal(str(row["price"])), max_capacity=row["max_capacity"],
                        valid_days=row["valid_days"], lot_assignments=row["lot_assignments"],
                        is_purchasable_online=row["is_purchasable_online"], sort_order=row["sort_order"],
                    ))
                await session.commit()
                logger.info("Seeded 10 default permit types")
    except Exception as e:
        logger.warning(f"Seed defaults on startup failed: {e}")

    # Seed academic calendar if empty
    try:
        from .models import AcademicSeason
        from datetime import date as _date
        async with async_session() as session:
            ac_count = await session.scalar(select(func.count()).select_from(AcademicSeason))
            if ac_count == 0:
                default_seasons = [
                    # 2025-2026
                    {"code": "fall_2025", "label": "Fall 2025", "start_date": _date(2025, 8, 25), "end_date": _date(2025, 12, 15), "is_default": True},
                    {"code": "winter_break_2025", "label": "Winter Break 2025-26", "start_date": _date(2025, 12, 16), "end_date": _date(2026, 1, 4), "is_default": False},
                    {"code": "winter_session_2026", "label": "Winter Session 2026", "start_date": _date(2026, 1, 5), "end_date": _date(2026, 1, 17), "is_default": False},
                    {"code": "spring_2026", "label": "Spring 2026", "start_date": _date(2026, 1, 19), "end_date": _date(2026, 5, 9), "is_default": False},
                    {"code": "spring_break_2026", "label": "Spring Break 2026", "start_date": _date(2026, 3, 8), "end_date": _date(2026, 3, 15), "is_default": False},
                    {"code": "may_term_2026", "label": "May Term 2026", "start_date": _date(2026, 5, 11), "end_date": _date(2026, 5, 30), "is_default": False},
                    {"code": "summer_i_2026", "label": "Summer Session I 2026", "start_date": _date(2026, 6, 1), "end_date": _date(2026, 7, 11), "is_default": False},
                    {"code": "summer_ii_2026", "label": "Summer Session II 2026", "start_date": _date(2026, 7, 13), "end_date": _date(2026, 8, 22), "is_default": False},
                    # 2026-2027
                    {"code": "fall_2026", "label": "Fall 2026", "start_date": _date(2026, 8, 31), "end_date": _date(2026, 12, 21), "is_default": False},
                    {"code": "winter_break_2026", "label": "Winter Break 2026-27", "start_date": _date(2026, 12, 22), "end_date": _date(2027, 1, 3), "is_default": False},
                    {"code": "winter_session_2027", "label": "Winter Session 2027", "start_date": _date(2027, 1, 4), "end_date": _date(2027, 1, 16), "is_default": False},
                    {"code": "spring_2027", "label": "Spring 2027", "start_date": _date(2027, 1, 18), "end_date": _date(2027, 5, 8), "is_default": False},
                    {"code": "spring_break_2027", "label": "Spring Break 2027", "start_date": _date(2027, 3, 7), "end_date": _date(2027, 3, 14), "is_default": False},
                    {"code": "may_term_2027", "label": "May Term 2027", "start_date": _date(2027, 5, 10), "end_date": _date(2027, 5, 29), "is_default": False},
                    {"code": "summer_i_2027", "label": "Summer Session I 2027", "start_date": _date(2027, 6, 1), "end_date": _date(2027, 7, 10), "is_default": False},
                    {"code": "summer_ii_2027", "label": "Summer Session II 2027", "start_date": _date(2027, 7, 12), "end_date": _date(2027, 8, 21), "is_default": False},
                ]
                for row in default_seasons:
                    session.add(AcademicSeason(**row))
                await session.commit()
                logger.info(f"Seeded {len(default_seasons)} academic seasons")
    except Exception as e:
        logger.warning(f"Seed academic calendar on startup failed: {e}")

    # Seed default message templates if none exist
    try:
        from .models import MessageTemplate
        async with async_session() as session:
            mt_count = await session.scalar(select(func.count()).select_from(MessageTemplate))
            if mt_count == 0:
                default_templates = [
                    {
                        "reason_code": "snow",
                        "reason_label": "Snow Emergency",
                        "is_emergency": True,
                        "email_subject": "URGENT: {lot_name} Closed — Snow Emergency",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #c0392b;">Snow Emergency — Lot Closure</h2><p><strong>{lot_name}</strong> at {school} is closed for snow removal effective <strong>{closes_at}</strong>.</p><p><strong>Move your vehicle immediately.</strong> Vehicles remaining may be towed.</p><p>Expected reopening: {reopens_at}</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for snow removal effective {closes_at}. Move your vehicle immediately.",
                    },
                    {
                        "reason_code": "repaving",
                        "reason_label": "Repaving",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Repaving",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Repaving</h2><p><strong>{lot_name}</strong> at {school} will be closed for repaving effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for repaving {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "tree_cutting",
                        "reason_label": "Tree Maintenance",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Tree Maintenance",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Tree Maintenance</h2><p><strong>{lot_name}</strong> at {school} will be closed for tree work effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for tree work {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "event",
                        "reason_label": "Campus Event",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Campus Event",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Campus Event</h2><p><strong>{lot_name}</strong> at {school} will be closed for a campus event effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for campus event {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "emergency",
                        "reason_label": "Emergency",
                        "is_emergency": True,
                        "email_subject": "URGENT: {lot_name} Closed — Emergency",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #c0392b;">Emergency Lot Closure</h2><p><strong>{lot_name}</strong> at {school} has been closed immediately.</p><p><strong>Reason:</strong> {reason}</p><p>Please avoid the area. Vehicles remaining may be towed.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed immediately. {reason}. Avoid the area.",
                    },
                    {
                        "reason_code": "general",
                        "reason_label": "General Closure",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name}",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure Notice</h2><p><strong>{lot_name}</strong> at {school} has been closed effective <strong>{closes_at}</strong>.</p><p><strong>Reason:</strong> {reason}</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} Parking Services — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed {closes_at}. Reason: {reason}.",
                    },
                ]
                for tmpl in default_templates:
                    session.add(MessageTemplate(**tmpl))
                await session.commit()
                logger.info("Seeded %d default message templates", len(default_templates))
    except Exception as e:
        logger.warning(f"Seed message templates on startup failed: {e}")

    # Auto-expire permits on startup
    try:
        from .services.permit_lifecycle import auto_expire_permits
        from .database import async_session as _session_factory
        async with _session_factory() as session:
            async with session.begin():
                count = await auto_expire_permits(session)
                if count:
                    logger.info(f"Auto-expired {count} permits on startup")
    except Exception as e:
        logger.warning(f"Auto-expire on startup failed: {e}")

    from .services.closure_scheduler import start_scheduler, stop_scheduler
    start_scheduler()

    yield

    stop_scheduler()


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
app.include_router(sync.diagnostic_router, prefix="/api/sync", tags=["sync-diagnostic"])
app.include_router(tickets.router, prefix="/api/tickets", tags=["tickets"])
app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
app.include_router(violation_types.router, prefix="/api/violation-types", tags=["violation-types"])
app.include_router(permit_types.router, prefix="/api/permit-types", tags=["permit-types"])
app.include_router(academic_calendar.router, prefix="/api/academic-calendar", tags=["academic-calendar"])
app.include_router(enforcement_settings.router, prefix="/api/settings/enforcement", tags=["settings"])
app.include_router(audit.diagnostic_router, prefix="/api/audit", tags=["audit"])
app.include_router(audit.router, prefix="/api/audit", tags=["audit"])
app.include_router(messaging.router, prefix="/api/messaging", tags=["messaging"])
app.include_router(notification_preferences.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(student_permits.router, prefix="/api/student/permits", tags=["student-permits"])

import os as _os
_upload_dir = _os.path.join(_os.path.dirname(__file__), "..", "uploads")
_os.makedirs(_upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_upload_dir), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    from .auth.okta import verify_token_string
    if settings.okta_domain:
        if not token:
            await websocket.close(code=4001, reason="Missing token")
            return
        try:
            await verify_token_string(token)
        except ValueError:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
