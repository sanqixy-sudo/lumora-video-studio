from alembic import op
import sqlalchemy as sa

revision = '0008_api_ref_preset'
down_revision = '0007_job_starred'
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reference_image_presets_status")
    op.execute("DROP TABLE IF EXISTS reference_image_presets")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS model_id")
    op.execute("ALTER TABLE provider_keys DROP COLUMN IF EXISTS api_base_url")
