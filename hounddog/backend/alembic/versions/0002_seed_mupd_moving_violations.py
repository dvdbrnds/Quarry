"""Seed MUPD moving violation types from 2026 traffic citation form.

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""

from alembic import op
import sqlalchemy as sa
from uuid import uuid4

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

MOVING_VIOLATIONS = [
    ("stop_sign",               "Failure to Obey Stop Sign",                      "75.00",  1),
    ("one_way",                 "Failure to Obey One-Way Sign",                   "75.00",  2),
    ("do_not_enter",            "Failure to Obey Do Not Enter Sign",              "75.00",  3),
    ("traffic_control_device",  "Failure to Obey Other Traffic Control Devices",  "75.00",  4),
    ("unsafe_speed",            "Driving at Unsafe Speed",                        "75.00",  5),
    ("crosswalk_yield",         "Failure to Yield to a Pedestrian in a Crosswalk","75.00",  6),
    ("careless_driving",        "Careless Driving",                               "100.00", 7),
    ("reckless_driving",        "Reckless Driving",                               "100.00", 8),
    ("no_license",              "Driving Without a Valid License",                 "100.00", 9),
    ("no_registration",         "Driving Without a Valid Vehicle Registration",   "75.00",  10),
    ("no_insurance",            "Driving Without Required Insurance",             "150.00", 11),
]


def upgrade() -> None:
    conn = op.get_bind()
    for code, label, fine, sort_order in MOVING_VIOLATIONS:
        exists = conn.execute(
            sa.text("SELECT 1 FROM violation_types WHERE code = :code"),
            {"code": code},
        ).fetchone()
        if exists:
            conn.execute(
                sa.text("""
                    UPDATE violation_types
                    SET label = :label, category = 'moving', fine_first = :fine,
                        sort_order = :sort_order, is_active = true
                    WHERE code = :code
                """),
                {"label": label, "fine": fine, "sort_order": sort_order, "code": code},
            )
        else:
            conn.execute(
                sa.text("""
                    INSERT INTO violation_types (id, code, label, category, fine_first, sort_order, is_active)
                    VALUES (:id, :code, :label, 'moving', :fine, :sort_order, true)
                """),
                {"id": str(uuid4()), "code": code, "label": label, "fine": fine, "sort_order": sort_order},
            )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [v[0] for v in MOVING_VIOLATIONS]
    for code in codes:
        conn.execute(
            sa.text("UPDATE violation_types SET is_active = false WHERE code = :code"),
            {"code": code},
        )
