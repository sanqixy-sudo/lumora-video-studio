"""Invalidate account sessions after password changes."""

from alembic import op
import sqlalchemy as sa

revision = "0023_user_session_version"
down_revision = "0022_upstream_errors"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_version", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "session_version")
