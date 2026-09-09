"""add human readable job batch name

Revision ID: 0012_job_batch_name
Revises: 0011_sora_api_defaults
Create Date: 2026-06-04
"""

from alembic import op
import sqlalchemy as sa


revision = '0012_job_batch_name'
down_revision = '0011_sora_api_defaults'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_batches", sa.Column("batch_name", sa.String(length=128), nullable=True))
    op.create_index("ix_job_batches_batch_name", "job_batches", ["batch_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_job_batches_batch_name", table_name="job_batches")
    op.drop_column("job_batches", "batch_name")
