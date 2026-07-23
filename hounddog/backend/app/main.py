import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .routers import (
    academic_calendar,
    alerts,
    audit,
    auth,
    backup,
    branding,
    devices,
    enforcement_settings,
    lots,
    messaging,
    notification_preferences,
    parking_map,
    payments,
    permit_types,
    permits,
    renewals,
    resident_plates,
    signage,
    staff_permits,
    student_permits,
    sync,
    tickets,
    violation_types,
    visitor_permits,
)
from .middleware.audit import AuditMiddleware

logger = logging.getLogger("quarry")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from sqlalchemy import text
    from .database import engine, Base
    from .models import (  # noqa: F401
        Permit, PermitApplication, ParkingLot, Device, Ticket, Payment,
        ViolationType, PermitType, AcademicSeason, LotZone, EnforcementSettings,
        AuditLog, LotClosure, MessageTemplate, NotificationPreference,
        AlertSubscriber, AlertLog, AlertTemplate, AlertResponse, AlertScenario,
        SubscriberGroup, subscriber_group_members, RenewalToken,
        VisitorApprovalToken,
    )
    # Fail fast if secret_key was not overridden from the default
    if not settings.secret_key:
        raise RuntimeError(
            "SECRET_KEY is not set. "
            "Set it to a strong random value before starting the server."
        )
    if len(settings.secret_key) < 32:
        raise RuntimeError(
            "SECRET_KEY is too short. Use at least 32 characters of random hex."
        )

    if not settings.okta_domain:
        raise RuntimeError(
            "OKTA_DOMAIN is not set. "
            "Set it to your Okta domain (e.g., moravian.okta.com) before starting the server."
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
        await conn.execute(text("SELECT pg_advisory_lock(42)"))
        try:
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
            # Mail notice tracking
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS mailed_at TIMESTAMPTZ",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS mailed_address TEXT",
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
            # Backfill null phone to empty string
            "UPDATE permits SET phone = '' WHERE phone IS NULL",
            # QPS permit numbering
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS permit_number VARCHAR(32)",
            "CREATE SEQUENCE IF NOT EXISTS qps_permit_number_seq START WITH 1",
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
            # SheepDog spot type
            "ALTER TABLE parking_spots ADD COLUMN IF NOT EXISTS spot_type VARCHAR(32) DEFAULT 'standard'",
            # Alert log multi-channel fields
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS status VARCHAR(32) DEFAULT 'active'",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS cleared_at TIMESTAMPTZ",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS cleared_by VARCHAR(256)",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS channel_results JSONB",
            # Digital signage screens
            """CREATE TABLE IF NOT EXISTS signage_screens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(256) NOT NULL,
                location VARCHAR(256) DEFAULT '',
                playlist JSONB DEFAULT '[]'::jsonb,
                last_seen TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            # Standalone permit purchases: ticket_id must be nullable
            "ALTER TABLE payments ALTER COLUMN ticket_id DROP NOT NULL",
            # Payment metadata columns
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_type VARCHAR(48)",
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payer_name VARCHAR(256)",
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payer_email VARCHAR(256)",
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS description VARCHAR(512)",
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS plate VARCHAR(20)",
            "ALTER TABLE payments ADD COLUMN IF NOT EXISTS bursar_reference VARCHAR(128)",
            # Lottery strategy on permit types
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS lottery_strategy VARCHAR(64) DEFAULT 'seniority_timestamp'",
            # Lot preferences on permit applications
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS lot_preferences TEXT[] DEFAULT '{}'",
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS assigned_lot VARCHAR(128)",
            # Lottery test entries and Okta metadata
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS is_test_entry BOOLEAN DEFAULT false",
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS okta_metadata JSONB",
            # Plate state on permit applications
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS plate_state VARCHAR(2) DEFAULT ''",
            # Fee-exempt lottery applications (RAs, grad nursing, etc.)
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS fee_exempt BOOLEAN DEFAULT false",
            # First-year restriction on permit types
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS min_class_year INTEGER",
            # Renewal tokens for faculty/staff magic-link renewal
            """CREATE TABLE IF NOT EXISTS renewal_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                token VARCHAR(128) NOT NULL UNIQUE,
                permit_id UUID NOT NULL REFERENCES permits(id) ON DELETE CASCADE,
                email VARCHAR(256) NOT NULL,
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ,
                response VARCHAR(32),
                new_plate VARCHAR(32),
                created_at TIMESTAMPTZ DEFAULT now()
            )""",
            "ALTER TABLE renewal_tokens ADD COLUMN IF NOT EXISTS response VARCHAR(32)",
            # Campus grouping for parking lots
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS campus VARCHAR(64)",
            # Lot vs street type
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS lot_type VARCHAR(32) DEFAULT 'lot'",
            # External lot fields (third-party parking)
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS external_url VARCHAR(512)",
            "ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS external_provider VARCHAR(256)",
            # Sequential ticket numbers
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_number VARCHAR(32)",
            "CREATE SEQUENCE IF NOT EXISTS quarry_ticket_number_seq START WITH 1",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ticket_number ON tickets (ticket_number) WHERE ticket_number IS NOT NULL",
            # Escalation tracking
            """CREATE TABLE IF NOT EXISTS escalation_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id VARCHAR(50) NOT NULL,
                student_name VARCHAR(255),
                student_email VARCHAR(255),
                plate VARCHAR(50),
                escalation_type VARCHAR(50) NOT NULL,
                ticket_count INTEGER NOT NULL,
                ticket_ids TEXT,
                status VARCHAR(50) DEFAULT 'sent',
                details TEXT,
                created_at TIMESTAMP DEFAULT NOW(),
                resolved_at TIMESTAMP,
                resolved_by VARCHAR(255)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_escalation_student ON escalation_log(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_escalation_type ON escalation_log(escalation_type)",
            # Extended Premium Commuter gets all street parking lots
            """UPDATE permit_types
               SET lot_assignments = (
                   SELECT ARRAY(SELECT DISTINCT unnest FROM unnest(
                       permit_types.lot_assignments || street_lots.names
                   ))
               )
               FROM (
                   SELECT COALESCE(ARRAY_AGG(name), '{}') AS names
                   FROM parking_lots WHERE lot_type = 'street'
               ) AS street_lots
               WHERE code = 'premium_commuter'""",
            # Lottery audit log
            """CREATE TABLE IF NOT EXISTS lottery_audit_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                permit_type_id UUID NOT NULL,
                strategy VARCHAR(50) NOT NULL,
                seed_hash VARCHAR(128),
                total_applicants INTEGER,
                eligible_applicants INTEGER,
                spots_available INTEGER,
                selected_count INTEGER,
                waitlisted_count INTEGER,
                filtered_test_entries INTEGER DEFAULT 0,
                filtered_unpaid_citations INTEGER DEFAULT 0,
                run_at TIMESTAMP NOT NULL,
                run_by VARCHAR(255),
                warnings TEXT,
                created_at TIMESTAMP DEFAULT NOW()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_lottery_audit_pt ON lottery_audit_log(permit_type_id)",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS lottery_seed VARCHAR(128)",
            "ALTER TABLE permit_applications ADD COLUMN IF NOT EXISTS admin_notes TEXT",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS allow_freshmen BOOLEAN DEFAULT false",
            """CREATE TABLE IF NOT EXISTS resident_plates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                plate VARCHAR(20) NOT NULL,
                plate_state VARCHAR(2) DEFAULT '',
                street_id UUID REFERENCES parking_lots(id) ON DELETE SET NULL,
                notes TEXT,
                added_by VARCHAR(256) DEFAULT '',
                created_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_resident_plates_plate ON resident_plates(plate)",
            # Omnilert replacement: alert templates
            """CREATE TABLE IF NOT EXISTS alert_templates (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(256) NOT NULL,
                category VARCHAR(64) NOT NULL,
                subject VARCHAR(512) NOT NULL,
                body_text TEXT DEFAULT '',
                body_sms VARCHAR(320) DEFAULT '',
                created_by VARCHAR(256) NOT NULL,
                is_default BOOLEAN DEFAULT false,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            # Omnilert replacement: two-way SMS responses
            """CREATE TABLE IF NOT EXISTS alert_responses (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                alert_id UUID NOT NULL REFERENCES alert_log(id) ON DELETE CASCADE,
                subscriber_id UUID REFERENCES alert_subscribers(id) ON DELETE SET NULL,
                phone VARCHAR(32),
                channel VARCHAR(32) DEFAULT 'sms',
                response_text VARCHAR(320) DEFAULT '',
                received_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_alert_responses_alert ON alert_responses(alert_id)",
            "CREATE INDEX IF NOT EXISTS idx_alert_responses_subscriber ON alert_responses(subscriber_id)",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS response_options JSONB",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS is_checkin BOOLEAN DEFAULT false",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS target_group_ids JSONB",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMPTZ",
            "ALTER TABLE alert_log ADD COLUMN IF NOT EXISTS recurrence_rule VARCHAR(256)",
            # Omnilert replacement: subscriber groups
            """CREATE TABLE IF NOT EXISTS subscriber_groups (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(256) NOT NULL,
                description TEXT DEFAULT '',
                group_type VARCHAR(64) DEFAULT 'custom',
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            """CREATE TABLE IF NOT EXISTS subscriber_group_members (
                subscriber_id UUID NOT NULL REFERENCES alert_subscribers(id) ON DELETE CASCADE,
                group_id UUID NOT NULL REFERENCES subscriber_groups(id) ON DELETE CASCADE,
                PRIMARY KEY (subscriber_id, group_id)
            )""",
            "CREATE INDEX IF NOT EXISTS idx_sgm_subscriber ON subscriber_group_members(subscriber_id)",
            "CREATE INDEX IF NOT EXISTS idx_sgm_group ON subscriber_group_members(group_id)",
            # Omnilert replacement: alert scenarios
            """CREATE TABLE IF NOT EXISTS alert_scenarios (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                name VARCHAR(256) NOT NULL,
                description TEXT DEFAULT '',
                steps JSONB NOT NULL DEFAULT '[]'::jsonb,
                created_by VARCHAR(256),
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            """CREATE TABLE IF NOT EXISTS branding_settings (
                id INTEGER PRIMARY KEY DEFAULT 1,
                brand_name VARCHAR(256) DEFAULT 'Quarry',
                primary_color VARCHAR(32) DEFAULT '#1a2744',
                accent_color VARCHAR(32) DEFAULT '#c9a84c',
                logo_data BYTEA,
                logo_mime VARCHAR(64),
                favicon_data BYTEA,
                favicon_mime VARCHAR(64),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            # Visitor portal: approval tokens for long-term vendor permits
            """CREATE TABLE IF NOT EXISTS visitor_approval_tokens (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                token VARCHAR(128) NOT NULL UNIQUE,
                permit_id UUID NOT NULL REFERENCES permits(id) ON DELETE CASCADE,
                sponsor_email VARCHAR(256) NOT NULL,
                sponsor_name VARCHAR(256) DEFAULT '',
                expires_at TIMESTAMPTZ NOT NULL,
                used_at TIMESTAMPTZ,
                decision VARCHAR(32),
                created_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_visitor_approval_token ON visitor_approval_tokens(token)",
            # Rename South Standalone → South Third Party
            "UPDATE permit_types SET label = 'South Third Party' WHERE code = 'south_standalone' AND label = 'South Standalone'",
            # Eligible groups for role-based permit visibility
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS eligible_groups TEXT[] DEFAULT '{}'",
            ]
            for migration in migrations:
                await conn.execute(text(migration))
        finally:
            await conn.execute(text("SELECT pg_advisory_unlock(42)"))

    logger.info("Schema migrations applied.")

    from .services.alert_dispatcher import init_channels
    init_channels()

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
                logger.info("Seeded default violation types")

            # One-shot backfill: moving violations added after initial parking-only seed
            moving_defaults = [
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
            existing_codes = {
                row[0] for row in (await session.execute(
                    select(ViolationType.code).where(ViolationType.code.in_([m["code"] for m in moving_defaults]))
                )).all()
            }
            backfilled = 0
            for row in moving_defaults:
                if row["code"] not in existing_codes:
                    session.add(ViolationType(
                        code=row["code"], label=row["label"], category=row["category"],
                        fine_first=Decimal(str(row["fine_first"])),
                        fine_second=Decimal(str(row["fine_second"])) if row.get("fine_second") else None,
                        fine_third_plus=Decimal(str(row["fine_third_plus"])) if row.get("fine_third_plus") else None,
                        sort_order=row["sort_order"],
                    ))
                    backfilled += 1
            if backfilled:
                await session.commit()
                logger.info("Backfilled %d moving violation types", backfilled)

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
                    {"code": "south_standalone", "label": "South Third Party", "eligible": "Resident students", "price": 100, "max_capacity": 50, "valid_days": 365, "lot_assignments": ["Lehigh St", "Spring St"], "is_purchasable_online": True, "sort_order": 9},
                    {"code": "faculty_staff", "label": "Faculty/Staff", "eligible": "Employees", "price": 0, "max_capacity": 500, "valid_days": 730, "lot_assignments": ["A", "F", "H", "M", "N", "O", "R", "S", "U", "W"], "is_purchasable_online": False, "sort_order": 10, "eligible_groups": ["Quarry-Staff", "Quarry-Admin"]},
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

    # Deduplicate academic seasons (keep oldest row per code)
    try:
        async with async_session() as session:
            await session.execute(text("""
                DELETE FROM academic_seasons
                WHERE id NOT IN (
                    SELECT DISTINCT ON (code) id
                    FROM academic_seasons
                    ORDER BY code, created_at ASC
                )
            """))
            await session.commit()
    except Exception as e:
        logger.warning(f"Dedup academic seasons failed: {e}")

    # Add unique constraint on academic_seasons.code if missing
    try:
        async with async_session() as session:
            await session.execute(text("""
                DO $$ BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_academic_seasons_code'
                    ) THEN
                        ALTER TABLE academic_seasons ADD CONSTRAINT uq_academic_seasons_code UNIQUE (code);
                    END IF;
                END $$;
            """))
            await session.commit()
    except Exception as e:
        logger.warning(f"Add academic_seasons unique constraint failed: {e}")

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

    # Seed default alert templates if none exist
    try:
        from .models import AlertTemplate
        async with async_session() as session:
            at_count = await session.scalar(select(func.count()).select_from(AlertTemplate))
            if at_count == 0:
                default_alert_templates = [
                    {"name": "Active Shooter", "category": "emergency", "subject": "ACTIVE SHOOTER — Seek shelter immediately", "body_text": "ACTIVE SHOOTER reported on campus. Run, Hide, Fight. Shelter in place immediately. Lock and barricade doors. Silence phones. Do not exit until all-clear is given by campus police.", "body_sms": "ACTIVE SHOOTER on campus. Run, Hide, Fight. Shelter in place NOW.", "is_default": True},
                    {"name": "Tornado Warning", "category": "emergency", "subject": "TORNADO WARNING — Take shelter now", "body_text": "A TORNADO WARNING has been issued for the campus area. Take shelter immediately in the lowest interior room away from windows. Stay sheltered until the all-clear is given.", "body_sms": "TORNADO WARNING for campus. Take shelter in lowest interior room NOW.", "is_default": False},
                    {"name": "Campus Lockdown", "category": "emergency", "subject": "CAMPUS LOCKDOWN — Shelter in place", "body_text": "Campus is under LOCKDOWN. Shelter in place immediately. Lock and barricade doors. Do not exit buildings until the all-clear is given by campus police.", "body_sms": "LOCKDOWN: Campus locked down. Shelter in place. Do not exit buildings.", "is_default": False},
                    {"name": "Weather Closure", "category": "campus_closing", "subject": "Campus Closed — Severe Weather", "body_text": "Due to severe weather conditions, campus is closed effective immediately. All classes and campus activities are cancelled. Stay home and monitor for updates.", "body_sms": "Campus closed due to severe weather. All classes cancelled. Stay home.", "is_default": True},
                    {"name": "Power Outage", "category": "general", "subject": "Power Outage Advisory", "body_text": "A power outage has been reported affecting campus buildings. Facilities is working to restore power. Updates will follow as more information becomes available.", "body_sms": "Power outage reported on campus. Updates to follow.", "is_default": False},
                    {"name": "IT Outage", "category": "general", "subject": "IT Systems Outage", "body_text": "Campus IT systems are currently experiencing an outage. This may affect email, internet, and other campus services. IT is working to restore service. Updates will follow.", "body_sms": "IT systems are currently down. Updates to follow.", "is_default": True},
                    {"name": "All-Clear", "category": "emergency", "subject": "ALL CLEAR — Resume normal activity", "body_text": "The emergency situation has been resolved. The ALL CLEAR has been given. You may resume normal activities. Thank you for your cooperation.", "body_sms": "ALL CLEAR: Emergency ended. Resume normal activity.", "is_default": False},
                ]
                for tmpl in default_alert_templates:
                    session.add(AlertTemplate(**tmpl, created_by="system"))
                await session.commit()
                logger.info("Seeded %d default alert templates", len(default_alert_templates))
    except Exception as e:
        logger.warning(f"Seed alert templates on startup failed: {e}")

    # Seed default subscriber groups if none exist
    try:
        from .models import SubscriberGroup
        async with async_session() as session:
            sg_count = await session.scalar(select(func.count()).select_from(SubscriberGroup))
            if sg_count == 0:
                default_groups = [
                    {"name": "Monocacy Hall", "group_type": "building"},
                    {"name": "Comenius Hall", "group_type": "building"},
                    {"name": "HUB", "group_type": "building"},
                    {"name": "Zinzendorf Hall", "group_type": "building"},
                    {"name": "Colonial Hall", "group_type": "building"},
                    {"name": "PPHAC", "group_type": "building"},
                    {"name": "Sally", "group_type": "building"},
                    {"name": "Steel Field", "group_type": "building"},
                    {"name": "Breidegam Athletics", "group_type": "building"},
                    {"name": "Main Street Offices", "group_type": "building"},
                    {"name": "1742", "group_type": "building"},
                    {"name": "Faculty", "group_type": "role"},
                    {"name": "Staff", "group_type": "role"},
                    {"name": "Students", "group_type": "role"},
                ]
                for grp in default_groups:
                    session.add(SubscriberGroup(**grp))
                await session.commit()
                logger.info("Seeded %d default subscriber groups", len(default_groups))
    except Exception as e:
        logger.warning(f"Seed subscriber groups on startup failed: {e}")

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

    from .services.weather_monitor import start_weather_monitor, stop_weather_monitor
    start_weather_monitor()

    yield

    stop_weather_monitor()
    stop_scheduler()


app = FastAPI(
    title="Quarry",
    description="Quarry parking management API",
    version="0.2.0",
    lifespan=lifespan,
)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest

class MethodOverrideMiddleware(BaseHTTPMiddleware):
    """Translate POST with X-HTTP-Method-Override: DELETE into a real DELETE.

    This works around WAFs/proxies that block the HTTP DELETE method.
    """
    async def dispatch(self, request: StarletteRequest, call_next):
        if request.method == "POST":
            override = request.headers.get("x-http-method-override", "").upper()
            if override == "DELETE":
                request.scope["method"] = "DELETE"
        return await call_next(request)

app.add_middleware(MethodOverrideMiddleware)

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
app.include_router(resident_plates.router, prefix="/api/resident-plates", tags=["resident-plates"])
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
app.include_router(staff_permits.router, prefix="/api/staff/permits", tags=["staff-permits"])
app.include_router(student_permits.router, prefix="/api/student/permits", tags=["student-permits"])
app.include_router(renewals.router, prefix="/api/renewals", tags=["renewals"])
app.include_router(alerts.admin_router, prefix="/api/alerts", tags=["alerts"])
app.include_router(alerts.public_router, prefix="/api/alerts", tags=["alerts-public"])
app.include_router(signage.admin_router, prefix="/api/signage", tags=["signage"])
app.include_router(signage.public_router, prefix="/api/signage", tags=["signage-public"])
app.include_router(backup.router, prefix="/api/backup", tags=["backup"])
app.include_router(branding.admin_router, prefix="/api/branding", tags=["branding"])
app.include_router(branding.public_router, prefix="/api/branding", tags=["branding-public"])
app.include_router(parking_map.router, prefix="/api/parking-map", tags=["parking-map"])
app.include_router(visitor_permits.router, prefix="/api/visitor/permits", tags=["visitor-permits"])

import os as _os
_upload_dir = _os.path.join(_os.path.dirname(__file__), "..", "uploads")
_os.makedirs(_upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=_upload_dir), name="uploads")

_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
if _os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/alerts/banner.js", include_in_schema=False)
async def banner_js():
    """Serve the embeddable alert banner script at a clean URL."""
    from fastapi.responses import FileResponse
    path = _os.path.join(_os.path.dirname(__file__), "static", "banner.js")
    return FileResponse(path, media_type="application/javascript", headers={
        "Cache-Control": "public, max-age=300",
        "Access-Control-Allow-Origin": "*",
    })


@app.get("/health")
async def health():
    from sqlalchemy import text
    from .database import engine
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=503,
            content={"status": "degraded", "error": str(exc)},
        )
    return {"status": "ok", "version": "1.0.0"}
