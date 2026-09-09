"""add podsora models and provider concurrency

Revision ID: 0017_podsora_limits
Revises: 0016_provider_models
Create Date: 2026-06-09
"""

from alembic import op


revision = "0017_podsora_limits"
down_revision = "0016_provider_models"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_4s VARCHAR(128)")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS concurrent_limit INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS concurrent_limit")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_4s")
