"""Add announcement banner fields to branding_settings

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branding_settings",
        sa.Column("announcement_text", sa.String(512), nullable=False, server_default=sa.text("''")),
    )
    op.add_column(
        "branding_settings",
        sa.Column("announcement_url", sa.String(512), nullable=False, server_default=sa.text("''")),
    )


def downgrade() -> None:
    op.drop_column("branding_settings", "announcement_url")
    op.drop_column("branding_settings", "announcement_text")
