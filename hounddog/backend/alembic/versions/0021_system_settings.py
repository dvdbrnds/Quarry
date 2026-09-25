"""System settings key-value table.

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("value", sa.String(1024), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
            sa.String(256),
            nullable=False,
            server_default="system",
        ),
    )

    # Seed the JNET system toggle (off by default)
    op.execute(
        "INSERT INTO system_settings (key, value, updated_by) "
        "VALUES ('jnet_system_enabled', 'false', 'system')"
    )


def downgrade() -> None:
    op.drop_table("system_settings")
