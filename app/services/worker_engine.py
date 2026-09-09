from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from sqlalchemy import func
from app.core.config import settings
from app.db import SessionLocal
from app.models.tables import Job, ProviderKey, User
from app.services.crypto import decrypt_secret
from app.services.jobs import add_event, refund_failed_job_quota
from app.services.system_settings import get_system_setting_int
from app.services.temp_cleanup import cleanup_library_bulk_zips
from app.services.quota_plans import refresh_due_packages

logger = logging.getLogger(__name__)

from app.services.worker_common import (
    ACTIVE_STATUSES,
    DOWNLOAD_STALE_SECONDS,
    GENERATION_RUNNING_STATUSES,
    PROCESS_WATCHDOG_SECONDS,
    _acquire_job_lock,
    _as_aware_utc,
    _dynamic_max_running_jobs,
    _has_remote_completed_event,
    _latest_event_at,
    _release_job_lock,
    _should_poll_remote_now,
    utcnow,
)
from app.services.worker_downloader import download_remote_job
from app.services.worker_poller import poll_remote
from app.services.worker_submitter import submit_queued_job
from app.services.worker_recovery import (
    complete_jobs_with_existing_output_files,
    force_due_content_fallback_jobs,
    mark_inflight_jobs_interrupted,
    recover_stale_downloading_jobs,
    recover_stale_submitting_jobs,
    touch_stale_polling_jobs,
)

SUBMIT_EXECUTOR = ThreadPoolExecutor(max_workers=max(16, int(settings.max_running_jobs)))
_SUBMIT_FUTURES: dict[object, int] = {}
PROCESS_EXECUTOR = ThreadPoolExecutor(max_workers=max(16, int(settings.max_running_jobs) * 4))
_PROCESS_FUTURES: dict[object, tuple[int, datetime]] = {}
_LAST_TEMP_CLEANUP_AT: datetime | None = None


def _cleanup_temp_files_periodically() -> None:
    global _LAST_TEMP_CLEANUP_AT
    now = utcnow()
    if _LAST_TEMP_CLEANUP_AT and (now - _LAST_TEMP_CLEANUP_AT).total_seconds() < 3600:
        return
    _LAST_TEMP_CLEANUP_AT = now
    removed = cleanup_library_bulk_zips(86400)
    if removed:
        logger.info("Removed %s stale library bulk zip files", removed)


def _cleanup_submit_futures() -> None:
    done = {future for future in _SUBMIT_FUTURES if future.done()}
    for future in done:
        job_id = _SUBMIT_FUTURES.pop(future, None)
        try:
            future.result()
        except Exception:
            logger.exception("Background submit worker crashed for job %s", job_id)


def _cleanup_process_futures() -> None:
    now = utcnow()
    for future, info in list(_PROCESS_FUTURES.items()):
        job_id, started_at = info
        if future.done():
            _PROCESS_FUTURES.pop(future, None)
            try:
                future.result()
            except Exception:
                logger.exception("Background job processor crashed for job %s", job_id)
            continue

        started_at = _as_aware_utc(started_at) or now
        elapsed = (now - started_at).total_seconds()
        watchdog_seconds = PROCESS_WATCHDOG_SECONDS
        try:
            with SessionLocal() as db:
                row = db.query(Job.status).filter(Job.id == int(job_id)).first()
                if row and row.status == "downloading":
                    watchdog_seconds = max(DOWNLOAD_STALE_SECONDS + 60, PROCESS_WATCHDOG_SECONDS)
        except Exception:
            watchdog_seconds = max(DOWNLOAD_STALE_SECONDS + 60, PROCESS_WATCHDOG_SECONDS)

        if elapsed > watchdog_seconds:
            _PROCESS_FUTURES.pop(future, None)
            logger.warning("Job %s processor exceeded watchdog %ss; allowing a new attempt", job_id, watchdog_seconds)
            try:
                with SessionLocal() as db:
                    job = db.query(Job).filter(Job.id == int(job_id)).first()
                    if job and job.status in {"submitted", "polling", "remote_completed", "download_waiting", "downloading"}:
                        latest = _latest_event_at(db, int(job.id), {"process_watchdog_released"})
                        latest = _as_aware_utc(latest) if latest else None
                        if latest is None or (now - latest).total_seconds() >= 30:
                            add_event(db, int(job.id), "warning", "process_watchdog_released", f"Process watchdog released stale worker after {int(watchdog_seconds)}s.")
                            db.commit()
            except Exception:
                logger.exception("Failed writing watchdog release event for job %s", job_id)


def _processing_job_ids() -> set[int]:
    return {job_id for job_id, _started_at in _PROCESS_FUTURES.values() if job_id is not None}


def _drop_process_futures_for_job(job_id: int) -> int:
    dropped = 0
    for future, info in list(_PROCESS_FUTURES.items()):
        active_job_id, _started_at = info
        if int(active_job_id) == int(job_id):
            _PROCESS_FUTURES.pop(future, None)
            dropped += 1
    return dropped


