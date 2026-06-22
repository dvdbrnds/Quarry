"""Initial schema — baseline migration capturing all inline ALTER TABLE statements.

For existing databases (already created via SQLAlchemy create_all + inline alters):
    alembic stamp head

For fresh databases:
    alembic upgrade head   (after the lifespan create_all has run)

Revision ID: 0001
Revises: —
Create Date: 2026-06-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These mirror the inline ALTER TABLE statements from main.py lifespan.
    # All use IF NOT EXISTS so they are safe to run against an already-migrated DB.

    # devices
    op.execute("ALTER TABLE devices ADD COLUMN IF NOT EXISTS push_token VARCHAR(256)")

    # tickets — enforcement fields
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS ticket_category VARCHAR(32) DEFAULT 'parking'")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS offense_number INTEGER DEFAULT 1")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_lat DOUBLE PRECISION")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_lng DOUBLE PRECISION")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS location_text VARCHAR(512)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS vehicle_description VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_notes TEXT")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS driver_name VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS driver_license VARCHAR(64)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS violation_type_id UUID")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_name VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_email VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS dispute_phone VARCHAR(32)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_name VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS officer_email VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS owner_name VARCHAR(256)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS permit_number VARCHAR(64)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_note TEXT")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_decision VARCHAR(32)")
    op.execute("ALTER TABLE tickets ADD COLUMN IF NOT EXISTS appeal_decided_by VARCHAR(128)")

    # parking_lots — enhanced fields
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS total_spaces INTEGER DEFAULT 0")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS handicap_spaces INTEGER DEFAULT 0")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_code VARCHAR(32) DEFAULT ''")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS designation_label VARCHAR(256) DEFAULT ''")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS access_schedule JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_snow_lot BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS notes TEXT")
    op.execute("ALTER TABLE parking_lots ADD COLUMN IF NOT EXISTS is_closed BOOLEAN DEFAULT false")

    # permits — email field
    op.execute("ALTER TABLE permits ADD COLUMN IF NOT EXISTS email VARCHAR(256)")


def downgrade() -> None:
    # Downgrade intentionally left as no-op: dropping columns from a production
    # database is destructive and should never be automated. Handle manually if needed.
    pass
