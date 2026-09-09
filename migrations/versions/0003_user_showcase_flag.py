"""add user showcase flag

Revision ID: 0003_user_showcase_flag
Revises: 0002_provider_key_runtime_fields
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_user_showcase_flag"
down_revision = "0002_provider_key_runtime_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("showcase_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column("users", "showcase_enabled", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "showcase_enabled")
