"""add starred flag for finished materials

Revision ID: 0007_job_starred
Revises: 0006_job_batches
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_job_starred"
down_revision = "0006_job_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("is_starred", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("jobs", sa.Column("starred_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_is_starred", "jobs", ["is_starred"])


def downgrade() -> None:
    op.drop_index("ix_jobs_is_starred", table_name="jobs")
    op.drop_column("jobs", "starred_at")
    op.drop_column("jobs", "is_starred")
