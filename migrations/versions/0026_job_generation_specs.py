"""Persist requested resolution and aspect ratio independently of legacy size."""
from alembic import op
import sqlalchemy as sa

revision = "0026_job_generation_specs"
down_revision = "0025_job_regeneration"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("resolution", sa.String(16), nullable=True))
    op.add_column("jobs", sa.Column("aspect_ratio", sa.String(16), nullable=True))


def downgrade():
    op.drop_column("jobs", "aspect_ratio")
    op.drop_column("jobs", "resolution")
