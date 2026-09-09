from __future__ import annotations

import base64
import hashlib
import hmac
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import date_bounds_utc, format_shanghai_datetime_short, shanghai_now
from app.models.tables import Job, JobBatch, JobEvent, JobFile, ProviderKey, QuotaLedger, QuotaWallet, User
from app.services.provider_keys import provider_is_retired, normalize_provider_name
from app.services.media import create_video_poster, probe_media
from app.services.system_settings import get_system_setting_int

TERMINAL_STATUSES = {"completed", "download_failed", "failed", "cancelled", "interrupted"}
RUNNING_STATUSES = {"submitting", "submitted", "polling"}
REDOWNLOAD_ALLOWED = {"download_failed", "remote_completed", "download_waiting", "downloading"}
RESUME_ALLOWED = {"interrupted", "polling", "submitted", "failed", "download_failed", "remote_completed", "download_waiting", "downloading"}
PAUSE_ALLOWED = {"submitted", "polling", "remote_completed", "download_waiting", "downloading", "failed", "download_failed"}
STATUS_LABELS = {
    "queued": "排队中",
    "submitting": "提交中",
    "submitted": "已提交",
    "polling": "查询中",
    "remote_completed": "待下载",
    "download_waiting": "等待下载",
    "downloading": "下载中",
    "completed": "已完成",
    "download_failed": "下载失败",
    "failed": "失败",
    "cancelled": "已取消",
    "interrupted": "已暂停",
    "stopped": "已停止",
}
RETRYABLE_FAILURE_HINTS = {
    "timeout",
    "timed out",
    "temporarily unavailable",
    "temporary unavailable",
    "service unavailable",
    "server error",
    "internal error",
    "internal_error",
    "rate limit",
    "too many requests",
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection reset",
    "connection aborted",
    "connection error",
    "network error",
    "upstream unavailable",
}
NON_RETRYABLE_FAILURE_HINTS = {
    "moderation_blocked",
    "blocked by our moderation",
    "content_policy",
    "content policy",
    "safety",
    "invalid_request",
    "invalid request",
    "forbidden",
    "unsupported",
}


def utcnow() -> datetime:
    return datetime.now(UTC)



def _token_secret() -> bytes:
    return str(settings.app_secret_key or "change-me").encode("utf-8")


