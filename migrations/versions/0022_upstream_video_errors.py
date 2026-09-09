"""add upstream video error fields

Revision ID: 0022_upstream_errors
Revises: 0021_quota_plans
Create Date: 2026-06-24
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0022_upstream_errors"
down_revision = "0021_quota_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("jobs")}
    if "error_message" not in existing:
        op.add_column("jobs", sa.Column("error_message", sa.Text(), nullable=True))
    if "error_code" not in existing:
        op.add_column("jobs", sa.Column("error_code", sa.Text(), nullable=True))
    if "upstream_response" not in existing:
        response_type = postgresql.JSONB(astext_type=sa.Text()) if bind.dialect.name == "postgresql" else sa.JSON()
        op.add_column("jobs", sa.Column("upstream_response", response_type, nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = {column["name"] for column in inspector.get_columns("jobs")}
    if "upstream_response" in existing:
        op.drop_column("jobs", "upstream_response")
    if "error_code" in existing:
        op.drop_column("jobs", "error_code")
    if "error_message" in existing:
        op.drop_column("jobs", "error_message")
