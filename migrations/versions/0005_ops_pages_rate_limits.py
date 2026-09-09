"""operations pages and user rate limits

Revision ID: 0005_ops_pages_rate_limits
Revises: 0004_queue_usage_admin_features
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_ops_pages_rate_limits"
down_revision = "0004_queue_usage_admin_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("daily_job_limit", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("concurrent_job_limit", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("min_submit_interval_seconds", sa.Integer(), nullable=True))
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("operator_user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_settings")
    op.drop_column("users", "min_submit_interval_seconds")
    op.drop_column("users", "concurrent_job_limit")
    op.drop_column("users", "daily_job_limit")
