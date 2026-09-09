from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.tables import APICallLog, Job, JobEvent
from app.services.jobs import add_event, utcnow
from app.services.sora_api import UpstreamError
from app.services.system_settings import get_system_setting_int, get_system_setting_text

RUNNING_STATUSES = {"submitting", "submitted", "polling", "remote_completed", "download_waiting", "downloading"}
# Only generation stages count against concurrency; download stages do not block new submissions.
GENERATION_RUNNING_STATUSES = {"submitting", "submitted", "polling"}
ACTIVE_STATUSES = {"submitted", "polling", "remote_completed", "download_waiting", "downloading"}
REMOTE_COMPLETED_STATUSES = {"completed", "complete", "succeeded", "success", "done"}
REMOTE_PROCESSING_STATUSES = {"pending", "queued", "in_progress", "processing", "running", "generating"}
REMOTE_TERMINAL = REMOTE_COMPLETED_STATUSES | {"failed", "error", "stopped", "cancelled", "canceled"}
CONTENT_FALLBACK_AFTER_SECONDS = 6000
CONTENT_FALLBACK_RETRY_SECONDS = 300
CONTENT_FALLBACK_ENABLED = True
POLL_START_EVENT_SECONDS = 30
# Poll less frequently as remote runtime grows.
REMOTE_POLL_SCHEDULE = (
    (0, 15),
    (600, 30),
    (1800, 60),
    (6000, 120),
)
PROCESS_WATCHDOG_SECONDS = max(45, int(getattr(settings, 'active_job_watchdog_seconds', 75) or 75))
DOWNLOAD_STALE_SECONDS = max(120, int(getattr(settings, 'download_stale_seconds', 180) or 180))


def _parse_download_retry_delays() -> list[int]:
    raw = str(settings.download_retry_delays_seconds or "0,15,30,60,120,180,300,600,900,1200")
    delays: list[int] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            delays.append(max(0, int(item)))
        except ValueError:
            continue
    return delays or [0, 15, 30, 60, 120, 180, 300, 600, 900, 1200]


DOWNLOAD_RETRY_DELAYS = _parse_download_retry_delays()
POLL_HEARTBEAT_SECONDS = 20


def _as_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _dynamic_max_running_jobs(db: Session) -> int:
    return max(1, int(get_system_setting_int(db, "max_running_jobs", settings.max_running_jobs) or settings.max_running_jobs))


def _dynamic_submit_max_attempts(db: Session) -> int:
    return max(1, int(get_system_setting_int(db, "submit_max_attempts", settings.submit_max_attempts) or settings.submit_max_attempts))


def _dynamic_download_retry_delays(db: Session) -> list[int]:
    raw = get_system_setting_text(db, "download_retry_delays_seconds", settings.download_retry_delays_seconds)
    delays: list[int] = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            delays.append(max(0, int(item)))
        except ValueError:
            continue
    return delays or DOWNLOAD_RETRY_DELAYS


def _remote_elapsed_seconds(job: Job) -> int:
    base = job.submitted_at or job.started_at or job.created_at
    base = _as_aware_utc(base)
    if not base:
        return 0
    return max(int((utcnow() - base).total_seconds()), 0)


def _content_fallback_after_seconds(db: Session) -> int:
    value = get_system_setting_int(db, "content_fallback_after_seconds", settings.content_fallback_after_seconds)
    return max(int(value or CONTENT_FALLBACK_AFTER_SECONDS), CONTENT_FALLBACK_AFTER_SECONDS)


def _remote_poll_interval_seconds(job: Job) -> int:
    """Return the dynamic upstream polling interval for a job."""
    elapsed = _remote_elapsed_seconds(job)
    interval = REMOTE_POLL_SCHEDULE[0][1]
    for threshold, seconds in REMOTE_POLL_SCHEDULE:
        if elapsed >= threshold:
            interval = seconds
        else:
            break
    return max(int(interval), 10)


