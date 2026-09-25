"""Bootstrap first cjis_admin user and enable JNET system toggle.

Looks up brandesd@moravian.edu's Okta sub from audit_logs (recorded on
every login), then creates the jnet_authorized_users record with
cjis_admin role and flips jnet_system_enabled to true.

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-25
"""
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

ADMIN_EMAIL = "brandesd@moravian.edu"
ADMIN_NAME = "David Brands"


def upgrade() -> None:
    op.execute(f"""
        INSERT INTO jnet_authorized_users (
            id, okta_sub, email, full_name, role,
            jnet_authorized, jnet_authorized_by_email,
            jnet_authorized_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            al.user_sub,
            '{ADMIN_EMAIL}',
            '{ADMIN_NAME}',
            'cjis_admin',
            true,
            'migration-0022',
            now(), now(), now()
        FROM audit_log al
        WHERE al.user_email = '{ADMIN_EMAIL}'
          AND al.user_sub != ''
        ORDER BY al.timestamp DESC
        LIMIT 1
        ON CONFLICT DO NOTHING;
    """)

    op.execute("""
        UPDATE system_settings
        SET value = 'true', updated_by = 'migration-0022'
        WHERE key = 'jnet_system_enabled';
    """)


def downgrade() -> None:
    op.execute(f"""
        DELETE FROM jnet_authorized_users
        WHERE email = '{ADMIN_EMAIL}' AND role = 'cjis_admin';
    """)

    op.execute("""
        UPDATE system_settings
        SET value = 'false', updated_by = 'migration-0022-downgrade'
        WHERE key = 'jnet_system_enabled';
    """)
