"""add configurable model quota costs

Revision ID: 0023_model_quota_costs
Revises: 0022_upstream_errors
Create Date: 2026-07-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0023_model_quota_costs"
down_revision = "0022_upstream_errors"
branch_labels = None
depends_on = None


PROVIDER_COST_COLUMNS = (
    "quota_cost_4s",
    "quota_cost_5s",
    "quota_cost_8s",
    "quota_cost_10s",
    "quota_cost_12s",
    "quota_cost_15s",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    provider_columns = {column["name"] for column in inspector.get_columns("provider_keys")}
    for column_name in PROVIDER_COST_COLUMNS:
        if column_name not in provider_columns:
            op.add_column(
                "provider_keys",
                sa.Column(column_name, sa.Integer(), nullable=False, server_default="1"),
            )

    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    if "quota_cost" not in job_columns:
        op.add_column(
            "jobs",
            sa.Column("quota_cost", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    job_columns = {column["name"] for column in inspector.get_columns("jobs")}
    if "quota_cost" in job_columns:
        op.drop_column("jobs", "quota_cost")

    provider_columns = {column["name"] for column in inspector.get_columns("provider_keys")}
    for column_name in reversed(PROVIDER_COST_COLUMNS):
        if column_name in provider_columns:
            op.drop_column("provider_keys", column_name)
