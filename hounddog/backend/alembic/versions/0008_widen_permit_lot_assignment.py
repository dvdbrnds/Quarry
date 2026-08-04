"""Widen permits.lot_assignment for multi-lot assignments

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-04
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "permits",
        "lot_assignment",
        existing_type=sa.String(length=128),
        type_=sa.String(length=512),
        existing_nullable=False,
        existing_server_default=sa.text("''"),
    )


def downgrade() -> None:
    op.alter_column(
        "permits",
        "lot_assignment",
        existing_type=sa.String(length=512),
        type_=sa.String(length=128),
        existing_nullable=False,
        existing_server_default=sa.text("''"),
    )
