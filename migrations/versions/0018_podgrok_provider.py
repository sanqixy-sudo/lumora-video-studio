"""add podgrok duration model

Revision ID: 0018_podgrok_provider
Revises: 0017_podsora_limits
Create Date: 2026-06-09
"""

from alembic import op


revision = "0018_podgrok_provider"
down_revision = "0017_podsora_limits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_15s VARCHAR(128)")


def downgrade() -> None:
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_15s")
