from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import SessionLocal
from app.models.tables import APICallLog, Job, ProviderKey
from app.services.crypto import decrypt_secret
from app.services.jobs import add_event, get_reference_path, get_reference_url, get_reference_urls, get_reference_video_url, release_reserved_quota_for_job
from app.services.provider_keys import record_provider_key_failure, record_provider_key_success
from app.services.quota_plans import charge_reserved_quota
from app.services.sora_api import (
    UpstreamError,
    compact_json,
    create_video,
    create_video_endpoint,
    create_video_request_summary,
    extract_upstream_error,
    is_upstream_failure,
    raw_task_response,
)
from app.services.worker_common import _acquire_job_lock, _dynamic_submit_max_attempts, _release_job_lock, utcnow

def _fail_submit(
    db: Session,
    job: Job,
    provider_key: ProviderKey | None,
    message: str,
    retryable: bool,
    *,
    error_code: str | None = None,
    upstream_response: object | None = None,
) -> None:
    attempts = int(job.submit_attempts or 0)
    max_attempts = _dynamic_submit_max_attempts(db)
    job.error_text = message
    job.error_message = message if upstream_response is not None else job.error_message
    job.error_code = error_code if upstream_response is not None else job.error_code
    job.upstream_response = upstream_response if upstream_response is not None else job.upstream_response
    if retryable and attempts < max_attempts:
        job.status = "queued"
        job.started_at = None
        db.add(job)
        add_event(db, job.id, "warning", "submit_retry", f"Submit failed; retrying: {message}")
        db.commit()
        return
    release_reserved_quota_for_job(db, job)
    job.status = "failed"
    job.failed_at = utcnow()
    db.add(job)
    add_event(db, job.id, "error", "submit_failed", f"Submit failed: {message}")
    db.commit()


