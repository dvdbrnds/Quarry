"""Widen tickets.permit_number from VARCHAR(64) to VARCHAR(256)

Visitor-type permits store custom field data in student_id which flows
into permit_number on ticket creation. Values like
'company_name:Visitor|work_description:Visiting Student|sponsor_department:Student'
exceed 64 chars, causing StringDataRightTruncationError on every retry
(3,400+ Sentry errors in 2 days).

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-13
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "tickets",
        "permit_number",
        existing_type=sa.String(64),
        type_=sa.String(256),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "tickets",
        "permit_number",
        existing_type=sa.String(256),
        type_=sa.String(64),
        existing_nullable=True,
    )
