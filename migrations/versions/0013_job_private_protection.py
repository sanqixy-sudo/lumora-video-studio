"""add private protection flag for user works

Revision ID: 0013_job_private_protection
Revises: 0012_job_batch_name
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_job_private_protection"
down_revision = "0012_job_batch_name"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("is_private_protected", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("jobs", sa.Column("private_protected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_jobs_is_private_protected", "jobs", ["is_private_protected"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_is_private_protected", table_name="jobs")
    op.drop_column("jobs", "private_protected_at")
    op.drop_column("jobs", "is_private_protected")
