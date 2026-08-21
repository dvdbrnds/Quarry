"""Add allowed_lots to visitor_presets

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-21
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visitor_presets",
        sa.Column("allowed_lots", ARRAY(sa.String()), nullable=False, server_default=sa.text("'{}'::varchar[]")),
    )


def downgrade() -> None:
    op.drop_column("visitor_presets", "allowed_lots")