def submit_queued_job(job_id: int) -> None:
    with SessionLocal() as db:
        if not _acquire_job_lock(db, job_id):
            return
        try:
            job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
            if not job or job.status != "queued":
                return
            provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).with_for_update().first()
            if not provider_key or provider_key.status != "active":
                _fail_submit(db, job, provider_key, "Provider key is missing or inactive.", retryable=False)
                return

            job.status = "submitting"
            job.started_at = utcnow()
            job.submit_attempts = int(job.submit_attempts or 0) + 1
            job.error_text = None
            job.error_message = None
            job.error_code = None
            job.upstream_response = None
            db.add(job)
            add_event(db, job.id, "info", "submitting", "Submitting job to upstream.")
            db.commit()

            api_key = decrypt_secret(provider_key.key_encrypted)
            api_base_url = provider_key.api_base_url
            provider_name = provider_key.provider_name
            model_id = job.model or provider_key.model_id or settings.default_video_model
            reference_path = get_reference_path(db, int(job.id))
            reference_image_urls = get_reference_urls(db, int(job.id))
            reference_image_url = reference_image_urls[0] if reference_image_urls else get_reference_url(db, int(job.id))
            reference_video_url = get_reference_video_url(db, int(job.id))
            request_summary = create_video_request_summary(
                job.prompt,
                job.seconds,
                job.size,
                reference_image_url,
                api_base_url,
                model_id,
                provider_name,
                reference_video_url,
                reference_image_urls=reference_image_urls,
            )
            endpoint = create_video_endpoint(api_base_url, provider_name)
            api_call = APICallLog(
                user_id=job.user_id,
                job_id=job.id,
                provider_key_id=provider_key.id,
                endpoint=endpoint,
                method="POST",
                request_summary=request_summary,
            )
            db.add(api_call)
            db.commit()

            try:
                data, status_code, latency_ms = create_video(
                    api_key,
                    job.prompt,
                    job.seconds,
                    job.size,
                    reference_path,
                    reference_image_url,
                    api_base_url,
                    model_id,
                    provider_name,
                    idempotency_key=str(job.request_id),
                    reference_video_url=reference_video_url,
                    reference_image_urls=reference_image_urls,
                )
            except UpstreamError as exc:
                api_call = db.query(APICallLog).filter(APICallLog.id == api_call.id).first()
                if api_call:
                    api_call.status_code = exc.status_code
                    api_call.success = False
                    api_call.latency_ms = exc.latency_ms
                    api_call.request_summary = exc.request_summary or request_summary
                    api_call.response_summary = exc.payload[:2000] if exc.payload else None
                    api_call.error_text = str(exc)
                    db.add(api_call)
                provider_key = db.query(ProviderKey).filter(ProviderKey.id == provider_key.id).with_for_update().first()
                if provider_key:
                    record_provider_key_failure(db, provider_key)
                retryable = bool(exc.status_code is None or exc.status_code >= 500 or exc.status_code in {408, 409, 425, 429})
                _fail_submit(
                    db,
                    job,
                    provider_key,
                    exc.error_message,
                    retryable=retryable,
                    error_code=exc.error_code,
                    upstream_response=exc.upstream_response,
                )
                return

            upstream_response = raw_task_response(data)
            if is_upstream_failure(data):
                error_message, error_code = extract_upstream_error(upstream_response)
                provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).with_for_update().first()
                if provider_key:
                    record_provider_key_failure(db, provider_key)
                api_call = db.query(APICallLog).filter(APICallLog.id == api_call.id).first()
                if api_call:
                    api_call.status_code = status_code
                    api_call.success = False
                    api_call.latency_ms = latency_ms
                    api_call.response_summary = json.dumps(upstream_response, ensure_ascii=False)
                    api_call.error_text = error_message
                    db.add(api_call)
                _fail_submit(
                    db,
                    job,
                    provider_key,
                    error_message or str(data.get("status") or "failed"),
                    retryable=False,
                    error_code=error_code,
                    upstream_response=upstream_response,
                )
                return

            remote_task_id = data.get("id") or data.get("task_id")
            if not remote_task_id:
                provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).with_for_update().first()
                if provider_key:
                    record_provider_key_failure(db, provider_key)
                api_call = db.query(APICallLog).filter(APICallLog.id == api_call.id).first()
                if api_call:
                    api_call.status_code = status_code
                    api_call.success = False
                    api_call.latency_ms = latency_ms
                    api_call.response_summary = compact_json(data)
                    api_call.error_text = "Missing remote task id."
                    db.add(api_call)
                error_message, error_code = extract_upstream_error(upstream_response)
                display_message = error_message or "Upstream response did not include remote task id."
                _fail_submit(
                    db,
                    job,
                    provider_key,
                    display_message,
                    retryable=False,
                    error_code=error_code,
                    upstream_response=upstream_response,
                )
                return

            job = db.query(Job).filter(Job.id == job.id).with_for_update().first()
            provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).with_for_update().first()
            job.remote_task_id = str(remote_task_id)
            job.model = str(data.get("model") or model_id)
            job.status = "submitted"
            job.progress = int(data.get("progress") or 0)
            job.submitted_at = utcnow()
            job.error_text = None
            try:
                charge_reserved_quota(db, job)
            except ValueError as exc:
                release_reserved_quota_for_job(db, job)
                job.status = "failed"
                job.failed_at = utcnow()
                job.error_text = str(exc)
                db.add(job)
                add_event(db, job.id, "error", "submit_failed", job.error_text)
                db.commit()
                return
            db.add(job)
            if provider_key:
                record_provider_key_success(db, provider_key)
            api_call = db.query(APICallLog).filter(APICallLog.id == api_call.id).first()
            if api_call:
                api_call.status_code = status_code
                api_call.success = True
                api_call.latency_ms = latency_ms
                api_call.response_summary = compact_json(data)
                api_call.error_text = None
                db.add(api_call)
            add_event(db, job.id, "info", "submitted", "Upstream task created.", {"remote_task_id": str(remote_task_id)})
            db.commit()
        finally:
            _release_job_lock(db, job_id)
