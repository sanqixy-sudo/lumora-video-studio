"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-15
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'users',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.Text(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='user'),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_users_username', 'users', ['username'], unique=True)

    op.create_table(
        'user_profiles',
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('display_name', sa.String(length=128)),
        sa.Column('note', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )

    op.create_table(
        'provider_keys',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('provider_name', sa.String(length=32), nullable=False, server_default='sora_api'),
        sa.Column('key_masked', sa.String(length=128), nullable=False),
        sa.Column('key_encrypted', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
        sa.Column('weight', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('daily_limit', sa.Integer()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )

    op.create_table(
        'jobs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_key_id', sa.BigInteger(), sa.ForeignKey('provider_keys.id')),
        sa.Column('request_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('remote_task_id', sa.String(length=128)),
        sa.Column('model', sa.String(length=32), nullable=False, server_default='sora-2'),
        sa.Column('prompt', sa.Text(), nullable=False),
        sa.Column('seconds', sa.Integer(), nullable=False, server_default='12'),
        sa.Column('size', sa.String(length=32), nullable=False, server_default='720x1280'),
        sa.Column('status', sa.String(length=32), nullable=False, server_default='queued'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_text', sa.Text()),
        sa.Column('download_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
    )
    op.create_index('idx_jobs_user_id', 'jobs', ['user_id'])
    op.create_index('idx_jobs_status', 'jobs', ['status'])
    op.create_index('idx_jobs_remote_task_id', 'jobs', ['remote_task_id'])
    op.create_index('uq_jobs_request_id', 'jobs', ['request_id'], unique=True)

    op.create_table(
        'quota_wallets',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('remaining_quota', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_granted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_quota_wallets_user_id', 'quota_wallets', ['user_id'], unique=True)

    op.create_table(
        'quota_ledger',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('jobs.id')),
        sa.Column('change_amount', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('note', sa.Text()),
        sa.Column('operator_user_id', sa.BigInteger(), sa.ForeignKey('users.id')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('ix_quota_ledger_user_id', 'quota_ledger', ['user_id'])
    op.create_index('ix_quota_ledger_action', 'quota_ledger', ['action'])
    op.create_index('uq_quota_debit_once_per_job', 'quota_ledger', ['job_id', 'action'], unique=True)

    op.create_table(
        'job_files',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('file_type', sa.String(length=32), nullable=False),
        sa.Column('file_path', sa.Text(), nullable=False),
        sa.Column('file_name', sa.String(length=255), nullable=False),
        sa.Column('file_size', sa.BigInteger()),
        sa.Column('mime_type', sa.String(length=128)),
        sa.Column('duration_seconds', sa.Numeric(10, 2)),
        sa.Column('width', sa.Integer()),
        sa.Column('height', sa.Integer()),
        sa.Column('playable', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_job_files_job_id', 'job_files', ['job_id'])

    op.create_table(
        'job_events',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('level', sa.String(length=16), nullable=False, server_default='info'),
        sa.Column('event_type', sa.String(length=64), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('payload_json', postgresql.JSONB(astext_type=sa.Text())),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_job_events_job_id_created_at', 'job_events', ['job_id', 'created_at'])

    op.create_table(
        'api_call_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id')),
        sa.Column('job_id', sa.BigInteger(), sa.ForeignKey('jobs.id', ondelete='SET NULL')),
        sa.Column('provider_key_id', sa.BigInteger(), sa.ForeignKey('provider_keys.id')),
        sa.Column('endpoint', sa.Text(), nullable=False),
        sa.Column('method', sa.String(length=16), nullable=False),
        sa.Column('status_code', sa.Integer()),
        sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('latency_ms', sa.Integer()),
        sa.Column('request_summary', sa.Text()),
        sa.Column('response_summary', sa.Text()),
        sa.Column('error_text', sa.Text()),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )
    op.create_index('idx_api_call_logs_user_id', 'api_call_logs', ['user_id'])
    op.create_index('idx_api_call_logs_job_id', 'api_call_logs', ['job_id'])

    op.create_table(
        'audit_logs',
        sa.Column('id', sa.BigInteger(), primary_key=True),
        sa.Column('actor_user_id', sa.BigInteger(), sa.ForeignKey('users.id')),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.BigInteger()),
        sa.Column('detail_json', postgresql.JSONB(astext_type=sa.Text())),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('audit_logs')
    op.drop_index('idx_api_call_logs_job_id', table_name='api_call_logs')
    op.drop_index('idx_api_call_logs_user_id', table_name='api_call_logs')
    op.drop_table('api_call_logs')
    op.drop_index('idx_job_events_job_id_created_at', table_name='job_events')
    op.drop_table('job_events')
    op.drop_index('idx_job_files_job_id', table_name='job_files')
    op.drop_table('job_files')
    op.drop_index('uq_quota_debit_once_per_job', table_name='quota_ledger')
    op.drop_index('ix_quota_ledger_action', table_name='quota_ledger')
    op.drop_index('ix_quota_ledger_user_id', table_name='quota_ledger')
    op.drop_table('quota_ledger')
    op.drop_index('ix_quota_wallets_user_id', table_name='quota_wallets')
    op.drop_table('quota_wallets')
    op.drop_index('uq_jobs_request_id', table_name='jobs')
    op.drop_index('idx_jobs_remote_task_id', table_name='jobs')
    op.drop_index('idx_jobs_status', table_name='jobs')
    op.drop_index('idx_jobs_user_id', table_name='jobs')
    op.drop_table('jobs')
    op.drop_table('provider_keys')
    op.drop_table('user_profiles')
    op.drop_index('ix_users_username', table_name='users')
    op.drop_table('users')
