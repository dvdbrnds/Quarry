"""Add campus column to parking_lots.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-10
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("parking_lots", sa.Column("campus", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("parking_lots", "campus")
