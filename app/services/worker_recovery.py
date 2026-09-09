from __future__ import annotations

import logging
from datetime import timedelta

from app.core.config import settings
from app.db import SessionLocal
from app.models.tables import Job
from app.services.jobs import add_event, create_output_file_record, output_path_for
from app.services.worker_common import (
    DOWNLOAD_STALE_SECONDS,
    _acquire_job_lock,
    _as_aware_utc,
    _latest_event_at,
    _release_job_lock,
    _remote_elapsed_seconds,
    _remote_poll_interval_seconds,
    utcnow,
)

logger = logging.getLogger(__name__)


def mark_inflight_jobs_interrupted() -> None:
    with SessionLocal() as db:
        jobs = db.query(Job).filter(Job.status.in_({"submitting", "downloading"})).all()
        changed = 0
        for job in jobs:
            if job.status == "submitting" and not job.remote_task_id:
                job.status = "queued"
                job.started_at = None
                add_event(db, job.id, "warning", "worker_requeue", "Worker restarted; queued submitting job again.")
            elif job.status == "downloading" and job.remote_task_id:
                job.status = "remote_completed"
                add_event(db, job.id, "warning", "worker_requeue_download", "Worker restarted; download will be retried.")
            else:
                job.status = "interrupted"
                job.error_text = "Worker restarted before this job reached a recoverable state."
                add_event(db, job.id, "warning", "interrupted", job.error_text)
            db.add(job)
            changed += 1
        if changed:
            db.commit()
            logger.info("Recovered %s inflight jobs after worker start", changed)


def recover_stale_submitting_jobs() -> None:
    cutoff = utcnow() - timedelta(seconds=max(int(settings.sora_api_http_timeout or 120) + 60, 180))
    with SessionLocal() as db:
        jobs = (
            db.query(Job)
            .filter(Job.status == "submitting", Job.remote_task_id.is_(None), Job.started_at.isnot(None), Job.started_at < cutoff)
            .order_by(Job.started_at.asc())
            .limit(50)
            .all()
        )
        changed = 0
        for job in jobs:
            if not _acquire_job_lock(db, int(job.id)):
                continue
            try:
                job.status = "queued"
                job.started_at = None
                job.error_text = job.error_text or "Submitting timed out before upstream task id was returned."
                db.add(job)
                add_event(db, job.id, "warning", "submit_stale_requeued", "Stale submitting job requeued.")
                changed += 1
            finally:
                _release_job_lock(db, int(job.id))
        if changed:
            db.commit()


def force_due_content_fallback_jobs() -> None:
    return


def complete_jobs_with_existing_output_files(drop_process_futures_for_job) -> None:
    with SessionLocal() as db:
        jobs = (
            db.query(Job)
            .filter(Job.status.in_({"remote_completed", "download_waiting", "downloading"}), Job.remote_task_id.isnot(None))
            .order_by(Job.updated_at.asc(), Job.id.asc())
            .limit(100)
            .all()
        )
        changed = 0
        for job in jobs:
            if not _acquire_job_lock(db, int(job.id)):
                continue
            try:
                job = db.query(Job).filter(Job.id == int(job.id)).with_for_update().first()
                if not job or job.status not in {"remote_completed", "download_waiting", "downloading"}:
                    continue
                path = output_path_for(job)
                part_path = path.with_suffix(path.suffix + ".part")
                if path.exists() and path.stat().st_size > 0:
                    create_output_file_record(db, int(job.id), path)
                    old_status = job.status
                    job.status = "completed"
                    job.progress = 100
                    job.error_text = None
                    job.completed_at = utcnow()
                    db.add(job)
                    add_event(db, int(job.id), "info", "download_existing_file_completed", f"Existing output file completed job from {old_status}.", {"file_path": str(path), "file_size": path.stat().st_size})
                    drop_process_futures_for_job(int(job.id))
                    changed += 1
                elif part_path.exists() and part_path.stat().st_size > 0:
                    updated_at = _as_aware_utc(job.updated_at) or utcnow()
                    if (utcnow() - updated_at).total_seconds() > DOWNLOAD_STALE_SECONDS:
                        try:
                            part_path.unlink()
                        except Exception:
                            pass
            finally:
                _release_job_lock(db, int(job.id))
        if changed:
            db.commit()


def recover_stale_downloading_jobs(drop_process_futures_for_job) -> None:
    cutoff = utcnow() - timedelta(seconds=DOWNLOAD_STALE_SECONDS)
    with SessionLocal() as db:
        jobs = (
            db.query(Job)
            .filter(Job.status == "downloading", Job.updated_at.isnot(None), Job.updated_at < cutoff)
            .order_by(Job.updated_at.asc(), Job.id.asc())
            .limit(50)
            .all()
        )
        changed = 0
        for job in jobs:
            if not _acquire_job_lock(db, int(job.id)):
                continue
            try:
                job = db.query(Job).filter(Job.id == int(job.id)).with_for_update().first()
                if not job or job.status != "downloading":
                    continue
                latest_done = _latest_event_at(db, int(job.id), {"download_completed", "download_error", "download_failed"})
                latest_done = _as_aware_utc(latest_done) if latest_done else None
                updated_at = _as_aware_utc(job.updated_at) or utcnow()
                if latest_done and latest_done >= updated_at:
                    continue
                job.status = "remote_completed"
                job.error_text = "Download attempt timed out; retrying."
                job.download_attempts = max(int(job.download_attempts or 1) - 1, 0)
                db.add(job)
                dropped = drop_process_futures_for_job(int(job.id))
                add_event(db, int(job.id), "warning", "download_stale_retry", f"Download stale after {DOWNLOAD_STALE_SECONDS}s; retrying. Dropped futures: {dropped}.")
                changed += 1
            finally:
                _release_job_lock(db, int(job.id))
        if changed:
            db.commit()


def touch_stale_polling_jobs(drop_process_futures_for_job=None) -> list[int]:
    touched_job_ids: list[int] = []
    with SessionLocal() as db:
        jobs = (
            db.query(Job)
            .filter(Job.status.in_({"submitted", "polling"}), Job.remote_task_id.isnot(None))
            .order_by(Job.updated_at.asc(), Job.id.asc())
            .limit(100)
            .all()
        )
        changed = 0
        for job in jobs:
            interval = _remote_poll_interval_seconds(job)
            last_poll = _latest_event_at(db, int(job.id), {"poll_request_started", "poll_response_received", "poll_heartbeat", "poll_progress", "poll_error"})
            last_poll = _as_aware_utc(last_poll or job.updated_at or job.submitted_at or job.created_at)
            now = utcnow()
            if last_poll and (now - last_poll).total_seconds() < max(interval * 2, 60):
                continue
            latest_watchdog = _latest_event_at(db, int(job.id), {"poll_watchdog"})
            latest_watchdog = _as_aware_utc(latest_watchdog) if latest_watchdog else None
            if latest_watchdog and (now - latest_watchdog).total_seconds() < max(interval * 2, 60):
                continue
            add_event(
                db,
                job.id,
                "info",
                "poll_watchdog",
                f"超过 {max(interval * 2, 60)} 秒没有拿到新的上游状态，已提醒 worker 重新查询。",
                {"interval_seconds": interval, "elapsed_seconds": _remote_elapsed_seconds(job)},
            )
            if drop_process_futures_for_job is not None:
                drop_process_futures_for_job(int(job.id))
            touched_job_ids.append(int(job.id))
            changed += 1
        if changed:
            db.commit()
    return touched_job_ids

