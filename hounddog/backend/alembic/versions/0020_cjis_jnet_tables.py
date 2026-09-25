"""CJIS/JNET compliance tables.

Creates:
  - jnet_authorized_users  (AC-2/AC-5/AC-6)
  - cjis_audit_logs        (AU-2/AU-3/AU-9/AU-11)
  - cjis_audit_alerts      (AU-6(1))
  - cjis_incidents          (IR-4/IR-6)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -- jnet_authorized_users -------------------------------------------------
    op.create_table(
        "jnet_authorized_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("okta_sub", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("email", sa.String(256), unique=True, nullable=False, index=True),
        sa.Column("full_name", sa.String(512), nullable=False, server_default=""),
        sa.Column("role", sa.String(32), nullable=False, server_default="jnet_officer"),
        sa.Column("jnet_authorized", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("jnet_authorized_by_email", sa.String(256), nullable=True),
        sa.Column("jnet_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jnet_background_check_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jnet_training_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jnet_last_activity", sa.DateTime(timezone=True), nullable=True),
        sa.Column("jnet_last_access_review", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="CJIS Security Policy v6.1 — AC-2/AC-5/AC-6. JNET access authorization tracking.",
    )

    # -- cjis_audit_logs -------------------------------------------------------
    op.create_table(
        "cjis_audit_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_email", sa.String(256), nullable=False),
        sa.Column("user_full_name", sa.String(512), nullable=False, server_default=""),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("query_plate", sa.String(16), nullable=False),
        sa.Column("query_state", sa.String(4), nullable=False, server_default="PA"),
        sa.Column("ori", sa.String(16), nullable=False),
        sa.Column("source_ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("device_id", sa.String(128), nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("response_time_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="CJIS Security Policy v6.1 — AU-2/AU-3. Retain minimum 1 year. No CJI response data stored.",
    )

    op.create_index("ix_cjis_audit_logs_timestamp", "cjis_audit_logs", ["timestamp"])
    op.create_index("ix_cjis_audit_logs_user_id", "cjis_audit_logs", ["user_id"])

    # -- cjis_audit_alerts -----------------------------------------------------
    op.create_table(
        "cjis_audit_alerts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("audit_log_id", UUID(as_uuid=True), sa.ForeignKey("cjis_audit_logs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("reviewed_by", sa.String(256), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("dismiss_reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        comment="CJIS Security Policy v6.1 — AU-6(1). Anomaly detection alerts for JNET queries.",
    )

    op.create_index("ix_cjis_audit_alerts_audit_log_id", "cjis_audit_alerts", ["audit_log_id"])
    op.create_index("ix_cjis_audit_alerts_alert_type", "cjis_audit_alerts", ["alert_type"])
    op.create_index("ix_cjis_audit_alerts_created_at", "cjis_audit_alerts", ["created_at"])

    # -- cjis_incidents --------------------------------------------------------
    op.create_table(
        "cjis_incidents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("incident_type", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("affected_records_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("detected_by", sa.String(256), nullable=False, server_default="system"),
        sa.Column("reported_to_iso_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text, nullable=True),
        comment="CJIS Security Policy v6.1 — IR-4/IR-6. Security incident tracking.",
    )

    op.create_index("ix_cjis_incidents_timestamp", "cjis_incidents", ["timestamp"])
    op.create_index("ix_cjis_incidents_incident_type", "cjis_incidents", ["incident_type"])


def downgrade() -> None:
    op.drop_table("cjis_incidents")
    op.drop_table("cjis_audit_alerts")
    op.drop_table("cjis_audit_logs")
    op.drop_table("jnet_authorized_users")
