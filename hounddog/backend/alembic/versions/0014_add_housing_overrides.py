"""Add housing_overrides table for manual resident/commuter overrides

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "housing_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("moravian_id", sa.String(32), nullable=False, unique=True, index=True),
        sa.Column("student_name", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("student_email", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("override_status", sa.String(8), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False, server_default=sa.text("''")),
        sa.Column("created_by", sa.String(256), nullable=False, server_default=sa.text("''")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("housing_overrides")
