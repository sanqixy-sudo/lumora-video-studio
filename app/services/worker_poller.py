from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.tables import APICallLog, Job, ProviderKey
from app.services.jobs import add_event, refund_failed_job_quota, is_retryable_failure, stringify_failure_reason
from app.services.provider_keys import record_provider_key_failure, record_provider_key_success
from app.services.sora_api import UpstreamError, compact_json, extract_upstream_error, fetch_video_status, is_upstream_failure, raw_task_response, remote_content_url
from app.services.worker_common import (
    CONTENT_FALLBACK_RETRY_SECONDS,
    POLL_HEARTBEAT_SECONDS,
    POLL_START_EVENT_SECONDS,
    REMOTE_COMPLETED_STATUSES,
    REMOTE_PROCESSING_STATUSES,
    REMOTE_TERMINAL,
    _as_aware_utc,
    _content_fallback_after_seconds,
    _latest_event_at,
    _remote_elapsed_seconds,
    _should_try_content_fallback,
    utcnow,
)

def _maybe_add_poll_activity_event(db: Session, job: Job, previous_progress: int, remote_status: str) -> None:
    if job.progress != previous_progress:
        add_event(
            db,
            job.id,
            "info",
            "poll_progress",
            f"上游状态 {remote_status}；进度 {previous_progress}% -> {job.progress}%。",
            {"remote_status": remote_status, "progress": job.progress},
        )
        return

    latest_heartbeat = _latest_event_at(db, job.id, {"poll_heartbeat"})
    now = utcnow()
    latest_heartbeat = _as_aware_utc(latest_heartbeat) if latest_heartbeat else None
    if latest_heartbeat is None or now - latest_heartbeat >= timedelta(seconds=POLL_HEARTBEAT_SECONDS):
        add_event(
            db,
            job.id,
            "info",
            "poll_heartbeat",
            f"上游仍在处理；状态 {remote_status}，进度 {job.progress}%。",
            {"remote_status": remote_status, "progress": job.progress},
        )


def _maybe_add_poll_request_event(db: Session, job: Job) -> None:
    latest = _latest_event_at(db, int(job.id), {"poll_request_started"})
    now = utcnow()
    latest = _as_aware_utc(latest) if latest else None
    if latest is None or (now - latest).total_seconds() >= POLL_START_EVENT_SECONDS:
        add_event(db, job.id, "info", "poll_request_started", "正在查询上游任务状态。")
        db.commit()

