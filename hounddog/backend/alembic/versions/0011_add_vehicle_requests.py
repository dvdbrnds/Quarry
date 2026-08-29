"""Add vehicle_requests table

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-28
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vehicle_requests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("permit_id", UUID(as_uuid=True), sa.ForeignKey("permits.id", ondelete="CASCADE"), nullable=False),
        sa.Column("student_sub", sa.String(256), nullable=False),
        sa.Column("student_email", sa.String(256), nullable=False),
        sa.Column("student_name", sa.String(256), nullable=False),
        sa.Column("plate", sa.String(32), nullable=False),
        sa.Column("plate_state", sa.String(2), server_default=""),
        sa.Column("reason", sa.Text(), server_default=""),
        sa.Column("status", sa.String(32), server_default="pending"),
        sa.Column("decided_by", sa.String(256), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_vehicle_requests_permit", "vehicle_requests", ["permit_id"])
    op.create_index("idx_vehicle_requests_status", "vehicle_requests", ["status"])


def downgrade() -> None:
    op.drop_table("vehicle_requests")
