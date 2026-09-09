"""disable provider key failure threshold

Revision ID: 0010_no_key_threshold
Revises: 0009_merge_key_ref
Create Date: 2026-05-26
"""

from alembic import op


revision = '0010_no_key_threshold'
down_revision = '0009_merge_key_ref'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 旧版曾把平台侧 500/502/1205 等问题累计到密钥失败次数，
    # 新版不再使用失败阈值/冷却剔除密钥，因此部署时清理历史状态。
    op.execute("UPDATE provider_keys SET consecutive_failures = 0, last_error_at = NULL")


def downgrade() -> None:
    pass