def _process_job_background(job_id: int) -> None:
    try:
        process_job(job_id)
    except Exception as exc:
        logger.exception("Failed processing job %s", job_id)
        try:
            with SessionLocal() as db:
                job = db.query(Job).filter(Job.id == job_id).first()
                if job and job.status in ACTIVE_STATUSES:
                    latest = _latest_event_at(db, job.id, {"worker_process_exception"})
                    now = utcnow()
                    latest = _as_aware_utc(latest) if latest else None
                    if latest is None or (now - latest).total_seconds() >= 30:
                        add_event(db, job.id, "warning", "worker_process_exception", f"Worker processing error: {str(exc)[:300]}")
                        db.commit()
        except Exception:
            logger.exception("Failed writing worker exception event for job %s", job_id)


def _submit_job_background(job_id: int) -> None:
    try:
        submit_queued_job(job_id)
    except Exception as exc:
        logger.exception("Failed submitting queued job %s", job_id)
        with SessionLocal() as db:
            job = db.query(Job).filter(Job.id == job_id).first()
            if job and job.status == "submitting" and not job.remote_task_id:
                job.status = "queued"
                job.started_at = None
                job.error_text = str(exc)[:1000]
                db.add(job)
                add_event(db, job.id, "warning", "submit_worker_error", f"Submit worker error: {str(exc)[:300]}")
                db.commit()









def _kick_remote_completed_downloads() -> None:
    _cleanup_process_futures()
    in_flight = _processing_job_ids()
    with SessionLocal() as db:
        job_ids = [
            int(job_id)
            for (job_id,) in (
                db.query(Job.id)
                .filter(Job.status.in_({"remote_completed", "download_waiting"}))
                .filter(Job.remote_task_id.isnot(None))
                .order_by(Job.updated_at.asc(), Job.id.asc())
                .limit(50)
                .all()
            )
            if int(job_id) not in in_flight
        ]
    for job_id in job_ids:
        if job_id in _processing_job_ids():
            continue
        future = PROCESS_EXECUTOR.submit(download_remote_job, int(job_id))
        _PROCESS_FUTURES[future] = (int(job_id), utcnow())


def _start_queued_jobs() -> None:
    _cleanup_submit_futures()
    already_scheduled = {int(job_id) for job_id in _SUBMIT_FUTURES.values()}
    with SessionLocal() as db:
        max_running = _dynamic_max_running_jobs(db)
        running = int(db.query(func.count(Job.id)).filter(Job.status.in_(GENERATION_RUNNING_STATUSES)).scalar() or 0)
        available = max(max_running - running - len(_SUBMIT_FUTURES), 0)
        if available <= 0:
            return
        running_by_user = {
            int(user_id): int(count or 0)
            for user_id, count in (
                db.query(Job.user_id, func.count(Job.id))
                .filter(Job.status.in_(GENERATION_RUNNING_STATUSES))
                .group_by(Job.user_id)
                .all()
            )
        }
        running_by_provider_key = {
            int(provider_key_id): int(count or 0)
            for provider_key_id, count in (
                db.query(Job.provider_key_id, func.count(Job.id))
                .filter(Job.status.in_(GENERATION_RUNNING_STATUSES))
                .filter(Job.provider_key_id.isnot(None))
                .group_by(Job.provider_key_id)
                .all()
            )
        }
        if already_scheduled:
            scheduled_by_user = (
                db.query(Job.user_id, func.count(Job.id))
                .filter(Job.id.in_(already_scheduled))
                .group_by(Job.user_id)
                .all()
            )
            for user_id, count in scheduled_by_user:
                running_by_user[int(user_id)] = running_by_user.get(int(user_id), 0) + int(count or 0)
            scheduled_by_provider_key = (
                db.query(Job.provider_key_id, func.count(Job.id))
                .filter(Job.id.in_(already_scheduled))
                .filter(Job.provider_key_id.isnot(None))
                .group_by(Job.provider_key_id)
                .all()
            )
            for provider_key_id, count in scheduled_by_provider_key:
                key = int(provider_key_id)
                running_by_provider_key[key] = running_by_provider_key.get(key, 0) + int(count or 0)
        default_user_limit = get_system_setting_int(db, "default_concurrent_job_limit", None)
        default_user_limit = int(default_user_limit or 0)

        candidates = (
            db.query(Job.id, Job.user_id, User.concurrent_job_limit, User.role, Job.provider_key_id, ProviderKey.concurrent_limit)
            .join(User, User.id == Job.user_id)
            .join(ProviderKey, ProviderKey.id == Job.provider_key_id)
            .filter(Job.status == "queued")
            .order_by(Job.queued_at.asc().nullsfirst(), Job.created_at.asc(), Job.id.asc())
            .limit(max(available * 20, 100))
            .all()
        )
        job_ids: list[int] = []
        for job_id, user_id, user_limit, role, provider_key_id, provider_limit in candidates:
            job_id = int(job_id)
            user_id = int(user_id)
            if job_id in already_scheduled:
                continue
            limit = int(user_limit or 0) if user_limit is not None else default_user_limit
            if role == "user" and limit > 0 and running_by_user.get(user_id, 0) >= limit:
                continue
            provider_key_id = int(provider_key_id)
            channel_limit = int(provider_limit or 0)
            if channel_limit > 0 and running_by_provider_key.get(provider_key_id, 0) >= channel_limit:
                continue
            job_ids.append(job_id)
            running_by_user[user_id] = running_by_user.get(user_id, 0) + 1
            running_by_provider_key[provider_key_id] = running_by_provider_key.get(provider_key_id, 0) + 1
            if len(job_ids) >= available:
                break
    for job_id in job_ids:
        future = SUBMIT_EXECUTOR.submit(_submit_job_background, int(job_id))
        _SUBMIT_FUTURES[future] = int(job_id)


