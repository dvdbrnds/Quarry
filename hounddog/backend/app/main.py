import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession

from .auth.okta import require_admin
from .config import settings
from .database import get_db
from .routers import (
    academic_calendar,
    alerts,
    appeals,
    audit,
    auth,
    backup,
    branding,
    vouchers,
    devices,
    enforcement_settings,
    fee_exempt,
    discount_roster,
    lots,
    lottery_v2,
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
            # Lottery V2 is production — drop staging cycle names
            "UPDATE lottery_v2_cycles SET name = 'Parking Lottery' WHERE name ILIKE '%staging%'",
            # SMS opt-in captured at lottery/commuter intake (Phase 23: expand to all AlertUs channels)
            "ALTER TABLE lottery_v2_applications ADD COLUMN IF NOT EXISTS sms_opt_in BOOLEAN DEFAULT false",
            # Auto-draw: threshold (e.g. 1.10 = 110%) and deadline
            "ALTER TABLE lottery_v2_cycles ADD COLUMN IF NOT EXISTS auto_draw_threshold DOUBLE PRECISION",
            "ALTER TABLE lottery_v2_cycles ADD COLUMN IF NOT EXISTS auto_draw_at TIMESTAMPTZ",
            # Third-party South lots are sold off-platform (City of Bethlehem)
            "UPDATE permit_types SET is_purchasable_online = FALSE WHERE code = 'south_standalone'",
            # Eligible groups for role-based permit visibility
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS eligible_groups TEXT[] DEFAULT '{}'",
            # Set eligible_groups on faculty_staff so only employees see it
            """UPDATE permit_types SET eligible_groups = '{"_Bethlehem - All - Faculty","_Bethlehem - All - Staff","_MU - Faculty, Adjunct",Quarry-Staff,Quarry-Admin}' WHERE code = 'faculty_staff'""",
            "UPDATE permit_types SET valid_days = 365 WHERE code = 'faculty_staff' AND valid_days = 730",
            "ALTER TABLE branding_settings ADD COLUMN IF NOT EXISTS department_name VARCHAR(256) DEFAULT 'Parking Authority'",
            "UPDATE branding_settings SET department_name = 'Parking Authority' WHERE department_name IS NULL OR department_name = ''",
            # Multi-permit & vehicle swap
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS last_plate_change TIMESTAMPTZ",
            "ALTER TABLE permit_types ADD COLUMN IF NOT EXISTS allow_multiple BOOLEAN DEFAULT FALSE",
            "UPDATE permit_types SET allow_multiple = TRUE WHERE code = 'faculty_staff' AND allow_multiple = FALSE",
            # 2025 planning spreadsheet: update tier caps and lot assignments
            "UPDATE permit_types SET max_capacity = 264, lot_assignments = '{X,A,F,H,M,N,O,R,S}' WHERE code = 'commuter_undergrad'",
            "UPDATE permit_types SET lot_assignments = '{W,A,F,H,M,N,O,R,S}' WHERE code = 'commuter_grad'",
            "UPDATE permit_types SET max_capacity = 200, lot_assignments = '{\"Main St\",\"Iron St.\",\"Monocacy St.\",\"Lenox Ave\",\"W. Greenwich St.\",\"Lorain Ave.\",\"W. Elizabeth\",\"W. Locust St\"}' WHERE code = 'premium_commuter'",
            "UPDATE permit_types SET max_capacity = 58 WHERE code = 'north_premium_resident'",
            "UPDATE permit_types SET max_capacity = 218 WHERE code = 'north_guaranteed_resident'",
            "UPDATE permit_types SET max_capacity = 40 WHERE code = 'south_premium_resident'",
            "UPDATE permit_types SET max_capacity = 44, lot_assignments = '{U}' WHERE code = 'south_guaranteed_resident'",
            "UPDATE permit_types SET max_capacity = 100 WHERE code = 'south_standalone'",
            "UPDATE permit_types SET lot_assignments = '{A,F,H,M,N,O,R,S,U,W}' WHERE code = 'faculty_staff'",
            # 2025 planning spreadsheet: update lot spot counts
            "UPDATE parking_lots SET total_spaces = 103 WHERE name = 'A'",
            "UPDATE parking_lots SET total_spaces = 95 WHERE name = 'B'",
            "UPDATE parking_lots SET total_spaces = 22 WHERE name = 'C'",
            "UPDATE parking_lots SET total_spaces = 12 WHERE name = 'D'",
            "UPDATE parking_lots SET total_spaces = 57 WHERE name = 'F'",
            "UPDATE parking_lots SET total_spaces = 22 WHERE name = 'G'",
            "UPDATE parking_lots SET total_spaces = 19 WHERE name = 'H'",
            "UPDATE parking_lots SET total_spaces = 22 WHERE name = 'I'",
            "UPDATE parking_lots SET total_spaces = 18 WHERE name = 'J'",
            "UPDATE parking_lots SET total_spaces = 18 WHERE name = 'M'",
            "UPDATE parking_lots SET total_spaces = 20 WHERE name = 'N'",
            "UPDATE parking_lots SET total_spaces = 16 WHERE name = 'O'",
            "UPDATE parking_lots SET total_spaces = 18 WHERE name = 'P'",
            "UPDATE parking_lots SET total_spaces = 42, campus = 'north' WHERE name = 'Q'",
            "UPDATE parking_lots SET total_spaces = 22 WHERE name = 'R'",
            "UPDATE parking_lots SET total_spaces = 26 WHERE name = 'S'",
            "UPDATE parking_lots SET total_spaces = 49 WHERE name = 'T'",
            "UPDATE parking_lots SET total_spaces = 88 WHERE name = 'U'",
            "UPDATE parking_lots SET total_spaces = 112 WHERE name = 'W'",
            "UPDATE parking_lots SET total_spaces = 264 WHERE name = 'X'",
            "UPDATE parking_lots SET total_spaces = 40 WHERE name = 'Z'",
            "UPDATE parking_lots SET total_spaces = 36 WHERE name = 'W. Laurel St'",
            "UPDATE parking_lots SET total_spaces = 25 WHERE name = 'W. Locust St'",
            "UPDATE parking_lots SET total_spaces = 50 WHERE name = 'Lehigh St'",
            "UPDATE parking_lots SET total_spaces = 100 WHERE name = 'Spring St'",
            # Update COMMUTER_EVENING_SCHEDULE on all FSC lots (change 07:00 to 06:00)
            """UPDATE parking_lots
               SET access_schedule = REPLACE(access_schedule::text, '"07:00"', '"06:00"')::jsonb
               WHERE designation_code = 'FSC' AND access_schedule IS NOT NULL AND access_schedule::text LIKE '%07:00%'""",
            """CREATE TABLE IF NOT EXISTS app_config (
                key VARCHAR(128) PRIMARY KEY,
                value JSONB NOT NULL DEFAULT '{}',
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS photo_data BYTEA",
            "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS photo_mime VARCHAR(64)",
            # Fee-exempt roster for RAs, RDs, etc.
            """CREATE TABLE IF NOT EXISTS fee_exempt_roster (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id VARCHAR(64) NOT NULL,
                email VARCHAR(256),
                first_name VARCHAR(256) DEFAULT '',
                last_name VARCHAR(256) DEFAULT '',
                reason VARCHAR(256) DEFAULT 'Res Life Staff',
                building VARCHAR(256),
                room VARCHAR(128),
                academic_year VARCHAR(16),
                created_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_fee_exempt_roster_student_id ON fee_exempt_roster(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_fee_exempt_roster_email ON fee_exempt_roster(email)",
            # Program discount roster (ABSN $100 off, etc.)
            """CREATE TABLE IF NOT EXISTS discount_roster (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                student_id VARCHAR(64) NOT NULL,
                email VARCHAR(256),
                first_name VARCHAR(256) DEFAULT '',
                last_name VARCHAR(256) DEFAULT '',
                program_name VARCHAR(256) DEFAULT 'ABSN',
                discount_amount NUMERIC(10,2) DEFAULT 100.00,
                academic_year VARCHAR(16),
                created_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_discount_roster_student_id ON discount_roster(student_id)",
            "CREATE INDEX IF NOT EXISTS idx_discount_roster_email ON discount_roster(email)",
            # Rename coupon → voucher (preserve existing data; no-op if already renamed)
            """DO $$ BEGIN
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='coupons')
                   AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='vouchers') THEN
                    ALTER TABLE coupons RENAME TO vouchers;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='coupon_usages')
                   AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='voucher_usages') THEN
                    ALTER TABLE coupon_usages RENAME TO voucher_usages;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='voucher_usages' AND column_name='coupon_id') THEN
                    ALTER TABLE voucher_usages RENAME COLUMN coupon_id TO voucher_id;
                END IF;
                IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='voucher_usages' AND column_name='coupon_code') THEN
                    ALTER TABLE voucher_usages RENAME COLUMN coupon_code TO voucher_code;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_class WHERE relname='idx_coupons_code') THEN
                    ALTER INDEX idx_coupons_code RENAME TO idx_vouchers_code;
                END IF;
                IF EXISTS (SELECT 1 FROM pg_class WHERE relname='idx_coupon_usages_coupon_id') THEN
                    ALTER INDEX idx_coupon_usages_coupon_id RENAME TO idx_voucher_usages_voucher_id;
                END IF;
            END $$""",
            # Voucher codes for academic programs
            """CREATE TABLE IF NOT EXISTS vouchers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                code VARCHAR(64) NOT NULL UNIQUE,
                program_name VARCHAR(256) DEFAULT '',
                discount_type VARCHAR(16) NOT NULL,
                discount_value NUMERIC(8,2) DEFAULT 0,
                applicable_permit_codes TEXT[] DEFAULT '{}',
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                is_active BOOLEAN DEFAULT true,
                expires_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ DEFAULT now(),
                updated_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_vouchers_code ON vouchers(code)",
            # Admin permit charge — link permit to Stripe session for payment
            "ALTER TABLE permits ADD COLUMN IF NOT EXISTS stripe_session_id VARCHAR(255)",
            # Voucher usage tracking for department chargebacks
            """CREATE TABLE IF NOT EXISTS voucher_usages (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                voucher_id UUID NOT NULL,
                voucher_code VARCHAR(64) NOT NULL,
                program_name VARCHAR(256) DEFAULT '',
                student_name VARCHAR(256) DEFAULT '',
                student_email VARCHAR(256) DEFAULT '',
                student_id VARCHAR(64) DEFAULT '',
                permit_type_code VARCHAR(64) DEFAULT '',
                original_price NUMERIC(8,2) DEFAULT 0,
                discount_amount NUMERIC(8,2) DEFAULT 0,
                final_price NUMERIC(8,2) DEFAULT 0,
                used_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_voucher_usages_voucher_id ON voucher_usages(voucher_id)",
            # Stripe transaction cache for fast Finance page loads
            """CREATE TABLE IF NOT EXISTS stripe_transaction_cache (
                id VARCHAR(256) PRIMARY KEY,
                source VARCHAR(32) DEFAULT 'charge',
                amount NUMERIC(10,2) DEFAULT 0,
                amount_refunded NUMERIC(10,2) DEFAULT 0,
                net NUMERIC(10,2) DEFAULT 0,
                fee NUMERIC(10,2) DEFAULT 0,
                currency VARCHAR(8) DEFAULT 'usd',
                status VARCHAR(32) DEFAULT 'succeeded',
                description TEXT,
                customer_email VARCHAR(256),
                customer_name VARCHAR(256),
                receipt_url VARCHAR(512),
                payment_method_type VARCHAR(64),
                payment_method_last4 VARCHAR(8),
                payment_method_brand VARCHAR(64),
                metadata_json JSONB,
                created_at TIMESTAMPTZ NOT NULL,
                livemode BOOLEAN DEFAULT false,
                cached_at TIMESTAMPTZ DEFAULT now()
            )""",
            "CREATE INDEX IF NOT EXISTS idx_stripe_cache_created ON stripe_transaction_cache(created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_stripe_cache_status ON stripe_transaction_cache(status)",
            ]
            for migration in migrations:
                try:
                    await conn.execute(text(migration))
                except Exception as e:
                    logger.error(f"Migration failed: {migration[:80]}... -> {e}")
                    raise
        finally:
            try:
                await conn.execute(text("SELECT pg_advisory_unlock(42)"))
            except Exception:
                pass

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
                    {"code": "commuter_undergrad", "label": "Regular Commuter (Undergrad)", "eligible": "Commuter undergrads", "price": 100, "max_capacity": 264, "valid_days": 365, "lot_assignments": ["X", "A", "F", "H", "M", "N", "O", "R", "S"], "is_purchasable_online": True, "sort_order": 1},
                    {"code": "commuter_grad", "label": "Regular Commuter (Grad)", "eligible": "Grad/seminary/continuing ed", "price": 100, "max_capacity": 112, "valid_days": 365, "lot_assignments": ["W", "A", "F", "H", "M", "N", "O", "R", "S"], "is_purchasable_online": True, "sort_order": 2},
                    {"code": "premium_commuter", "label": "Extended Premium Commuter", "eligible": "Commuter students", "price": 150, "max_capacity": 200, "valid_days": 365, "lot_assignments": ["Main St", "Iron St.", "Monocacy St.", "Lenox Ave", "W. Greenwich St.", "Lorain Ave.", "W. Elizabeth", "W. Locust St"], "is_purchasable_online": True, "sort_order": 3},
                    {"code": "north_premium_resident", "label": "North Premium Resident", "eligible": "Resident students (seniority-based)", "price": 400, "max_capacity": 58, "valid_days": 365, "lot_assignments": ["I", "W. Laurel St"], "is_purchasable_online": False, "sort_order": 4},
                    {"code": "north_guaranteed_resident", "label": "North Guaranteed Resident", "eligible": "Resident students (seniority-based)", "price": 250, "max_capacity": 218, "valid_days": 365, "lot_assignments": ["B", "C", "D", "G", "P", "T"], "is_purchasable_online": False, "sort_order": 5},
                    {"code": "steel_field_resident", "label": "Steel Field Resident", "eligible": "Resident students", "price": 75, "max_capacity": 42, "valid_days": 365, "lot_assignments": ["Q"], "is_purchasable_online": True, "sort_order": 6},
                    {"code": "south_premium_resident", "label": "South Premium Resident", "eligible": "Resident students (seniority-based)", "price": 400, "max_capacity": 40, "valid_days": 365, "lot_assignments": ["Z"], "is_purchasable_online": False, "sort_order": 7},
                    {"code": "south_guaranteed_resident", "label": "South Guaranteed Resident", "eligible": "Resident students (seniority-based)", "price": 250, "max_capacity": 44, "valid_days": 365, "lot_assignments": ["U"], "is_purchasable_online": False, "sort_order": 8},
                    {"code": "south_standalone", "label": "South Third Party", "eligible": "Resident students", "price": 100, "max_capacity": 100, "valid_days": 365, "lot_assignments": ["Lehigh St", "Spring St"], "is_purchasable_online": False, "sort_order": 9},
                    {"code": "faculty_staff", "label": "Faculty/Staff", "eligible": "Employees", "price": 0, "max_capacity": 500, "valid_days": 365, "lot_assignments": ["A", "F", "H", "M", "N", "O", "R", "S", "U", "W"], "is_purchasable_online": False, "sort_order": 10, "eligible_groups": ["_Bethlehem - All - Faculty", "_Bethlehem - All - Staff", "_MU - Faculty, Adjunct", "Quarry-Staff", "Quarry-Admin"]},
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
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #c0392b;">Snow Emergency — Lot Closure</h2><p><strong>{lot_name}</strong> at {school} is closed for snow removal effective <strong>{closes_at}</strong>.</p><p><strong>Move your vehicle immediately.</strong> Vehicles remaining may be towed.</p><p>Expected reopening: {reopens_at}</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for snow removal effective {closes_at}. Move your vehicle immediately.",
                    },
                    {
                        "reason_code": "repaving",
                        "reason_label": "Repaving",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Repaving",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Repaving</h2><p><strong>{lot_name}</strong> at {school} will be closed for repaving effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for repaving {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "tree_cutting",
                        "reason_label": "Tree Maintenance",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Tree Maintenance",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Tree Maintenance</h2><p><strong>{lot_name}</strong> at {school} will be closed for tree work effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for tree work {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "event",
                        "reason_label": "Campus Event",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name} — Campus Event",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure — Campus Event</h2><p><strong>{lot_name}</strong> at {school} will be closed for a campus event effective <strong>{closes_at}</strong>.</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed for campus event {closes_at}. Reopens {reopens_at}.",
                    },
                    {
                        "reason_code": "emergency",
                        "reason_label": "Emergency",
                        "is_emergency": True,
                        "email_subject": "URGENT: {lot_name} Closed — Emergency",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #c0392b;">Emergency Lot Closure</h2><p><strong>{lot_name}</strong> at {school} has been closed immediately.</p><p><strong>Reason:</strong> {reason}</p><p>Please avoid the area. Vehicles remaining may be towed.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
                        "sms_body": "{school} Parking: {lot_name} closed immediately. {reason}. Avoid the area.",
                    },
                    {
                        "reason_code": "general",
                        "reason_label": "General Closure",
                        "is_emergency": False,
                        "email_subject": "Parking Lot Closed: {lot_name}",
                        "email_body": '<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;"><h2 style="color: #1a2744;">Lot Closure Notice</h2><p><strong>{lot_name}</strong> at {school} has been closed effective <strong>{closes_at}</strong>.</p><p><strong>Reason:</strong> {reason}</p><p>Expected reopening: <strong>{reopens_at}</strong></p><p>Please make alternative parking arrangements.</p><hr style="border: none; border-top: 1px solid #ddd; margin: 24px 0;"><p style="font-size: 12px; color: #888;">{school} {department} — Quarry</p></div>',
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

    from .services.notification_health import check_notification_config
    check_notification_config()

    from .services.env_preflight import run_preflight
    run_preflight()

    # Migrate any existing disk-based backup schedule into DB (one-time on first deploy)
    try:
        from .services.backup_scheduler import SCHEDULE_FILE
        if SCHEDULE_FILE.exists():
            import json as _json
            _disk_schedule = _json.loads(SCHEDULE_FILE.read_text())
            if _disk_schedule.get("enabled"):
                from .database import async_session as _as
                async with _as() as _db:
                    from sqlalchemy import text as _text
                    _existing = await _db.execute(
                        _text("SELECT value FROM app_config WHERE key = 'backup_schedule'")
                    )
                    if not _existing.scalar():
                        _val = _json.dumps(_disk_schedule)
                        await _db.execute(_text("""
                            INSERT INTO app_config (key, value, updated_at)
                            VALUES ('backup_schedule', CAST(:val AS jsonb), now())
                            ON CONFLICT (key) DO NOTHING
                        """), {"val": _val})
                        await _db.commit()
                        logger.info("Migrated backup schedule from disk to DB")
    except Exception as e:
        logger.warning("Backup schedule disk->DB migration skipped: %s", e)

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
app.include_router(appeals.router, prefix="/api/appeals", tags=["appeals"])
app.include_router(appeals.public_router, prefix="/api/appeals", tags=["appeals-public"])
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
app.include_router(lottery_v2.router, prefix="/api/lottery-v2", tags=["lottery-v2"])
app.include_router(renewals.router, prefix="/api/renewals", tags=["renewals"])
app.include_router(alerts.admin_router, prefix="/api/alerts", tags=["alerts"])
app.include_router(alerts.public_router, prefix="/api/alerts", tags=["alerts-public"])
app.include_router(signage.admin_router, prefix="/api/signage", tags=["signage"])
app.include_router(signage.public_router, prefix="/api/signage", tags=["signage-public"])
app.include_router(backup.router, prefix="/api/backup", tags=["backup"])
app.include_router(fee_exempt.router, prefix="/api/admin/fee-exempt", tags=["fee-exempt"])
app.include_router(discount_roster.router, prefix="/api/admin/discounts", tags=["discounts"])
app.include_router(branding.admin_router, prefix="/api/branding", tags=["branding"])
app.include_router(branding.public_router, prefix="/api/branding", tags=["branding-public"])
app.include_router(parking_map.router, prefix="/api/parking-map", tags=["parking-map"])
app.include_router(visitor_permits.router, prefix="/api/visitor/permits", tags=["visitor-permits"])
app.include_router(vouchers.admin_router, prefix="/api/vouchers", tags=["vouchers"])
app.include_router(vouchers.router, prefix="/api/vouchers", tags=["vouchers"])


@app.get("/api/admin/notification-health", tags=["admin"])
async def notification_health(user=Depends(require_admin())):
    from .services.notification_health import stats, check_notification_config
    return {
        "config_warnings": check_notification_config(),
        **stats.summary(),
    }


@app.get("/api/admin/preflight", tags=["admin"])
async def preflight_check(user=Depends(require_admin())):
    from .services.env_preflight import run_preflight
    results = run_preflight()
    all_pass = all(r["status"] != "fail" for r in results)
    return {"status": "pass" if all_pass else "fail", "checks": results}


@app.post("/api/admin/migrate-photos", tags=["admin"])
async def migrate_photos_to_db(user=Depends(require_admin()), db: AsyncSession = Depends(get_db)):
    """One-time migration: copy any disk-based ticket photos into the database."""
    import os
    from sqlalchemy import select as _select
    from .models.ticket import Ticket

    upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "photos")
    if not os.path.isdir(upload_dir):
        return {"migrated": 0, "skipped": 0, "errors": 0}

    result = await db.execute(
        _select(Ticket).where(
            Ticket.photo_url.ilike("%/uploads/photos/%"),
            Ticket.photo_data.is_(None),
        )
    )
    tickets = result.scalars().all()

    migrated = 0
    skipped = 0
    errors = 0
    for ticket in tickets:
        filename = ticket.photo_url.split("/uploads/photos/")[-1]
        filepath = os.path.join(upload_dir, filename)
        if not os.path.isfile(filepath):
            skipped += 1
            continue
        try:
            with open(filepath, "rb") as f:
                ticket.photo_data = f.read()
            ticket.photo_mime = "image/jpeg"
            ticket.photo_url = f"/api/tickets/{ticket.id}/photo"
            migrated += 1
        except Exception:
            errors += 1

    if migrated > 0:
        await db.commit()
    return {"migrated": migrated, "skipped": skipped, "errors": errors}


@app.get("/api/admin/impersonate-lookup", tags=["admin"])
async def impersonate_lookup(email: str, user=Depends(require_admin()), db: AsyncSession = Depends(get_db)):
    """Look up a user's identity by email for impersonation purposes."""
    from sqlalchemy import text
    import httpx

    if not email or not email.strip():
        from fastapi import HTTPException as _HTTPException
        raise _HTTPException(400, "email parameter required")

    email = email.strip().lower()

    sub = ""
    name = email
    groups: list[str] = []
    class_year = None

    # Primary source: Okta API
    if settings.okta_domain and settings.okta_api_token:
        try:
            async with httpx.AsyncClient() as client:
                user_res = await client.get(
                    f"https://{settings.okta_domain}/api/v1/users/{email}",
                    headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                    timeout=10,
                )
                if user_res.status_code == 200:
                    okta_user = user_res.json()
                    sub = okta_user.get("id", "")
                    profile = okta_user.get("profile", {})
                    name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or email

                    groups_res = await client.get(
                        f"https://{settings.okta_domain}/api/v1/users/{okta_user['id']}/groups",
                        headers={"Authorization": f"SSWS {settings.okta_api_token}"},
                        timeout=10,
                    )
                    if groups_res.status_code == 200:
                        groups = [
                            g["profile"]["name"]
                            for g in groups_res.json()
                            if g.get("profile", {}).get("name")
                        ]

                    cy = profile.get(settings.okta_class_year_claim)
                    if cy:
                        try:
                            class_year = int(cy)
                        except (ValueError, TypeError):
                            pass
        except Exception:
            pass

    # Fallback to DB if Okta didn't find them
    if not sub:
        app_result = await db.execute(text("""
            SELECT student_sub, student_name, student_email, class_year, okta_metadata
            FROM permit_applications
            WHERE LOWER(student_email) = :email
            ORDER BY created_at DESC LIMIT 1
        """), {"email": email})
        app_row = app_result.mappings().first()

        perm_result = await db.execute(text("""
            SELECT student_id as sub, name, email
            FROM permits
            WHERE LOWER(email) = :email AND deleted_at IS NULL
            ORDER BY created_at DESC LIMIT 1
        """), {"email": email})
        perm_row = perm_result.mappings().first()

        if not app_row and not perm_row:
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(404, f"No user found with email: {email}")

        if app_row:
            sub = app_row["student_sub"] or ""
            name = app_row["student_name"] or email
            class_year = app_row["class_year"]
            metadata = app_row["okta_metadata"] or {}
            if isinstance(metadata, dict) and not groups:
                groups = metadata.get("groups", [])
        elif perm_row:
            sub = perm_row["sub"] or ""
            name = perm_row["name"] or email

    # Determine role from groups
    from .auth.okta import OktaUser
    temp_user = OktaUser(
        sub=sub or f"impersonated:{email}",
        email=email,
        groups=groups,
        given_name=name.split(" ", 1)[0],
        family_name=name.split(" ", 1)[1] if " " in name else "",
        display_name=name,
        class_year=class_year,
    )
    role = temp_user.role if temp_user.role != "none" else "student"

    return {
        "sub": sub or f"impersonated:{email}",
        "email": email,
        "name": name,
        "groups": groups,
        "role": role,
        "class_year": class_year,
    }


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
