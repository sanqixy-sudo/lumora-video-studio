"""add registration setting and quota requests

Revision ID: 0015_registration_quota_requests
Revises: 0014_job_product_region
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = "0015_registration_quota_requests"
down_revision = "0014_job_product_region"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_requests",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("reviewer_user_id", sa.BigInteger(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["reviewer_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_quota_requests_user_id", "quota_requests", ["user_id"], unique=False)
    op.create_index("ix_quota_requests_status", "quota_requests", ["status"], unique=False)
    op.create_index("ix_quota_requests_reviewer_user_id", "quota_requests", ["reviewer_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_quota_requests_reviewer_user_id", table_name="quota_requests")
    op.drop_index("ix_quota_requests_status", table_name="quota_requests")
    op.drop_index("ix_quota_requests_user_id", table_name="quota_requests")
    op.drop_table("quota_requests")
