"""merge provider key and reference preset migration heads

Revision ID: 0009_merge_key_ref
Revises: 0008_provider_key_ext, 0008_api_ref_preset
Create Date: 2026-05-26
"""

from alembic import op
import sqlalchemy as sa

revision = '0009_merge_key_ref'
down_revision = ('0008_provider_key_ext', '0008_api_ref_preset')
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Safety pass for machines that previously applied only one of the 0008 branches.
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS api_base_url TEXT")
    op.execute("ALTER TABLE provider_keys ADD COLUMN IF NOT EXISTS model_id VARCHAR(128)")
    op.execute("UPDATE provider_keys SET api_base_url = COALESCE(api_base_url, 'https://niubi.zeabur.app')")
    op.execute("UPDATE provider_keys SET model_id = COALESCE(model_id, 'sora-2-8s')")
    op.execute("""
    CREATE TABLE IF NOT EXISTS reference_image_presets (
        id BIGSERIAL PRIMARY KEY,
        name VARCHAR(128) NOT NULL,
        image_url TEXT NOT NULL,
        width INTEGER NULL,
        height INTEGER NULL,
        aspect_ratio VARCHAR(32) NULL,
        status VARCHAR(16) NOT NULL DEFAULT 'active',
        sort_order INTEGER NOT NULL DEFAULT 100,
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_reference_image_presets_status ON reference_image_presets(status)")
    try:
        op.alter_column('jobs', 'model', existing_type=sa.String(length=32), type_=sa.String(length=128), existing_nullable=False)
    except Exception:
        # If the column is already VARCHAR(128), keep migration idempotent across mixed upgrade states.
        pass


def downgrade() -> None:
    # Merge revision only; leave actual schema rollback to branch downgrades.
    pass
