"""add provider key runtime fields

Revision ID: 0002_provider_key_runtime_fields
Revises: 0001_initial
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa

revision = '0002_provider_key_runtime_fields'
down_revision = '0001_initial'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('provider_keys', sa.Column('consecutive_failures', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('provider_keys', sa.Column('last_error_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('provider_keys', sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True))
    op.alter_column('provider_keys', 'consecutive_failures', server_default=None)


def downgrade() -> None:
    op.drop_column('provider_keys', 'last_used_at')
    op.drop_column('provider_keys', 'last_error_at')
    op.drop_column('provider_keys', 'consecutive_failures')
