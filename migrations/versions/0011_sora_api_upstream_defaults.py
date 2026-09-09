"""move provider defaults to sora api upstream

Revision ID: 0011_sora_api_defaults
Revises: 0010_no_key_threshold
Create Date: 2026-06-04
"""

from alembic import op


revision = '0011_sora_api_defaults'
down_revision = '0010_no_key_threshold'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE provider_keys SET provider_name = 'sora_api' WHERE provider_name IN ('packyapi', 'apipod')")
    op.execute("UPDATE provider_keys SET api_base_url = 'https://niubi.zeabur.app' WHERE api_base_url IS NULL OR api_base_url LIKE '%api.apipod.ai%'")
    op.execute("UPDATE provider_keys SET model_id = 'sora-2-8s' WHERE model_id IS NULL OR model_id IN ('sora-2-vip', 'sora-2', 'sora-2-4s')")
    op.execute("UPDATE jobs SET model = 'sora-2-8s' WHERE model IN ('sora-2-vip', 'sora-2', 'sora-2-4s')")


def downgrade() -> None:
    pass
