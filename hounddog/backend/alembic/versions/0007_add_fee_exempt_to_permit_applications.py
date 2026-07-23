"""Add fee_exempt column to permit_applications

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "permit_applications",
        sa.Column("fee_exempt", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("permit_applications", "fee_exempt")
