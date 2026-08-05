"""Add channel_config table

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-05
"""
from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_config",
        sa.Column("name", sa.String(64), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_by", sa.String(256), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("channel_config")