def poll_remote(db: Session, job: Job, provider_key: ProviderKey, api_key: str) -> None:
    provider_key_id = provider_key.id
    previous_progress = int(job.progress or 0)
    endpoint = remote_content_url(job.remote_task_id, provider_key.api_base_url, provider_key.provider_name)
    _maybe_add_poll_request_event(db, job)
    try:
        data, status_code, latency_ms = fetch_video_status(api_key, job.remote_task_id, provider_key.api_base_url, provider_key.provider_name)
    except UpstreamError as exc:
        provider_key = db.query(ProviderKey).filter(ProviderKey.id == provider_key_id).with_for_update().first()
        if provider_key:
            record_provider_key_failure(db, provider_key)
        db.add(
            APICallLog(
                user_id=job.user_id,
                job_id=job.id,
                provider_key_id=provider_key_id,
                endpoint=endpoint,
                method="GET",
                status_code=exc.status_code,
                success=False,
                error_text=str(exc),
                response_summary=(exc.payload or "")[:2000],
            )
        )
        upstream_response = exc.upstream_response if isinstance(exc.upstream_response, dict) else None
        explicit_failure = bool(upstream_response and is_upstream_failure(upstream_response))
        transient_http = bool(exc.status_code is None or exc.status_code >= 500 or exc.status_code in {408, 409, 425, 429})
        if explicit_failure and not transient_http:
            error_message, error_code = extract_upstream_error(upstream_response)
            failure_reason = error_message or job.error_message or str(upstream_response.get("status") or "failed")
            job.status = "failed"
            job.failed_at = utcnow()
            job.error_message = failure_reason
            job.error_code = error_code
            job.upstream_response = upstream_response
            job.error_text = failure_reason
            db.add(job)
            add_event(db, job.id, "error", "remote_failed", f"Remote failed: {failure_reason}", upstream_response)
            refund_failed_job_quota(db, job, f"Remote failed: {failure_reason}")
        else:
            add_event(db, job.id, "warning", "poll_error", f"上游状态查询失败：{str(exc)[:300]}")
        db.commit()
        return

    try:
        raw_progress = data.get("progress")
        if raw_progress is None:
            remote_progress = previous_progress
        else:
            remote_progress = int(raw_progress)
    except (TypeError, ValueError):
        remote_progress = previous_progress
    job.progress = max(previous_progress, remote_progress)
    provider_key = db.query(ProviderKey).filter(ProviderKey.id == provider_key_id).with_for_update().first()
    if provider_key:
        record_provider_key_success(db, provider_key)
    db.add(
        APICallLog(
            user_id=job.user_id,
            job_id=job.id,
            provider_key_id=provider_key_id,
            endpoint=endpoint,
            method="GET",
            status_code=status_code,
            success=True,
            latency_ms=latency_ms,
            response_summary=compact_json(data),
        )
    )
    add_event(
        db,
        job.id,
        "info",
        "poll_response_received",
        f"已收到上游状态返回，耗时 {latency_ms}ms。",
        {"status_code": status_code, "latency_ms": latency_ms},
    )

    remote_status = str(data.get("status") or "unknown").lower()
    maybe_result_url = data.get("video_url") or data.get("url") or data.get("download_url")
    result_value = data.get("result") if isinstance(data, dict) else None
    if not maybe_result_url:
        if isinstance(result_value, str):
            maybe_result_url = result_value
        elif isinstance(result_value, list) and result_value:
            first = result_value[0]
            maybe_result_url = first if isinstance(first, str) else (first.get("url") or first.get("video_url") if isinstance(first, dict) else None)
    current_progress = int(job.progress or 0)
    if remote_status in REMOTE_PROCESSING_STATUSES and (current_progress >= 100 or maybe_result_url):
        remote_status = "completed"
        add_event(db, job.id, "info", "remote_status_override", f"Remote status was '{data.get('status')}' but progress={current_progress}% or result_url present, treating as completed.")

    if remote_status in REMOTE_PROCESSING_STATUSES:
        if _should_try_content_fallback(db, job, remote_status):
            job.status = "remote_completed"
            job.progress = max(int(job.progress or 0), previous_progress)
            job.error_text = None
            db.add(job)
            wait_seconds = _content_fallback_after_seconds(db)
            add_event(db, job.id, "info", "content_fallback", f"Fallback download after {wait_seconds}s without terminal status.", {"remote_status": remote_status, "wait_seconds": wait_seconds})
            db.commit()
            return
        if job.status != "polling":
            add_event(db, job.id, "info", "polling", "上游任务仍在生成中。")
        job.status = "polling"
        _maybe_add_poll_activity_event(db, job, previous_progress, remote_status)
        db.add(job)
        db.commit()
        return

    if remote_status in REMOTE_COMPLETED_STATUSES:
        job.status = "remote_completed"
        job.progress = 100
        job.error_text = None
        db.add(job)
        add_event(db, job.id, "info", "remote_completed", "上游任务已完成。", data)
        db.commit()
        return

    if remote_status in REMOTE_TERMINAL:
        upstream_response = raw_task_response(data)
        error_message, error_code = extract_upstream_error(upstream_response)
        failure_reason = error_message or job.error_message or remote_status
        job.status = "failed" if remote_status in {"failed", "error", "stopped", "cancelled", "canceled"} else remote_status
        job.failed_at = utcnow()
        job.error_message = failure_reason
        job.error_code = error_code
        job.upstream_response = upstream_response
        job.error_text = failure_reason
        db.add(job)
        if remote_status in {"failed", "error"} and is_retryable_failure(failure_reason):
            add_event(db, job.id, "warning", "remote_failed_retryable", f"Remote failed with retryable reason: {failure_reason}", upstream_response)
        else:
            add_event(db, job.id, "error", "remote_failed", f"Remote failed: {failure_reason}", upstream_response)
        refund_failed_job_quota(db, job, f"Remote failed: {failure_reason}")
        db.commit()
        return

    job.status = "polling"
    _maybe_add_poll_activity_event(db, job, previous_progress, remote_status)
    db.add(job)
    db.commit()
