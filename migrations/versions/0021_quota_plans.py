"""add quota plans

Revision ID: 0021_quota_plans
Revises: 0020_risk_report
Create Date: 2026-06-24
"""

from alembic import op


revision = "0021_quota_plans"
down_revision = "0020_risk_report"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS quota_plans (
            id BIGSERIAL PRIMARY KEY,
            name VARCHAR(128) NOT NULL,
            period_type VARCHAR(16) NOT NULL DEFAULT 'weekly',
            quota_amount INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_quota_plans_period_type ON quota_plans(period_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_quota_plans_status ON quota_plans(status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_quota_plan_assignments (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            plan_id BIGINT NOT NULL REFERENCES quota_plans(id) ON DELETE CASCADE,
            custom_quota_amount INTEGER,
            remaining_quota INTEGER NOT NULL DEFAULT 0,
            reserved_quota INTEGER NOT NULL DEFAULT 0,
            period_start_at TIMESTAMPTZ,
            period_end_at TIMESTAMPTZ,
            next_refresh_at TIMESTAMPTZ,
            last_refreshed_at TIMESTAMPTZ,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_quota_plan_assignments_user ON user_quota_plan_assignments(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_quota_plan_assignments_plan ON user_quota_plan_assignments(plan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_quota_plan_assignments_status ON user_quota_plan_assignments(status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_quota_plan_assignments_next_refresh ON user_quota_plan_assignments(next_refresh_at)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS job_quota_reservations (
            id BIGSERIAL PRIMARY KEY,
            job_id BIGINT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            source_type VARCHAR(16) NOT NULL,
            assignment_id BIGINT REFERENCES user_quota_plan_assignments(id) ON DELETE SET NULL,
            amount INTEGER NOT NULL DEFAULT 1,
            status VARCHAR(16) NOT NULL DEFAULT 'reserved',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_job_quota_reservations_job ON job_quota_reservations(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_quota_reservations_user ON job_quota_reservations(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_quota_reservations_assignment ON job_quota_reservations(assignment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_quota_reservations_source ON job_quota_reservations(source_type)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_quota_reservations_status ON job_quota_reservations(status)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS package_quota_ledger (
            id BIGSERIAL PRIMARY KEY,
            assignment_id BIGINT REFERENCES user_quota_plan_assignments(id) ON DELETE SET NULL,
            plan_id BIGINT REFERENCES quota_plans(id) ON DELETE SET NULL,
            user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            job_id BIGINT REFERENCES jobs(id) ON DELETE SET NULL,
            change_amount INTEGER NOT NULL,
            action VARCHAR(64) NOT NULL,
            note TEXT,
            period_start_at TIMESTAMPTZ,
            operator_user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_package_quota_ledger_assignment ON package_quota_ledger(assignment_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_package_quota_ledger_plan ON package_quota_ledger(plan_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_package_quota_ledger_user ON package_quota_ledger(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_package_quota_ledger_job ON package_quota_ledger(job_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_package_quota_ledger_action ON package_quota_ledger(action)")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'uq_package_quota_once_per_job_action'
            ) THEN
                ALTER TABLE package_quota_ledger
                ADD CONSTRAINT uq_package_quota_once_per_job_action UNIQUE (job_id, action);
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS package_quota_ledger")
    op.execute("DROP TABLE IF EXISTS job_quota_reservations")
    op.execute("DROP TABLE IF EXISTS user_quota_plan_assignments")
    op.execute("DROP TABLE IF EXISTS quota_plans")
