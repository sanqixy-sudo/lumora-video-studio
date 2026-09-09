"""job batches for multi prompt creation

Revision ID: 0006_job_batches
Revises: 0005_ops_pages_rate_limits
Create Date: 2026-05-14
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_job_batches"
down_revision = "0005_ops_pages_rate_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "job_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("batch_code", sa.String(length=40), nullable=False),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_job_batches_user_id", "job_batches", ["user_id"])
    op.create_index("ix_job_batches_request_id", "job_batches", ["request_id"], unique=True)
    op.create_index("ix_job_batches_batch_code", "job_batches", ["batch_code"], unique=True)
    op.add_column("jobs", sa.Column("batch_id", sa.BigInteger(), nullable=True))
    op.add_column("jobs", sa.Column("batch_index", sa.Integer(), nullable=True))
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])
    op.create_foreign_key("fk_jobs_batch_id_job_batches", "jobs", "job_batches", ["batch_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_jobs_batch_id_job_batches", "jobs", type_="foreignkey")
    op.drop_index("ix_jobs_batch_id", table_name="jobs")
    op.drop_column("jobs", "batch_index")
    op.drop_column("jobs", "batch_id")
    op.drop_index("ix_job_batches_batch_code", table_name="job_batches")
    op.drop_index("ix_job_batches_request_id", table_name="job_batches")
    op.drop_index("ix_job_batches_user_id", table_name="job_batches")
    op.drop_table("job_batches")
