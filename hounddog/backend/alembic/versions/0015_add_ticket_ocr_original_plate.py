"""Add ocr_original_plate column to tickets for misread reporting

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("ocr_original_plate", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "ocr_original_plate")
