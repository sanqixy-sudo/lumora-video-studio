"""Link each regeneration to its previous attempt, preventing duplicate retries."""
from alembic import op
import sqlalchemy as sa
revision = '0025_job_regeneration'
down_revision = '0024_merge_account_legacy_quota'
branch_labels = None
depends_on = None

def upgrade():
    op.add_column('jobs', sa.Column('retry_of_job_id', sa.BigInteger(), nullable=True))
    with op.batch_alter_table('jobs') as batch:
        batch.create_foreign_key('fk_jobs_retry_of_job_id', 'jobs', ['retry_of_job_id'], ['id'], ondelete='SET NULL')
        batch.create_unique_constraint('uq_jobs_retry_of_job_id', ['retry_of_job_id'])

def downgrade():
    with op.batch_alter_table('jobs') as batch:
        batch.drop_constraint('uq_jobs_retry_of_job_id', type_='unique')
        batch.drop_constraint('fk_jobs_retry_of_job_id', type_='foreignkey')
        batch.drop_column('retry_of_job_id')
