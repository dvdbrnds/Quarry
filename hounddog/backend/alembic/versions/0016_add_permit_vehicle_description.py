"""Add vehicle_description column to permits

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-08
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("permits", sa.Column("vehicle_description", sa.String(256), nullable=True))


def downgrade() -> None:
    op.drop_column("permits", "vehicle_description")
