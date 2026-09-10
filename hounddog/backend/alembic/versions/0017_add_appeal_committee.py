"""Add appeal committee tables and ticket escalation columns

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-10
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "appeal_committee_members",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(256), unique=True, nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("is_chair", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("added_by", sa.String(256), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "committee_votes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("ticket_id", UUID(as_uuid=True), sa.ForeignKey("tickets.id"), nullable=False),
        sa.Column("voter_email", sa.String(256), nullable=False),
        sa.Column("vote", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("voted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("ticket_id", "voter_email", name="uq_committee_vote_ticket_voter"),
    )

    op.add_column("tickets", sa.Column("committee_status", sa.String(32), nullable=True))
    op.add_column("tickets", sa.Column("committee_decision", sa.String(32), nullable=True))
    op.add_column("tickets", sa.Column("committee_decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tickets", sa.Column("committee_notes", sa.Text(), nullable=True))
    op.add_column("tickets", sa.Column("escalated_by", sa.String(256), nullable=True))
    op.add_column("tickets", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "escalated_at")
    op.drop_column("tickets", "escalated_by")
    op.drop_column("tickets", "committee_notes")
    op.drop_column("tickets", "committee_decided_at")
    op.drop_column("tickets", "committee_decision")
    op.drop_column("tickets", "committee_status")
    op.drop_table("committee_votes")
    op.drop_table("appeal_committee_members")