def make_public_remote_download_token(job_id: int, remote_task_id: str | None, ttl_seconds: int | None = None) -> str | None:
    if not remote_task_id:
        return None
    ttl = int(ttl_seconds or settings.public_download_token_ttl_seconds or 86400)
    expires = int(time.time()) + max(ttl, 60)
    body = f"{int(job_id)}:{remote_task_id}:{expires}"
    sig = hmac.new(_token_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{body}:{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def verify_public_remote_download_token(token: str, job_id: int, remote_task_id: str | None) -> bool:
    if not token or not remote_task_id:
        return False
    try:
        padded = token + "=" * (-len(token) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        token_job_id, token_remote_task_id, expires_text, sig = raw.rsplit(":", 3)
        expires = int(expires_text)
    except Exception:
        return False
    if str(job_id) != token_job_id or str(remote_task_id) != token_remote_task_id:
        return False
    if expires < int(time.time()):
        return False
    body = f"{token_job_id}:{token_remote_task_id}:{expires}"
    expected = hmac.new(_token_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

def status_label(status: str | None) -> str:
    return STATUS_LABELS.get(str(status or ""), str(status or "-"))


def add_event(db: Session, job_id: int, level: str, event_type: str, message: str, payload_json: dict | None = None) -> None:
    db.add(JobEvent(job_id=job_id, level=level, event_type=event_type, message=message, payload_json=payload_json))


def create_reference_file_record(db: Session, job_id: int, path: Path) -> JobFile:
    row = JobFile(
        job_id=job_id,
        file_type="reference_image",
        file_path=str(path),
        file_name=path.name,
        file_size=path.stat().st_size,
        mime_type="image/png" if path.suffix.lower() == ".png" else None,
        playable=False,
    )
    db.add(row)
    return row


def create_reference_url_record(db: Session, job_id: int, image_url: str, *, name: str | None = None, width: int | None = None, height: int | None = None) -> JobFile:
    row = JobFile(
        job_id=job_id,
        file_type="reference_image_url",
        file_path=str(image_url),
        file_name=(name or "reference_url")[:255],
        file_size=None,
        mime_type="image/url",
        width=width,
        height=height,
        playable=False,
    )
    db.add(row)
    return row


def create_reference_video_url_record(db: Session, job_id: int, video_url: str) -> JobFile:
    row = JobFile(
        job_id=job_id,
        file_type="reference_video_url",
        file_path=str(video_url),
        file_name="reference_video_url",
        file_size=None,
        mime_type="video/url",
        playable=False,
    )
    db.add(row)
    return row


def get_output_file(db: Session, job_id: int) -> JobFile | None:
    row = db.query(JobFile).filter(JobFile.job_id == job_id, JobFile.file_type == "output_video").first()
    if row and not Path(row.file_path).exists():
        return None
    return row


def create_output_file_record(db: Session, job_id: int, path: Path) -> JobFile:
    old = get_output_file(db, job_id)
    if old:
        db.delete(old)
        db.flush()
    meta = probe_media(path)
    create_video_poster(path)
    row = JobFile(
        job_id=job_id,
        file_type="output_video",
        file_path=str(path),
        file_name=path.name,
        file_size=meta.get("file_size"),
        mime_type=meta.get("mime_type"),
        duration_seconds=meta.get("duration_seconds"),
        width=meta.get("width"),
        height=meta.get("height"),
        playable=bool(meta.get("playable")),
    )
    db.add(row)
    return row


def output_path_for(job: Job) -> Path:
    return settings.files_output_dir / f"job_{job.id}_{job.remote_task_id or uuid.uuid4().hex}.mp4"


def get_reference_path(db: Session, job_id: int) -> Path | None:
    row = db.query(JobFile).filter(JobFile.job_id == job_id, JobFile.file_type == "reference_image").first()
    return Path(row.file_path) if row else None


def get_reference_url(db: Session, job_id: int) -> str | None:
    urls = get_reference_urls(db, job_id)
    return urls[0] if urls else None


def get_reference_urls(db: Session, job_id: int) -> list[str]:
    rows = (
        db.query(JobFile)
        .filter(JobFile.job_id == job_id, JobFile.file_type == "reference_image_url")
        .order_by(JobFile.id.asc())
        .all()
    )
    return [str(row.file_path).strip() for row in rows if row.file_path and str(row.file_path).strip()]


def get_reference_video_url(db: Session, job_id: int) -> str | None:
    row = db.query(JobFile).filter(JobFile.job_id == job_id, JobFile.file_type == "reference_video_url").first()
    return str(row.file_path).strip() if row and row.file_path else None


def normalize_request_id(request_id: str | uuid.UUID | None) -> uuid.UUID:
    if request_id is None:
        return uuid.uuid4()
    if isinstance(request_id, uuid.UUID):
        return request_id
    try:
        return uuid.UUID(str(request_id))
    except ValueError as exc:
        raise ValueError("request_id 无效") from exc


def stringify_failure_reason(value) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        parts: list[str] = []
        if value.get("code"):
            parts.append(str(value.get("code")))
        if value.get("message"):
            parts.append(str(value.get("message")))
        return " - ".join(parts) if parts else str(value)
    return str(value)


def is_retryable_failure(reason) -> bool:
    text = stringify_failure_reason(reason).lower()
    if not text:
        return False
    if any(hint in text for hint in NON_RETRYABLE_FAILURE_HINTS):
        return False
    return any(hint in text for hint in RETRYABLE_FAILURE_HINTS)



def _rate_limit_value(db: Session, user: User, field_name: str, default_key: str) -> int | None:
    value = getattr(user, field_name, None)
    if value is not None:
        try:
            parsed = int(value)
            return parsed if parsed > 0 else None
        except (TypeError, ValueError):
            return None
    parsed = get_system_setting_int(db, default_key, None)
    return parsed if parsed and parsed > 0 else None


def enforce_user_rate_limits(db: Session, user: User, additional_jobs: int = 1) -> None:
    additional_jobs = max(int(additional_jobs or 1), 1)
    if user.role != "user":
        return
    daily_limit = _rate_limit_value(db, user, "daily_job_limit", "default_daily_job_limit")
    # concurrent_job_limit 现在表示“同时生成数”，只由 worker 调度时控制。
    # 提交时不再因为该值拒绝创建；超出的任务会继续保持 queued 排队，避免用户被卡住。
    min_interval = _rate_limit_value(db, user, "min_submit_interval_seconds", "default_min_submit_interval_seconds")

    if daily_limit:
        start_utc, end_utc = date_bounds_utc(shanghai_now().date())
        today_count = int(
            db.query(func.count(Job.id))
            .filter(Job.user_id == user.id, Job.created_at >= start_utc, Job.created_at < end_utc)
            .scalar()
            or 0
        )
        if today_count + additional_jobs > daily_limit:
            raise ValueError(f"今日提交任务已达到上限 {daily_limit} 条，本次还需创建 {additional_jobs} 条")

    if min_interval:
        latest = db.query(Job.created_at).filter(Job.user_id == user.id).order_by(Job.id.desc()).first()
        if latest and latest[0]:
            last_time = latest[0]
            if last_time.tzinfo is None:
                last_time = last_time.replace(tzinfo=UTC)
            elapsed = (utcnow() - last_time).total_seconds()
            if elapsed < min_interval:
                wait_seconds = int(min_interval - elapsed) + 1
                raise ValueError(f"提交过于频繁，请 {wait_seconds} 秒后再试")


def make_batch_code(batch_uuid: uuid.UUID) -> str:
    return f"B{shanghai_now().strftime('%Y%m%d%H%M%S')}{str(batch_uuid).replace('-', '')[:6].upper()}"


def normalize_batch_name(value: str | None, prompts: list[str] | tuple[str, ...] | None = None) -> str | None:
    text = " ".join(str(value or "").split())
    if not text and prompts:
        first_prompt = next((str(item or "").strip() for item in prompts if str(item or "").strip()), "")
        text = " ".join(first_prompt.split())
    if not text:
        return None
    if len(text) > 128:
        return text[:125].rstrip() + "..."
    return text


def normalize_required_label(value: str | None, field_name: str, max_length: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"请填写{field_name}")
    if len(text) > max_length:
        raise ValueError(f"{field_name}最多 {max_length} 个字符")
    return text


def normalize_prompt_list(prompts: list[str] | tuple[str, ...], max_prompts: int = 100) -> list[str]:
    cleaned: list[str] = []
    for value in prompts or []:
        text = str(value or "").strip()
        if text:
            cleaned.append(text)
    if not cleaned:
        raise ValueError("请至少填写 1 条提示词")
    if len(cleaned) > max_prompts:
        raise ValueError(f"一次最多创建 {max_prompts} 条提示词任务")
    return cleaned


def create_jobs_batch_and_reserve(
    db: Session,
    user: User,
    provider_key: ProviderKey | None,
    prompts: list[str] | tuple[str, ...],
    seconds: int,
    size: str,
    reference_path: Path | None = None,
    reference_image_url: str | None = None,
    reference_video_url: str | None = None,
    reference_image_name: str | None = None,
    reference_width: int | None = None,
    reference_height: int | None = None,
    reference_images: list[tuple[str, str | None, int | None, int | None]] | None = None,
    batch_request_id: str | uuid.UUID | None = None,
    batch_name: str | None = None,
    product_name: str | None = None,
    region_name: str | None = None,
    model_id: str | None = None,
    risk_failure_messages: dict[int, str] | None = None,
) -> tuple[JobBatch, list[Job]]:
    """Create a traceable batch and multiple independent queued jobs.

    Each prompt becomes one job and reserves one quota. A stable batch_request_id
    makes the operation idempotent, so browser double-clicks do not create duplicates.
    """
    if provider_key and provider_is_retired(provider_key.provider_name):
        raise ValueError("该渠道已下线，请选择其他模型")
    if provider_key and normalize_provider_name(provider_key.provider_name) == "veo_omni" and reference_video_url:
        raise ValueError("VEO Omni 视频编辑已下线")
    cleaned_prompts = normalize_prompt_list(list(prompts))
    normalized_batch_name = normalize_batch_name(batch_name, cleaned_prompts)
    normalized_product_name = normalize_required_label(product_name, "APP名称")
    normalized_region_name = normalize_required_label(region_name, "地区")
    risk_failure_messages = risk_failure_messages or {}
    resolved_model_id = str(model_id or (provider_key.model_id if provider_key else None) or settings.default_video_model).strip()
    batch_uuid = normalize_request_id(batch_request_id)
    request_ids = [uuid.uuid5(uuid.NAMESPACE_URL, f"sora-batch:{user.id}:{batch_uuid}:{idx}") for idx, _ in enumerate(cleaned_prompts)]

    batch = db.query(JobBatch).filter(JobBatch.user_id == user.id, JobBatch.request_id == batch_uuid).first()
    if not batch:
        batch = JobBatch(
            user_id=user.id,
            request_id=batch_uuid,
            batch_code=make_batch_code(batch_uuid),
            batch_name=normalized_batch_name,
            product_name=normalized_product_name,
            region_name=normalized_region_name,
            total_count=len(cleaned_prompts),
        )
        db.add(batch)
        db.flush()
    else:
        batch.total_count = max(int(batch.total_count or 0), len(cleaned_prompts))
        if normalized_batch_name and batch.batch_name != normalized_batch_name:
            batch.batch_name = normalized_batch_name
        if batch.product_name != normalized_product_name:
            batch.product_name = normalized_product_name
        if batch.region_name != normalized_region_name:
            batch.region_name = normalized_region_name
        db.add(batch)
        db.flush()

    existing_jobs = (
        db.query(Job)
        .filter(Job.user_id == user.id, Job.request_id.in_(request_ids))
        .all()
    )
    existing_by_request_id = {job.request_id: job for job in existing_jobs}
    missing: list[tuple[int, str, uuid.UUID]] = []
    for idx, prompt in enumerate(cleaned_prompts):
        request_id = request_ids[idx]
        existing = existing_by_request_id.get(request_id)
        if existing:
            changed = False
            if existing.batch_id != batch.id:
                existing.batch_id = batch.id
                changed = True
            if existing.batch_index != idx + 1:
                existing.batch_index = idx + 1
                changed = True
            if existing.product_name != normalized_product_name:
                existing.product_name = normalized_product_name
                changed = True
            if existing.region_name != normalized_region_name:
                existing.region_name = normalized_region_name
                changed = True
            if changed:
                db.add(existing)
        else:
            missing.append((idx, prompt, request_id))

    if missing:
        normal_missing = [(idx, prompt, request_id) for idx, prompt, request_id in missing if idx not in risk_failure_messages]
        if normal_missing and not provider_key:
            raise ValueError("当前没有可用的对应渠道密钥")
        if normal_missing:
            enforce_user_rate_limits(db, user, additional_jobs=len(normal_missing))
        now = utcnow()
        for idx, prompt, request_id in missing:
            failure_message = risk_failure_messages.get(idx)
            job = Job(
                user_id=user.id,
                batch_id=batch.id,
                batch_index=idx + 1,
                provider_key_id=provider_key.id if provider_key else None,
                request_id=request_id,
                product_name=normalized_product_name,
                region_name=normalized_region_name,
                prompt=prompt,
                seconds=seconds,
                size=size,
                model=resolved_model_id,
                status="failed" if failure_message else "queued",
                progress=0,
                queued_at=None if failure_message else now,
                failed_at=now if failure_message else None,
                error_text=failure_message,
                submit_attempts=0,
            )
            db.add(job)
            db.flush()
            if reference_path:
                create_reference_file_record(db, job.id, reference_path)
            if reference_images:
                for image_url, image_name, image_width, image_height in reference_images:
                    create_reference_url_record(db, job.id, image_url, name=image_name, width=image_width, height=image_height)
            elif reference_image_url:
                create_reference_url_record(db, job.id, reference_image_url, name=reference_image_name, width=reference_width, height=reference_height)
            if reference_video_url:
                create_reference_video_url_record(db, job.id, reference_video_url)
            if failure_message:
                add_event(db, job.id, "error", "failed", failure_message)
            else:
                from app.services.quota_plans import reserve_quota_for_job

                reserve_quota_for_job(db, job)
                add_event(
                    db,
                    job.id,
                    "info",
                    "queued",
                    f"批量创建任务已进入队列（第 {idx + 1} 条 / 共 {len(cleaned_prompts)} 条）。",
                    {"batch_id": batch.id, "batch_code": batch.batch_code, "batch_index": idx + 1, "batch_total": len(cleaned_prompts)},
                )
    db.commit()

    refreshed_batch = db.query(JobBatch).filter(JobBatch.id == batch.id).first() or batch
    jobs = (
        db.query(Job)
        .filter(Job.user_id == user.id, Job.request_id.in_(request_ids))
        .order_by(Job.batch_index.asc().nullslast(), Job.id.asc())
        .all()
    )
    return refreshed_batch, jobs

def create_job_and_charge(
    db: Session,
    user: User,
    provider_key: ProviderKey,
    prompt: str,
    seconds: int,
    size: str,
    reference_path: Path | None = None,
    reference_image_url: str | None = None,
    reference_video_url: str | None = None,
    reference_image_name: str | None = None,
    reference_width: int | None = None,
    reference_height: int | None = None,
    reference_images: list[tuple[str, str | None, int | None, int | None]] | None = None,
    request_id: str | uuid.UUID | None = None,
    model_id: str | None = None,
) -> Job:
    """Create a local queued job and reserve one quota.

    The worker submits queued jobs to the upstream provider later. Existing name is
    kept so routes do not need to change. No upstream call happens in this web
    request, which avoids concurrent browser submissions blocking the web server.
    """
    normalized_request_id = normalize_request_id(request_id)
    existing_job = db.query(Job).filter(Job.user_id == user.id, Job.request_id == normalized_request_id).first()
    if existing_job:
        return existing_job

    if provider_is_retired(provider_key.provider_name):
        raise ValueError("该渠道已下线，请选择其他模型")
    if normalize_provider_name(provider_key.provider_name) == "veo_omni" and reference_video_url:
        raise ValueError("VEO Omni 视频编辑已下线")
    enforce_user_rate_limits(db, user)

    now = utcnow()
    job = Job(
        user_id=user.id,
        provider_key_id=provider_key.id,
        request_id=normalized_request_id,
        prompt=prompt,
        seconds=seconds,
        size=size,
        model=(str(model_id or provider_key.model_id or settings.default_video_model).strip()),
        status="queued",
        progress=0,
        queued_at=now,
        submit_attempts=0,
    )
    db.add(job)
    db.flush()
    if reference_path:
        create_reference_file_record(db, job.id, reference_path)
    if reference_images:
        for image_url, image_name, image_width, image_height in reference_images:
            create_reference_url_record(db, job.id, image_url, name=image_name, width=image_width, height=image_height)
    elif reference_image_url:
        create_reference_url_record(db, job.id, reference_image_url, name=reference_image_name, width=reference_width, height=reference_height)
    if reference_video_url:
        create_reference_video_url_record(db, job.id, reference_video_url)
    from app.services.quota_plans import reserve_quota_for_job

    reserve_quota_for_job(db, job)
    add_event(db, job.id, "info", "queued", "任务已进入队列。")
    db.commit()
    db.refresh(job)
    return job


def release_reserved_quota(db: Session, user_id: int) -> None:
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == user_id).with_for_update().first()
    if wallet and int(wallet.reserved_quota or 0) > 0:
        wallet.reserved_quota = int(wallet.reserved_quota or 0) - 1
        db.add(wallet)


def release_reserved_quota_for_job(db: Session, job: Job) -> None:
    from app.services.quota_plans import release_reserved_quota_for_job as release_package_or_personal

    if release_package_or_personal(db, job):
        return
    if job.status in {"queued", "submitting"} and not job.remote_task_id:
        release_reserved_quota(db, job.user_id)


def refund_failed_job_quota(db: Session, job: Job, reason: str | None = None) -> bool:
    """Refund one charged quota for a finally failed job, once per job."""
    from app.services.quota_plans import refund_charged_quota_for_job

    if refund_charged_quota_for_job(db, job, reason):
        return True
    if not job or not job.id:
        return False
    debited = (
        db.query(QuotaLedger.id)
        .filter(QuotaLedger.job_id == job.id, QuotaLedger.action == "debit_create_success")
        .first()
    )
    if not debited:
        return False
    refunded = (
        db.query(QuotaLedger.id)
        .filter(QuotaLedger.job_id == job.id, QuotaLedger.action == "refund_failed_job")
        .first()
    )
    if refunded:
        return False
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == job.user_id).with_for_update().first()
    if not wallet:
        wallet = QuotaWallet(user_id=job.user_id, remaining_quota=0, total_granted=0, total_used=0, reserved_quota=0)
        db.add(wallet)
        db.flush()
    wallet.remaining_quota = int(wallet.remaining_quota or 0) + 1
    wallet.total_used = max(int(wallet.total_used or 0) - 1, 0)
    db.add(wallet)
    db.add(
        QuotaLedger(
            user_id=job.user_id,
            job_id=job.id,
            change_amount=1,
            action="refund_failed_job",
            note=(reason or "Failed job quota refunded.")[:1000],
            operator_user_id=job.user_id,
        )
    )
    try:
        from app.models.tables import JobQuotaReservation

        reservation = db.query(JobQuotaReservation).filter(JobQuotaReservation.job_id == job.id, JobQuotaReservation.status == "charged").with_for_update().first()
        if reservation:
            reservation.status = "refunded"
            db.add(reservation)
    except Exception:
        pass
    add_event(db, job.id, "info", "quota_refunded", reason or "Failed job quota refunded.")
    return True


def queue_position(db: Session, job: Job) -> int | None:
    if job.status != "queued":
        return None
    q = db.query(Job.id).filter(Job.status == "queued")
    if job.queued_at is not None:
        q = q.filter((Job.queued_at < job.queued_at) | ((Job.queued_at == job.queued_at) & (Job.id <= job.id)))
    else:
        q = q.filter(Job.id <= job.id)
    return int(q.count() or 0)


def queue_text(db: Session, job: Job) -> str:
    if job.status == "queued":
        pos = queue_position(db, job)
        return f"排队第 {pos} 位" if pos else "排队中"
    if job.status in RUNNING_STATUSES:
        return "运行中"
    return "-"


def serialize_job(job: Job, output_file: JobFile | None = None, *, include_upstream_response: bool = False) -> dict:
    data = {
        "id": job.id,
        "user_id": job.user_id,
        "batch_id": job.batch_id,
        "batch_index": job.batch_index,
        "provider_key_id": job.provider_key_id,
        "remote_task_id": job.remote_task_id,
        "model": job.model,
        "product_name": job.product_name,
        "region_name": job.region_name,
        "prompt": job.prompt,
        "seconds": job.seconds,
        "size": job.size,
        "status": job.status,
        "status_label": status_label(job.status),
        "progress": job.progress,
        "error_text": job.error_text,
        "error_message": getattr(job, "error_message", None),
        "error_code": getattr(job, "error_code", None),
        "download_attempts": job.download_attempts,
        "submit_attempts": job.submit_attempts,
        "queued_at": format_shanghai_datetime_short(job.queued_at),
        "started_at": format_shanghai_datetime_short(job.started_at),
        "submitted_at": format_shanghai_datetime_short(job.submitted_at),
        "failed_at": format_shanghai_datetime_short(job.failed_at),
        "created_at": format_shanghai_datetime_short(job.created_at),
        "updated_at": format_shanghai_datetime_short(job.updated_at),
        "completed_at": format_shanghai_datetime_short(job.completed_at),
        "is_starred": bool(getattr(job, "is_starred", False)),
        "starred_at": format_shanghai_datetime_short(getattr(job, "starred_at", None)),
        "is_private_protected": bool(getattr(job, "is_private_protected", False)),
        "private_protected_at": format_shanghai_datetime_short(getattr(job, "private_protected_at", None)),
        "output_file": serialize_file(output_file) if output_file else None,
    }
    if include_upstream_response:
        data["upstream_response"] = getattr(job, "upstream_response", None)
    return data


def serialize_file(file: JobFile | None) -> dict | None:
    if not file:
        return None
    return {
        "id": file.id,
        "file_type": file.file_type,
        "file_name": file.file_name,
        "file_size": file.file_size,
        "mime_type": file.mime_type,
        "duration_seconds": str(file.duration_seconds) if file.duration_seconds is not None else None,
        "width": file.width,
        "height": file.height,
        "playable": file.playable,
    }


def serialize_event(event: JobEvent) -> dict:
    return {
        "id": event.id,
        "level": event.level,
        "event_type": event.event_type,
        "message": event.message,
        "payload_json": event.payload_json,
        "created_at": format_shanghai_datetime_short(event.created_at),
    }


def can_redownload(job: Job, output_file: JobFile | None) -> bool:
    return job.remote_task_id is not None and (
        job.status in REDOWNLOAD_ALLOWED or (job.status == "completed" and output_file is None)
    )


def can_resume(job: Job) -> bool:
    return job.remote_task_id is not None and job.status in RESUME_ALLOWED


def can_pause(job: Job) -> bool:
    return job.remote_task_id is not None and job.status in PAUSE_ALLOWED
