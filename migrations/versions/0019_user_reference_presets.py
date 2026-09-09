"""add user-owned reference image presets

Revision ID: 0019_user_reference_presets
Revises: 0018_podgrok_provider
Create Date: 2026-06-17
"""

from alembic import op


revision = "0019_user_reference_presets"
down_revision = "0018_podgrok_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE reference_image_presets ADD COLUMN IF NOT EXISTS owner_user_id BIGINT")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_reference_image_presets_owner_user_id'
            ) THEN
                ALTER TABLE reference_image_presets
                ADD CONSTRAINT fk_reference_image_presets_owner_user_id
                FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE;
            END IF;
        END $$;
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_reference_image_presets_owner_status_sort ON reference_image_presets(owner_user_id, status, sort_order)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_reference_image_presets_owner_status_sort")
    op.execute("ALTER TABLE reference_image_presets DROP CONSTRAINT IF EXISTS fk_reference_image_presets_owner_user_id")
    op.execute("ALTER TABLE reference_image_presets DROP COLUMN IF EXISTS owner_user_id")
