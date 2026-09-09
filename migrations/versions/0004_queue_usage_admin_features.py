"""queue usage and admin features

Revision ID: 0004_queue_usage_admin_features
Revises: 0003_user_showcase_flag
Create Date: 2026-05-12
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_queue_usage_admin_features"
down_revision = "0003_user_showcase_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quota_wallets", sa.Column("reserved_quota", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("quota_wallets", "reserved_quota", server_default=None)

    op.add_column("jobs", sa.Column("submit_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("jobs", sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True))
    op.alter_column("jobs", "submit_attempts", server_default=None)
    op.execute("UPDATE jobs SET queued_at = created_at WHERE queued_at IS NULL")
    op.execute("UPDATE jobs SET submitted_at = created_at WHERE remote_task_id IS NOT NULL AND submitted_at IS NULL")
    op.execute("UPDATE jobs SET failed_at = updated_at WHERE status IN ('failed','download_failed','interrupted') AND failed_at IS NULL")
    op.create_index("ix_jobs_queued_at", "jobs", ["queued_at"])
    op.create_index("ix_jobs_started_at", "jobs", ["started_at"])

    op.create_table(
        "daily_usage_overrides",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("usage_date", sa.Date(), nullable=False),
        sa.Column("override_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("real_count_snapshot", sa.Integer(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("operator_user_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["operator_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "usage_date", name="uq_daily_usage_override_user_date"),
    )
    op.create_index("ix_daily_usage_overrides_user_id", "daily_usage_overrides", ["user_id"])
    op.create_index("ix_daily_usage_overrides_usage_date", "daily_usage_overrides", ["usage_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_usage_overrides_usage_date", table_name="daily_usage_overrides")
    op.drop_index("ix_daily_usage_overrides_user_id", table_name="daily_usage_overrides")
    op.drop_table("daily_usage_overrides")
    op.drop_index("ix_jobs_started_at", table_name="jobs")
    op.drop_index("ix_jobs_queued_at", table_name="jobs")
    op.drop_column("jobs", "failed_at")
    op.drop_column("jobs", "submitted_at")
    op.drop_column("jobs", "started_at")
    op.drop_column("jobs", "queued_at")
    op.drop_column("jobs", "submit_attempts")
    op.drop_column("quota_wallets", "reserved_quota")
