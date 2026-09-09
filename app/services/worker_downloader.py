from __future__ import annotations

import logging
from datetime import timedelta

from app.db import SessionLocal
from app.models.tables import APICallLog, Job, ProviderKey
from app.services.crypto import decrypt_secret
from app.services.jobs import add_event, create_output_file_record, output_path_for, refund_failed_job_quota
from app.services.provider_keys import record_provider_key_failure, record_provider_key_success
from app.services.sora_api import (
    UpstreamError,
    compact_json,
    download_video,
    extract_upstream_error,
    is_upstream_failure,
    raw_task_response,
)
from app.services.worker_common import (
    CONTENT_FALLBACK_RETRY_SECONDS,
    DOWNLOAD_STALE_SECONDS,
    _acquire_job_lock,
    _as_aware_utc,
    _dynamic_download_retry_delays,
    _fallback_started_before_min_poll,
    _has_remote_completed_event,
    _is_content_not_ready_error,
    _latest_event_at,
    _latest_remote_completed_video_url,
    _release_job_lock,
    _remote_elapsed_seconds,
    utcnow,
)

logger = logging.getLogger(__name__)

def download_remote_job(job_id: int) -> None:
    """Download a completed upstream video and finalize the job."""
    claim: dict | None = None
    with SessionLocal() as db:
        if not _acquire_job_lock(db, job_id):
            return
        try:
            job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
            if not job or job.status not in {"remote_completed", "download_waiting"}:
                return

            existing_path = output_path_for(job)
            if existing_path.exists() and existing_path.stat().st_size > 0:
                create_output_file_record(db, int(job.id), existing_path)
                job.status = "completed"
                job.progress = 100
                job.error_text = None
                job.completed_at = utcnow()
                db.add(job)
                add_event(db, job.id, "info", "completed", "Existing output file found; job completed.")
                db.commit()
                return

            if _fallback_started_before_min_poll(db, job):
                elapsed = _remote_elapsed_seconds(job)
                job.status = "polling"
                job.error_text = None
                db.add(job)
                add_event(db, job.id, "info", "fallback_guard_restore_polling", f"Fallback guard restored polling after {elapsed}s.", {"elapsed_seconds": elapsed, "fallback_disabled": True})
                db.commit()
                return

            provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).first()
            if not provider_key:
                job.status = "failed"
                job.failed_at = utcnow()
                job.error_text = "Provider key missing."
                db.add(job)
                add_event(db, job.id, "error", "provider_missing", "Provider key missing.")
                refund_failed_job_quota(db, job, job.error_text)
                db.commit()
                return

            if not job.remote_task_id:
                job.status = "failed"
                job.failed_at = utcnow()
                job.error_text = "Remote task id missing."
                db.add(job)
                add_event(db, job.id, "error", "download_missing_remote_id", "Remote task id missing.")
                refund_failed_job_quota(db, job, job.error_text)
                db.commit()
                return

            api_key = decrypt_secret(provider_key.key_encrypted)
            known_video_url = _latest_remote_completed_video_url(db, int(job.id))
            delays = _dynamic_download_retry_delays(db)
            attempt_index = int(job.download_attempts or 0)
            if attempt_index >= len(delays):
                job.status = "download_failed"
                job.failed_at = utcnow()
                if not job.error_text:
                    job.error_text = "Download retry attempts exhausted."
                db.add(job)
                add_event(db, job.id, "error", "download_failed", job.error_text)
                db.commit()
                return

            delay = 0 if (known_video_url or _has_remote_completed_event(db, int(job.id))) else delays[attempt_index]
            now = utcnow()
            if delay and job.updated_at is not None:
                next_retry_at = (_as_aware_utc(job.updated_at) or now) + timedelta(seconds=delay)
                if now < next_retry_at:
                    latest_wait_event = _latest_event_at(db, job.id, {"download_retry_wait"})
                    if job.status != "download_waiting":
                        job.status = "download_waiting"
                        db.add(job)
                    latest_wait_event = _as_aware_utc(latest_wait_event) if latest_wait_event else None
                    job_updated_at = _as_aware_utc(job.updated_at) or now
                    if latest_wait_event is None or latest_wait_event < job_updated_at:
                        remaining = max(int((next_retry_at - now).total_seconds()), 1)
                        add_event(db, job.id, "info", "download_retry_wait", f"Waiting {remaining}s before next download attempt.")
                    db.commit()
                    return

            job.status = "downloading"
            job.download_attempts = attempt_index + 1
            db.add(job)
            add_event(db, job.id, "info", "downloading", f"Download attempt {job.download_attempts}; watchdog {DOWNLOAD_STALE_SECONDS}s.")
            if known_video_url:
                add_event(db, job.id, "info", "download_source_url", f"Using upstream video url: {known_video_url[:260]}")
            else:
                add_event(db, job.id, "info", "download_source_url_missing", "No saved video_url/url was found; adapter will re-check status.")
            db.commit()
            claim = {
                "job_id": job.id,
                "user_id": job.user_id,
                "provider_key_id": provider_key.id,
                "remote_task_id": job.remote_task_id,
                "api_base_url": provider_key.api_base_url,
                "provider_name": provider_key.provider_name,
                "api_key": api_key,
                "dest": output_path_for(job),
                "known_video_url": known_video_url,
            }
        finally:
            _release_job_lock(db, job_id)

    if not claim:
        return

    try:
        meta, status_code, latency_ms = download_video(
            claim["api_key"],
            claim["remote_task_id"],
            claim["dest"],
            claim["api_base_url"],
            claim["provider_name"],
            known_video_url=claim.get("known_video_url"),
        )
    except UpstreamError as exc:
        with SessionLocal() as db:
            if not _acquire_job_lock(db, job_id):
                return
            try:
                job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
                if not job or job.remote_task_id != claim["remote_task_id"]:
                    return
                if job.status not in {"downloading", "remote_completed", "download_waiting"}:
                    add_event(db, job.id, "warning", "download_result_ignored", f"Ignoring download result for status {job.status}.")
                    db.commit()
                    return
                provider_key = db.query(ProviderKey).filter(ProviderKey.id == claim["provider_key_id"]).with_for_update().first()
                db.add(
                    APICallLog(
                        user_id=job.user_id,
                        job_id=job.id,
                        provider_key_id=claim["provider_key_id"],
                        endpoint=f"/videos/{claim['remote_task_id']}/content",
                        method="GET",
                        status_code=exc.status_code,
                        success=False,
                        error_text=str(exc),
                        response_summary=(exc.payload or "")[:2000],
                    )
                )

                upstream_response = exc.upstream_response if isinstance(exc.upstream_response, dict) else None
                if upstream_response and is_upstream_failure(upstream_response):
                    raw_response = raw_task_response(upstream_response)
                    error_message, error_code = extract_upstream_error(raw_response)
                    failure_reason = error_message or str(exc) or "Upstream task failed"
                    job.status = "failed"
                    job.failed_at = utcnow()
                    job.error_message = failure_reason
                    job.error_code = error_code or exc.error_code
                    job.upstream_response = raw_response
                    job.error_text = failure_reason
                    db.add(job)
                    if provider_key:
                        record_provider_key_failure(db, provider_key)
                    add_event(db, job.id, "error", "remote_failed", f"Remote failed during download: {failure_reason}", raw_response)
                    refund_failed_job_quota(db, job, f"Remote failed: {failure_reason}")
                    db.commit()
                    return

                if _is_content_not_ready_error(exc):
                    job.download_attempts = max(int(job.download_attempts or 1) - 1, 0)
                    job.status = "polling"
                    job.error_text = None
                    db.add(job)
                    add_event(db, job.id, "info", "content_not_ready", f"Content is not ready; returning to polling for {CONTENT_FALLBACK_RETRY_SECONDS}s.")
                    db.commit()
                    return

                delays = _dynamic_download_retry_delays(db)
                has_more_attempts = int(job.download_attempts or 0) < len(delays)
                job.status = "download_waiting" if has_more_attempts else "download_failed"
                if not has_more_attempts:
                    job.failed_at = utcnow()
                job.error_text = f"{exc} ({exc.status_code})" if exc.status_code else str(exc)
                db.add(job)
                if provider_key:
                    record_provider_key_failure(db, provider_key)
                payload_hint = (exc.payload or "")[:900]
                detail_suffix = f" Payload: {payload_hint}" if payload_hint else ""
                add_event(db, job.id, "warning", "download_error", f"Download failed: {job.error_text}.{detail_suffix}")
                if has_more_attempts:
                    retry_delay = delays[int(job.download_attempts or 0)] if int(job.download_attempts or 0) < len(delays) else 0
                    add_event(db, job.id, "info", "download_retry_pending", f"Next download retry in {retry_delay}s.")
                else:
                    refund_failed_job_quota(db, job, f"Download failed: {job.error_text}")
                db.commit()
                if job.status == "download_failed":
                    logger.warning("Job %s download failed permanently", job.id)
            finally:
                _release_job_lock(db, job_id)
        return

    with SessionLocal() as db:
        if not _acquire_job_lock(db, job_id):
            return
        try:
            job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
            if not job or job.remote_task_id != claim["remote_task_id"]:
                return
            if job.status not in {"downloading", "remote_completed", "download_waiting"}:
                add_event(db, job.id, "warning", "download_result_ignored", f"Ignoring successful download for status {job.status}.")
                db.commit()
                return
            provider_key = db.query(ProviderKey).filter(ProviderKey.id == claim["provider_key_id"]).with_for_update().first()
            create_output_file_record(db, int(job.id), claim["dest"])
            job.status = "completed"
            job.progress = 100
            job.error_text = None
            job.completed_at = utcnow()
            db.add(job)
            if provider_key:
                record_provider_key_success(db, provider_key)
            db.add(
                APICallLog(
                    user_id=job.user_id,
                    job_id=job.id,
                    provider_key_id=claim["provider_key_id"],
                    endpoint=f"/videos/{claim['remote_task_id']}/content",
                    method="GET",
                    status_code=status_code,
                    success=True,
                    latency_ms=latency_ms,
                    response_summary=compact_json(meta),
                )
            )
            add_event(db, job.id, "info", "completed", "Video downloaded and job completed.", meta)
            db.commit()
        finally:
            _release_job_lock(db, job_id)

