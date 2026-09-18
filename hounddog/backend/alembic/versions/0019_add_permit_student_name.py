"""Add student_name column to permits table.

The Permit model already defines this column but the migration was never
created, causing _normalize_permit_plates and _backfill_visitor_preset_ids
to crash on every deploy (QUARRY-1X, QUARRY-1Y).

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-18
"""
from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "permits",
        sa.Column("student_name", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("permits", "student_name")