def process_once() -> None:
    _cleanup_temp_files_periodically()
    try:
        with SessionLocal() as db:
            refreshed = refresh_due_packages(db)
            if refreshed:
                db.commit()
                logger.info("Refreshed %s due quota package assignments", refreshed)
    except Exception:
        logger.exception("Failed refreshing due quota package assignments")
    _cleanup_submit_futures()
    recover_stale_submitting_jobs()
    _cleanup_process_futures()
    complete_jobs_with_existing_output_files(_drop_process_futures_for_job)
    recover_stale_downloading_jobs(_drop_process_futures_for_job)
    force_due_content_fallback_jobs()
    touched_polling_job_ids = touch_stale_polling_jobs(_drop_process_futures_for_job)
    _start_queued_jobs()
    _kick_remote_completed_downloads()
    _cleanup_process_futures()

    in_flight = _processing_job_ids()
    with SessionLocal() as db:
        job_ids = [
            int(job_id)
            for (job_id,) in (
                db.query(Job.id)
                .filter(Job.status.in_(ACTIVE_STATUSES))
                .order_by(Job.updated_at.asc(), Job.id.asc())
                .limit(200)
                .all()
            )
        ]
    for job_id in job_ids:
        if job_id in in_flight or job_id in _processing_job_ids():
            continue
        future = PROCESS_EXECUTOR.submit(_process_job_background, int(job_id))
        _PROCESS_FUTURES[future] = (int(job_id), utcnow())
    for job_id in touched_polling_job_ids:
        if job_id in _processing_job_ids():
            continue
        future = PROCESS_EXECUTOR.submit(_process_job_background, int(job_id))
        _PROCESS_FUTURES[future] = (int(job_id), utcnow())


def process_job(job_id: int) -> None:
    should_download = False
    with SessionLocal() as db:
        if not _acquire_job_lock(db, job_id):
            return
        try:
            job = db.query(Job).filter(Job.id == job_id).first()
            if not job or job.status not in ACTIVE_STATUSES:
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

            if job.status in {"submitted", "polling"}:
                if _has_remote_completed_event(db, int(job.id)) or int(job.progress or 0) >= 100:
                    job.status = "remote_completed"
                    job.error_text = None
                    db.add(job)
                    add_event(db, job.id, "info", "remote_completed_resume_download", "Resuming download for completed upstream job.")
                    db.commit()
                    should_download = True
                else:
                    if not _should_poll_remote_now(db, job):
                        return
                    api_key = decrypt_secret(provider_key.key_encrypted)
                    poll_remote(db, job, provider_key, api_key)
                    fresh = db.query(Job.status, Job.progress).filter(Job.id == job_id).first()
                    if fresh and (str(fresh.status or "") == "remote_completed" or int(fresh.progress or 0) >= 100 or _has_remote_completed_event(db, job_id)):
                        should_download = True
            elif job.status in {"remote_completed", "download_waiting"}:
                should_download = True
            elif job.status == "downloading":
                return
        finally:
            _release_job_lock(db, job_id)

    if should_download:
        try:
            with SessionLocal() as db:
                job = db.query(Job).filter(Job.id == int(job_id)).first()
                if job and job.status in {"remote_completed", "download_waiting"}:
                    latest = _latest_event_at(db, int(job.id), {"download_handoff"})
                    latest = _as_aware_utc(latest) if latest else None
                    now = utcnow()
                    if latest is None or (now - latest).total_seconds() >= 20:
                        add_event(db, int(job.id), "info", "download_handoff", "Handing completed upstream job to downloader.")
                        db.commit()
        except Exception:
            logger.exception("Failed writing download handoff event for job %s", job_id)
        download_remote_job(job_id)


def schedule_job_now(job_id: int) -> bool:
    """Immediately schedule one job for processing from web/admin actions.

    This is intentionally best-effort. It fixes the case where a user clicks
    continue/re-download but the regular worker loop does not pick the job
    quickly because an old in-memory future still exists or the next loop is delayed.
    """
    try:
        _cleanup_process_futures()
        jid = int(job_id)
        # In this process, avoid launching duplicate processors for the same job.
        if jid in _processing_job_ids():
            return False
        future = PROCESS_EXECUTOR.submit(_process_job_background, jid)
        _PROCESS_FUTURES[future] = (jid, utcnow())
        return True
    except Exception:
        logger.exception("Failed to schedule job %s immediately", job_id)
        return False


def _download_remote(db, job: Job, provider_key=None, api_key: str | None = None) -> None:
    db.commit()
    download_remote_job(int(job.id))

