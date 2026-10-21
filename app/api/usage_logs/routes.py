"""Task billing log shared by users and report administrators."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.core.timezone import SHANGHAI_TZ, format_shanghai_datetime, shanghai_now
from app.core.request_security import require_same_origin
from app.deps import get_current_user, get_db
from app.models.tables import Job, JobCost, JobEvent, JobFile, User


router = APIRouter(prefix="/usage-logs", tags=["usage-logs"])
PAGE_SIZE = 30
SUCCESS_STATUSES = {"remote_completed", "download_waiting", "downloading", "download_failed", "completed"}
FAILED_STATUSES = {"failed", "cancelled"}


def _money(amount: Decimal | None) -> str:
    if amount is None:
        return "—"
    value = f"{amount:.6f}".rstrip("0").rstrip(".")
    whole, dot, fraction = value.partition(".")
    return f"{whole}.{fraction.ljust(2, '0')}" if dot else f"{whole}.00"


def _time_filter(start: datetime, end: datetime):
    start_utc = start.astimezone(UTC)
    end_utc = (end + timedelta(minutes=1)).astimezone(UTC)
    task_time = func.coalesce(JobCost.upstream_completed_at, JobCost.created_at)
    return task_time >= start_utc, task_time < end_utc


def _scope(query, user: User):
    if user.role == "user":
        return query.filter(JobCost.source_user_id == user.id)
    if user.role == "sub_admin":
        hidden_ids = select(User.id).where(User.hidden_from_subadmin_reports.is_(True))
        return query.filter(JobCost.source_user_id.not_in(hidden_ids))
    if user.role == "admin":
        return query
    raise HTTPException(status_code=403, detail="无权查看使用日志")


def _billing_state(cost: JobCost, job: Job | None, remote_completed: bool) -> str:
    if cost.state == "settled":
        return "settled"
    if cost.state == "excluded":
        return "excluded"
    if remote_completed or cost.upstream_completed_at or (job and job.status in SUCCESS_STATUSES):
        return "success_pending"
    if job and job.status in FAILED_STATUSES:
        return "failed_pending"
    return "generating"


def _recheck_hint(cost: JobCost) -> str:
    if cost.last_error == "No task billing log yet":
        return "上游账单尚未同步，系统会继续自动核对。"
    if cost.last_error and cost.last_error.startswith("Billing lookup failed"):
        return "暂时无法读取上游账单，系统会自动重试。"
    return "若上游账单尚未同步，系统会继续自动核对。"


def _parse_times(start_value: str | None, end_value: str | None) -> tuple[datetime, datetime]:
    today = shanghai_now().date()
    default_start = datetime.combine(today.replace(day=1), time.min)
    default_end = datetime.combine(today, time(23, 59))

    def parse(value: str | None, fallback: datetime, *, is_end: bool) -> datetime:
        if not value:
            return fallback.replace(tzinfo=SHANGHAI_TZ)
        if len(value) == 10:
            parsed = datetime.combine(datetime.fromisoformat(value).date(), time(23, 59) if is_end else time.min)
        else:
            parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is not None:
            raise ValueError("time zone not allowed")
        return parsed.replace(second=0, microsecond=0, tzinfo=SHANGHAI_TZ)

    try:
        start = parse(start_value, default_start, is_end=False)
        end = parse(end_value, default_end, is_end=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="时间格式应为 YYYY-MM-DD HH:MM") from exc
    if start > end:
        raise HTTPException(status_code=422, detail="开始时间不能晚于结束时间")
    if end.year >= 9999:
        raise HTTPException(status_code=422, detail="结束时间超出可查询范围")
    return start, end


def _periods(now: datetime) -> list[dict[str, str]]:
    today = now.date()
    periods = (
        ("today", "今天", today, today),
        ("yesterday", "昨天", today - timedelta(days=1), today - timedelta(days=1)),
        ("week", "近 7 天", today - timedelta(days=6), today),
        ("month", "本月", today.replace(day=1), today),
    )
    return [
        {"key": key, "label": label, "start": f"{first:%Y-%m-%d}T00:00", "end": f"{last:%Y-%m-%d}T23:59"}
        for key, label, first, last in periods
    ]


@router.get("/page", response_class=HTMLResponse)
def usage_logs_page(
    request: Request,
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    user: str = Query(default="", max_length=100),
    task: str = Query(default="", max_length=128),
    page: int = Query(default=1, ge=1),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    start_time, end_time = _parse_times(start, end)
    user_query = user.strip() if current_user.role in {"admin", "sub_admin"} else ""
    task_query = task.strip()
    query = _scope(db.query(JobCost).filter(*_time_filter(start_time, end_time)), current_user)
    if user_query:
        user_match = JobCost.source_user_id == int(user_query) if user_query.isdecimal() else JobCost.username.ilike(f"%{user_query}%")
        query = query.filter(user_match)
    if task_query:
        escaped = task_query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        matches = [
            JobCost.remote_task_id.ilike(f"%{escaped}%", escape="\\"),
        ]
        if task_query.isdecimal():
            matches.append(JobCost.source_job_id == int(task_query))
        if len(task_query) >= 8:
            matches.append(cast(JobCost.source_logs, String).ilike(f"%{escaped}%", escape="\\"))
        query = query.filter(or_(*matches))
    total_count = query.count()
    settled_query = query.filter(JobCost.state == "settled")
    total_amount = settled_query.with_entities(func.sum(JobCost.amount)).scalar() or Decimal(0)
    settled_count = settled_query.count()
    pending_count = query.filter(JobCost.state == "pending").count()
    completed_job_ids = select(Job.id).where(Job.status.in_(SUCCESS_STATUSES))
    completed_event_ids = select(JobEvent.job_id).where(JobEvent.event_type == "remote_completed")
    success_pending_count = query.filter(
        JobCost.state == "pending",
        or_(JobCost.upstream_completed_at.isnot(None),
            JobCost.source_job_id.in_(completed_job_ids),
            JobCost.source_job_id.in_(completed_event_ids)),
    ).count()
    failed_job_ids = select(Job.id).where(Job.status.in_(FAILED_STATUSES))
    failed_pending_count = query.filter(
        JobCost.state == "pending",
        JobCost.source_job_id.in_(failed_job_ids),
        JobCost.source_job_id.not_in(completed_event_ids),
        JobCost.upstream_completed_at.is_(None),
    ).count()
    daily_records = (
        settled_query.with_entities(
            JobCost.usage_date,
            func.sum(JobCost.amount),
            func.count(JobCost.id),
        )
        .filter(JobCost.usage_date.is_not(None))
        .group_by(JobCost.usage_date)
        .order_by(JobCost.usage_date.desc())
        .limit(31).all()
    )
    daily_rows = [
        {"date": usage_date.isoformat(), "amount": _money(amount), "count": count}
        for usage_date, amount, count in daily_records
    ]
    total_pages = max(1, (total_count + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    costs = (
        query.order_by(func.coalesce(JobCost.upstream_completed_at, JobCost.created_at).desc(), JobCost.id.desc())
        .offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE).all()
    )
    job_ids = [cost.source_job_id for cost in costs]
    jobs_by_id = {job.id: job for job in db.query(Job).filter(Job.id.in_(job_ids)).all()} if job_ids else {}
    completed_event_ids_on_page = {row[0] for row in db.query(JobEvent.job_id).filter(
        JobEvent.job_id.in_(job_ids), JobEvent.event_type == "remote_completed").distinct().all()} if job_ids else set()
    prompt_by_job = {job_id: job.prompt for job_id, job in jobs_by_id.items()}
    display_states = {cost.source_job_id: _billing_state(cost, jobs_by_id.get(cost.source_job_id),
                      cost.source_job_id in completed_event_ids_on_page) for cost in costs}
    periods = _periods(shanghai_now())
    selected_start = start_time.strftime("%Y-%m-%dT%H:%M")
    selected_end = end_time.strftime("%Y-%m-%dT%H:%M")
    active_period = next((item["key"] for item in periods if item["start"] == selected_start and item["end"] == selected_end), None)
    return request.app.state.templates.TemplateResponse(
        request,
        "usage_logs/page.html",
        {
            "request": request,
            "current_user": current_user,
            "costs": costs,
            "prompt_by_job": prompt_by_job,
            "display_states": display_states,
            "start": selected_start,
            "end": selected_end,
            "periods": periods,
            "active_period": active_period,
            "user_query": user_query,
            "task_query": task_query,
            "can_filter_user": current_user.role in {"admin", "sub_admin"},
            "total_count": total_count,
            "settled_count": settled_count,
            "pending_count": pending_count,
            "success_pending_count": success_pending_count,
            "generating_count": max(0, pending_count - success_pending_count - failed_pending_count),
            "daily_rows": daily_rows,
            "total_amount": _money(total_amount),
            "page": page,
            "total_pages": total_pages,
            "money": _money,
        },
    )


@router.get("/{source_job_id}/detail", response_class=HTMLResponse)
def usage_log_detail(
    source_job_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    cost = _scope(db.query(JobCost).filter(JobCost.source_job_id == source_job_id), current_user).first()
    if cost is None:
        raise HTTPException(status_code=404, detail="日志不存在")
    job = db.query(Job).filter(Job.id == source_job_id).first()
    remote_completed = db.query(JobEvent.id).filter(
        JobEvent.job_id == source_job_id, JobEvent.event_type == "remote_completed").first() is not None
    display_state = _billing_state(cost, job, remote_completed)
    video = None
    if job is not None:
        video = (
            db.query(JobFile)
            .filter(JobFile.job_id == job.id, JobFile.file_type == "output_video")
            .order_by(JobFile.id.desc()).first()
        )
        if video is not None and not Path(video.file_path).is_file():
            video = None
    request_ids = list(dict.fromkeys(
        str(item.get("request_id")) for item in (cost.source_logs or [])
        if isinstance(item, dict) and item.get("request_id")
    ))
    return request.app.state.templates.TemplateResponse(
        request,
        "usage_logs/detail.html",
        {
            "request": request,
            "cost": cost,
            "job": job,
            "display_state": display_state,
            "can_recheck": current_user.role == "admin" and display_state == "success_pending",
            "recheck_hint": _recheck_hint(cost),
            "video": video,
            "request_ids": request_ids,
            "money": _money,
            "format_time": format_shanghai_datetime,
        },
    )


@router.post("/{source_job_id}/recheck", dependencies=[Depends(require_same_origin)])
def queue_billing_recheck(
    source_job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="只有管理员可重新核对计费")
    cost = db.query(JobCost).filter(JobCost.source_job_id == source_job_id).first()
    if cost is None:
        raise HTTPException(status_code=404, detail="日志不存在")
    job = db.query(Job).filter(Job.id == source_job_id).first()
    remote_completed = db.query(JobEvent.id).filter(
        JobEvent.job_id == source_job_id, JobEvent.event_type == "remote_completed").first() is not None
    if _billing_state(cost, job, remote_completed) != "success_pending":
        raise HTTPException(status_code=409, detail="当前任务无需重新核对")
    cost.next_check_at = datetime.now(UTC)
    db.add(cost)
    db.commit()
    return {"status": "queued", "message": "已加入计费核对队列"}
