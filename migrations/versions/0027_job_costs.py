"""Store New API task settlement and its correction history."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027_job_costs"
down_revision = "0026_job_generation_specs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "job_costs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_job_id", sa.BigInteger(), nullable=False),
        sa.Column("source_user_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("provider_key_id", sa.BigInteger(), nullable=False),
        sa.Column("api_base_url", sa.Text(), nullable=False),
        sa.Column("provider_name", sa.String(32), nullable=False),
        sa.Column("remote_task_id", sa.String(128), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("seconds", sa.Integer(), nullable=False),
        sa.Column("resolution", sa.String(16)),
        sa.Column("state", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("quota_per_unit", sa.BigInteger()),
        sa.Column("net_quota", sa.BigInteger()),
        sa.Column("amount", sa.Numeric(18, 6)),
        sa.Column("currency", sa.String(8)),
        sa.Column("usage_date", sa.Date()),
        sa.Column("upstream_completed_at", sa.DateTime(timezone=True)),
        sa.Column("source_logs", sa.JSON().with_variant(JSONB(), "postgresql")),
        sa.Column("last_error", sa.Text()),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("next_check_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_job_id", name="uq_job_costs_source_job_id"),
    )
    for column in ("source_user_id", "remote_task_id", "state", "usage_date", "next_check_at"):
        op.create_index(f"ix_job_costs_{column}", "job_costs", [column])
    op.create_table(
        "job_cost_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("source_job_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_quota", sa.BigInteger()),
        sa.Column("new_quota", sa.BigInteger(), nullable=False),
        sa.Column("previous_amount", sa.Numeric(18, 6)),
        sa.Column("new_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("source_logs", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_cost_revisions_source_job_id", "job_cost_revisions", ["source_job_id"])


def downgrade():
    op.drop_index("ix_job_cost_revisions_source_job_id", table_name="job_cost_revisions")
    op.drop_table("job_cost_revisions")
    for column in ("next_check_at", "usage_date", "state", "remote_task_id", "source_user_id"):
        op.drop_index(f"ix_job_costs_{column}", table_name="job_costs")
    op.drop_table("job_costs")
