"""Add require_student_name to visitor_presets

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "visitor_presets",
        sa.Column("require_student_name", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.add_column(
        "visitor_presets",
        sa.Column("student_name_label", sa.String(256), nullable=False, server_default=sa.text("'Student name'")),
    )


def downgrade() -> None:
    op.drop_column("visitor_presets", "student_name_label")
    op.drop_column("visitor_presets", "require_student_name")