def _latest_status_poll_at(db: Session, job: Job) -> datetime | None:
    if not job.remote_task_id:
        return None
    row = (
        db.query(APICallLog.created_at)
        .filter(APICallLog.job_id == int(job.id))
        .filter(APICallLog.method == "GET")
        .filter(APICallLog.endpoint.notlike("%/content%"))
        .order_by(APICallLog.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _maybe_add_poll_wait_event(db: Session, job: Job, interval: int, remaining: int) -> None:
    latest = _latest_event_at(db, int(job.id), {"poll_wait"})
    now = utcnow()
    latest = _as_aware_utc(latest) if latest else None
    if latest is not None and (now - latest).total_seconds() < 60:
        return
    add_event(
        db,
        int(job.id),
        "info",
        "poll_wait",
        f"距离下次上游状态查询还需等待 {remaining} 秒。",
        {"interval_seconds": interval, "remaining_seconds": remaining, "elapsed_seconds": _remote_elapsed_seconds(job)},
    )


def _latest_poll_watchdog_at(db: Session, job: Job) -> datetime | None:
    latest = _latest_event_at(db, int(job.id), {"poll_watchdog"})
    return _as_aware_utc(latest) if latest else None


def _should_poll_remote_now(db: Session, job: Job) -> bool:
    last_poll = _latest_status_poll_at(db, job)
    latest_watchdog = _latest_poll_watchdog_at(db, job)
    last_poll_aware = _as_aware_utc(last_poll) if last_poll else None
    if latest_watchdog and (last_poll_aware is None or latest_watchdog > last_poll_aware):
        return True
    if last_poll is None:
        return True
    now = utcnow()
    last_poll = last_poll_aware or now
    interval = _remote_poll_interval_seconds(job)
    elapsed = int((now - last_poll).total_seconds())
    if elapsed >= interval:
        return True
    _maybe_add_poll_wait_event(db, job, interval, max(interval - elapsed, 1))
    db.commit()
    return False


def _latest_content_fallback_event_at(db: Session, job_id: int) -> datetime | None:
    row = (
        db.query(JobEvent.created_at)
        .filter(JobEvent.job_id == job_id, JobEvent.event_type.in_({"content_fallback", "content_not_ready", "content_sweeper_fallback"}))
        .order_by(JobEvent.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _content_fallback_recently_attempted(db: Session, job: Job, now: datetime | None = None) -> bool:
    latest = _latest_content_fallback_event_at(db, int(job.id))
    if latest is None:
        return False
    now = now or utcnow()
    latest = _as_aware_utc(latest) or now
    return (now - latest).total_seconds() < CONTENT_FALLBACK_RETRY_SECONDS


def _fallback_started_before_min_poll(db: Session, job: Job) -> bool:
    """Return True when an old fallback moved a job to download too early."""
    if not job.remote_task_id:
        return False

    latest_fallback = _latest_event_at(db, int(job.id), {"content_fallback", "content_sweeper_fallback"})
    if latest_fallback is None:
        return False

    latest_true_completed = _latest_event_at(db, int(job.id), {"remote_completed"})
    latest_fallback = _as_aware_utc(latest_fallback)
    latest_true_completed = _as_aware_utc(latest_true_completed) if latest_true_completed else None
    if latest_true_completed:
        return False

    if CONTENT_FALLBACK_ENABLED and _remote_elapsed_seconds(job) >= _content_fallback_after_seconds(db):
        return False
    return True


def _should_try_content_fallback(db: Session, job: Job, remote_status: str) -> bool:
    if not CONTENT_FALLBACK_ENABLED:
        return False
    if not job.remote_task_id:
        return False
    if str(remote_status or "").lower() not in REMOTE_PROCESSING_STATUSES:
        return False
    if _remote_elapsed_seconds(job) < _content_fallback_after_seconds(db):
        return False
    return not _content_fallback_recently_attempted(db, job)


def _is_content_not_ready_error(exc: UpstreamError) -> bool:
    payload = str(exc.payload or "").lower()
    message = str(exc).lower()
    text_value = f"{message} {payload}"
    return (
        exc.status_code in {400, 404, 409, 425}
        and (
            "not completed" in text_value
            or "not ready" in text_value
            or "result url not ready" in text_value
            or "in_progress" in text_value
            or "queued" in text_value
            or "processing" in text_value
            or '"status":"processing"' in text_value.replace(" ", "")
        )
    )

def _acquire_job_lock(db: Session, job_id: int) -> bool:
    try:
        return bool(db.execute(text("SELECT pg_try_advisory_xact_lock(:job_id)"), {"job_id": int(job_id)}).scalar())
    except Exception:
        return True


def _release_job_lock(db: Session, job_id: int) -> None:
    return


def _latest_event_at(db: Session, job_id: int, event_types: set[str]) -> datetime | None:
    row = (
        db.query(JobEvent.created_at)
        .filter(JobEvent.job_id == job_id, JobEvent.event_type.in_(event_types))
        .order_by(JobEvent.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _has_remote_completed_event(db: Session, job_id: int) -> bool:
    return _latest_event_at(db, int(job_id), {"remote_completed"}) is not None


def _first_url_from_event_payload(value) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_url_from_event_payload(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("source_url", "video_url", "download_url", "url"):
            found = _first_url_from_event_payload(value.get(key))
            if found:
                return found
        for key in ("result", "data", "output", "files", "_raw"):
            found = _first_url_from_event_payload(value.get(key))
            if found:
                return found
    return None


def _latest_remote_completed_video_url(db: Session, job_id: int) -> str | None:
    """Find a usable video URL saved by polling, events, or API call logs."""
    def _clean_url(value: str | None) -> str | None:
        if not value:
            return None
        value = str(value).strip().strip('"\'<> ,;')
        if not value.startswith(('http://', 'https://')):
            return None
        lower = value.lower()
        if lower.startswith(("http://", "https://")):
            return value
        return None

    rows = (
        db.query(JobEvent.payload_json, JobEvent.message)
        .filter(JobEvent.job_id == int(job_id))
        .order_by(JobEvent.created_at.desc())
        .limit(80)
        .all()
    )
    for payload, message in rows:
        found = _clean_url(_first_url_from_event_payload(payload))
        if found:
            return found
        found = _clean_url(_first_url_from_event_payload(message))
        if found:
            return found

    call_rows = (
        db.query(APICallLog.response_summary, APICallLog.error_text, APICallLog.request_summary)
        .filter(APICallLog.job_id == int(job_id))
        .order_by(APICallLog.created_at.desc())
        .limit(80)
        .all()
    )
    for response_summary, error_text, request_summary in call_rows:
        for item in (response_summary, error_text, request_summary):
            found = _clean_url(_first_url_from_event_payload(item))
            if found:
                return found
    return None
