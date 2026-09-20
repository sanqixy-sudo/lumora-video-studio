"""Join NAS legacy quota schema and account session versioning.

The legacy quota revision is already applied on existing NAS installations.
Both branches are retained so those databases and clean installs share one head.
"""

revision = "0024_merge_account_legacy_quota"
down_revision = ("0023_model_quota_costs", "0023_user_session_version")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
