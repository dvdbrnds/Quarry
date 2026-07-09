"""Add payment_type, payer_name, payer_email, description, plate to payments.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("payment_type", sa.String(48), nullable=True))
    op.add_column("payments", sa.Column("payer_name", sa.String(256), nullable=True))
    op.add_column("payments", sa.Column("payer_email", sa.String(256), nullable=True))
    op.add_column("payments", sa.Column("description", sa.String(512), nullable=True))
    op.add_column("payments", sa.Column("plate", sa.String(20), nullable=True))

    # Backfill payment_type from method for existing rows
    op.execute("""
        UPDATE payments SET payment_type = CASE
            WHEN method = 'online_card' THEN 'ticket_payment'
            WHEN method = 'online_permit_purchase' THEN 'permit_purchase'
            WHEN method = 'bursar' THEN 'ticket_payment'
            ELSE 'ticket_payment'
        END
        WHERE payment_type IS NULL
    """)


def downgrade() -> None:
    op.drop_column("payments", "plate")
    op.drop_column("payments", "description")
    op.drop_column("payments", "payer_email")
    op.drop_column("payments", "payer_name")
    op.drop_column("payments", "payment_type")
