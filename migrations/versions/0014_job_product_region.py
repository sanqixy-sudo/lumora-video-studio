"""add product and region fields to jobs and batches

Revision ID: 0014_job_product_region
Revises: 0013_job_private_protection
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0014_job_product_region"
down_revision = "0013_job_private_protection"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_batches", sa.Column("product_name", sa.String(length=80), nullable=True))
    op.add_column("job_batches", sa.Column("region_name", sa.String(length=80), nullable=True))
    op.create_index("ix_job_batches_product_name", "job_batches", ["product_name"], unique=False)
    op.create_index("ix_job_batches_region_name", "job_batches", ["region_name"], unique=False)

    op.add_column("jobs", sa.Column("product_name", sa.String(length=80), nullable=True))
    op.add_column("jobs", sa.Column("region_name", sa.String(length=80), nullable=True))
    op.create_index("ix_jobs_product_name", "jobs", ["product_name"], unique=False)
    op.create_index("ix_jobs_region_name", "jobs", ["region_name"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_jobs_region_name", table_name="jobs")
    op.drop_index("ix_jobs_product_name", table_name="jobs")
    op.drop_column("jobs", "region_name")
    op.drop_column("jobs", "product_name")

    op.drop_index("ix_job_batches_region_name", table_name="job_batches")
    op.drop_index("ix_job_batches_product_name", table_name="job_batches")
    op.drop_column("job_batches", "region_name")
    op.drop_column("job_batches", "product_name")
