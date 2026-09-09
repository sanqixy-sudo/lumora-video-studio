import uuid
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, JSON, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(16), default='user')
    status: Mapped[str] = mapped_column(String(16), default='active')
    showcase_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    hidden_from_subadmin_reports: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', index=True)
    daily_job_limit: Mapped[int | None] = mapped_column(Integer)
    concurrent_job_limit: Mapped[int | None] = mapped_column(Integer)
    min_submit_interval_seconds: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserProfile(Base):
    __tablename__ = 'user_profiles'
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(128))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProviderKey(Base):
    __tablename__ = 'provider_keys'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    provider_name: Mapped[str] = mapped_column(String(32), default='sora_api')
    key_masked: Mapped[str] = mapped_column(String(128))
    key_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='active')
    weight: Mapped[int] = mapped_column(Integer, default=100)
    daily_limit: Mapped[int | None] = mapped_column(Integer)
    concurrent_limit: Mapped[int | None] = mapped_column(Integer)
    api_base_url: Mapped[str | None] = mapped_column(Text)
    model_id: Mapped[str | None] = mapped_column(String(128))
    model_id_4s: Mapped[str | None] = mapped_column(String(128))
    model_id_5s: Mapped[str | None] = mapped_column(String(128))
    model_id_8s: Mapped[str | None] = mapped_column(String(128))
    model_id_10s: Mapped[str | None] = mapped_column(String(128))
    model_id_12s: Mapped[str | None] = mapped_column(String(128))
    model_id_15s: Mapped[str | None] = mapped_column(String(128))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ReferenceImagePreset(Base):
    __tablename__ = 'reference_image_presets'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    owner_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    name: Mapped[str] = mapped_column(String(128))
    image_url: Mapped[str] = mapped_column(Text)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    aspect_ratio: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default='active')
    sort_order: Mapped[int] = mapped_column(Integer, default=100)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class QuotaWallet(Base):
    __tablename__ = 'quota_wallets'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), unique=True, index=True)
    remaining_quota: Mapped[int] = mapped_column(Integer, default=0)
    total_granted: Mapped[int] = mapped_column(Integer, default=0)
    total_used: Mapped[int] = mapped_column(Integer, default=0)
    reserved_quota: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobBatch(Base):
    __tablename__ = 'job_batches'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), unique=True, index=True)
    batch_code: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    batch_name: Mapped[str | None] = mapped_column(String(128), index=True)
    product_name: Mapped[str | None] = mapped_column(String(80), index=True)
    region_name: Mapped[str | None] = mapped_column(String(80), index=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    batch_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('job_batches.id', ondelete='SET NULL'), index=True)
    batch_index: Mapped[int | None] = mapped_column(Integer)
    provider_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('provider_keys.id'))
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), default=uuid.uuid4, unique=True)
    remote_task_id: Mapped[str | None] = mapped_column(String(128), index=True)
    model: Mapped[str] = mapped_column(String(128), default='sora-2-8s')
    product_name: Mapped[str | None] = mapped_column(String(80), index=True)
    region_name: Mapped[str | None] = mapped_column(String(80), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    seconds: Mapped[int] = mapped_column(Integer, default=12)
    size: Mapped[str] = mapped_column(String(32), default='720x1280')
    status: Mapped[str] = mapped_column(String(32), default='queued', index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error_text: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(Text)
    upstream_response: Mapped[object | None] = mapped_column(JSON().with_variant(JSONB, "postgresql"))
    download_attempts: Mapped[int] = mapped_column(Integer, default=0)
    submit_attempts: Mapped[int] = mapped_column(Integer, default=0)
    queued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_starred: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', index=True)
    starred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_private_protected: Mapped[bool] = mapped_column(Boolean, default=False, server_default='false', index=True)
    private_protected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuotaLedger(Base):
    __tablename__ = 'quota_ledger'
    __table_args__ = (
        UniqueConstraint('job_id', 'action', name='uq_quota_debit_once_per_job'),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('jobs.id'))
    change_amount: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaPlan(Base):
    __tablename__ = 'quota_plans'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    period_type: Mapped[str] = mapped_column(String(16), default='weekly', index=True)
    quota_amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default='active', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class UserQuotaPlanAssignment(Base):
    __tablename__ = 'user_quota_plan_assignments'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    plan_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('quota_plans.id', ondelete='CASCADE'), index=True)
    custom_quota_amount: Mapped[int | None] = mapped_column(Integer)
    remaining_quota: Mapped[int] = mapped_column(Integer, default=0)
    reserved_quota: Mapped[int] = mapped_column(Integer, default=0)
    period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default='active', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobQuotaReservation(Base):
    __tablename__ = 'job_quota_reservations'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('jobs.id', ondelete='CASCADE'), unique=True, index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    assignment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('user_quota_plan_assignments.id', ondelete='SET NULL'), index=True)
    amount: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default='reserved', index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PackageQuotaLedger(Base):
    __tablename__ = 'package_quota_ledger'
    __table_args__ = (
        UniqueConstraint('job_id', 'action', name='uq_package_quota_once_per_job_action'),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    assignment_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('user_quota_plan_assignments.id', ondelete='SET NULL'), index=True)
    plan_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('quota_plans.id', ondelete='SET NULL'), index=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('jobs.id', ondelete='SET NULL'), index=True)
    change_amount: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(64), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    period_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QuotaRequest(Base):
    __tablename__ = 'quota_requests'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    amount: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='pending', index=True)
    reviewer_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'), index=True)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class JobFile(Base):
    __tablename__ = 'job_files'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('jobs.id', ondelete='CASCADE'), index=True)
    file_type: Mapped[str] = mapped_column(String(32))
    file_path: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    duration_seconds: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    playable: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class JobEvent(Base):
    __tablename__ = 'job_events'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('jobs.id', ondelete='CASCADE'), index=True)
    level: Mapped[str] = mapped_column(String(16), default='info')
    event_type: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class APICallLog(Base):
    __tablename__ = 'api_call_logs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    job_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('jobs.id', ondelete='SET NULL'), index=True)
    provider_key_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('provider_keys.id'))
    endpoint: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(16))
    status_code: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    request_summary: Mapped[str | None] = mapped_column(Text)
    response_summary: Mapped[str | None] = mapped_column(Text)
    error_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DailyUsageOverride(Base):
    __tablename__ = 'daily_usage_overrides'
    __table_args__ = (
        UniqueConstraint('user_id', 'usage_date', name='uq_daily_usage_override_user_date'),
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='CASCADE'), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    override_count: Mapped[int] = mapped_column(Integer, default=0)
    real_count_snapshot: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AppSetting(Base):
    __tablename__ = 'app_settings'
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class RiskControlRule(Base):
    __tablename__ = 'risk_control_rules'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    keywords: Mapped[list] = mapped_column(JSONB)
    error_message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default='active', index=True)
    operator_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id', ondelete='SET NULL'))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditLog(Base):
    __tablename__ = 'audit_logs'
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey('users.id'))
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str] = mapped_column(String(32))
    target_id: Mapped[int | None] = mapped_column(BigInteger)
    detail_json: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
