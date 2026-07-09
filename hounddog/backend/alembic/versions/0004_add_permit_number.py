"""Add permit_number column and QPS sequence to permits.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("permits", sa.Column("permit_number", sa.String(32), nullable=True))
    op.create_unique_constraint("uq_permits_permit_number", "permits", ["permit_number"])

    # Seed the sequence starting after 0 so the first Quarry-issued permit is QPS-00001.
    # Legacy permits keep their original numbers (populated during import) and don't
    # consume from this sequence.
    op.execute("CREATE SEQUENCE IF NOT EXISTS qps_permit_number_seq START WITH 1")


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS qps_permit_number_seq")
    op.drop_constraint("uq_permits_permit_number", "permits", type_="unique")
    op.drop_column("permits", "permit_number")
