"""add duration model ids to provider keys

Revision ID: 0016_provider_models
Revises: 0015_registration_quota_requests
Create Date: 2026-06-09
"""

from alembic import op


revision = "0016_provider_models"
down_revision = "0015_registration_quota_requests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_5s VARCHAR(128)")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_8s VARCHAR(128)")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_10s VARCHAR(128)")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id_12s VARCHAR(128)")
    op.execute("UPDATE provider_keys SET model_id_8s = COALESCE(model_id_8s, model_id, 'sora-2-8s') WHERE provider_name = 'sora_api'")
    op.execute("UPDATE provider_keys SET model_id_12s = COALESCE(model_id_12s, 'sora-2-12s') WHERE provider_name = 'sora_api'")
    op.execute("UPDATE provider_keys SET model_id_5s = COALESCE(model_id_5s, model_id, 'seedance-1.5-pro') WHERE provider_name = 'seedance'")
    op.execute("UPDATE provider_keys SET model_id_10s = COALESCE(model_id_10s, 'seedance-1.5-pro-10s') WHERE provider_name = 'seedance'")
    op.execute("UPDATE provider_keys SET model_id_12s = COALESCE(model_id_12s, 'seedance-1.5-pro-12s') WHERE provider_name = 'seedance'")


def downgrade() -> None:
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_12s")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_10s")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_8s")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id_5s")
