"""add risk control rules and report hidden users

Revision ID: 0020_risk_report
Revises: 0019_user_reference_presets
Create Date: 2026-06-23
"""

from alembic import op


revision = "0020_risk_report"
down_revision = "0019_user_reference_presets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS hidden_from_subadmin_reports BOOLEAN NOT NULL DEFAULT false")
    op.execute("CREATE INDEX IF NOT EXISTS idx_users_hidden_from_subadmin_reports ON users(hidden_from_subadmin_reports)")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS risk_control_rules (
            id BIGSERIAL PRIMARY KEY,
            keywords JSONB NOT NULL,
            error_message TEXT NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            operator_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_risk_control_rules_status ON risk_control_rules(status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_risk_control_rules_status")
    op.execute("DROP TABLE IF EXISTS risk_control_rules")
    op.execute("DROP INDEX IF EXISTS idx_users_hidden_from_subadmin_reports")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS hidden_from_subadmin_reports")
