"""provider key endpoint and model fields compatibility branch

Revision ID: 0008_provider_key_ext
Revises: 0007_job_starred
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa

revision = '0008_provider_key_ext'
down_revision = '0007_job_starred'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Keep this branch for old databases that may already reference 0008_provider_key_ext.
    # All operations are idempotent so it can safely coexist with 0008_api_ref_preset.
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS api_base_url TEXT")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id VARCHAR(128)")
    op.execute("UPDATE provider_keys SET api_base_url = COALESCE(api_base_url, 'https://niubi.zeabur.app')")
    op.execute("UPDATE provider_keys SET model_id = COALESCE(model_id, 'sora-2-8s')")
    op.alter_column('jobs', 'model', existing_type=sa.String(length=32), type_=sa.String(length=128), existing_nullable=False)


def downgrade() -> None:
    op.alter_column('jobs', 'model', existing_type=sa.String(length=128), type_=sa.String(length=32), existing_nullable=False)
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS api_base_url")
