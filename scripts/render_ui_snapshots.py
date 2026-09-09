from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

from jinja2 import Environment, FileSystemLoader, select_autoescape


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = ROOT / "app" / "templates"
OUT_DIR = ROOT / "runtime" / "ui_snapshots"


class MockUrl:
    def __init__(self, path: str, query: dict[str, str] | None = None):
        self.path = path
        self.query = urlencode(query or {})
        self._query = dict(query or {})

    def include_query_params(self, **kwargs):
        query = {**self._query, **{k: str(v) for k, v in kwargs.items() if v is not None}}
        return MockUrl(self.path, query)

    def remove_query_params(self, keys):
        if isinstance(keys, str):
            keys = [keys]
        query = {k: v for k, v in self._query.items() if k not in set(keys)}
        return MockUrl(self.path, query)

    def __str__(self) -> str:
        return self.path + (f"?{self.query}" if self.query else "")


class QueryParams(dict):
    def multi_items(self):
        return list(self.items())


def ns(**kwargs):
    return SimpleNamespace(**kwargs)


def request(path: str, query: dict[str, str] | None = None):
    return ns(url=MockUrl(path, query), query_params=QueryParams(query or {}))


def role_label(role: str | None) -> str:
    return {"admin": "Admin", "sub_admin": "Sub Admin", "user": "User"}.get(str(role or ""), str(role or "-"))


def status_label(status: str | None) -> str:
    return {
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
    }.get(str(status or ""), str(status or "-"))


def user_display_name(user) -> str:
    if not user:
        return "-"
    return str(getattr(user, "display_name", "") or getattr(user, "username", "") or "-")


def dt(value):
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%m-%d %H:%M")
    return str(value)


now = datetime(2026, 6, 4, 16, 30)
admin = ns(id=1, username="admin", role="admin", status="active", showcase_enabled=True, created_at=now)
user = ns(id=2, username="creator01", role="user", status="active", showcase_enabled=True, created_at=now)
wallet = ns(remaining_quota=88, reserved_quota=3, total_used=42, total_granted=130)
jobs = [
    ns(
        id=101,
        user_id=2,
        batch_id=12,
        status="polling",
        progress=62,
        remote_task_id="task_abc123",
        model="sora-2-12s",
        product_name="NiceReels",
        region_name="菲律宾",
        size="720x1280",
        seconds=12,
        prompt="城市雨夜里，一位摄影师穿过霓虹街道，镜头缓慢推进，电影感，高级灰色调。",
        error_text=None,
        queue_text="运行中，第 1 位",
        download_attempts=0,
        created_at=now,
        updated_at=now,
        queued_at=now,
        started_at=now,
    ),
    ns(
        id=102,
        user_id=2,
        batch_id=12,
        status="completed",
        progress=100,
        remote_task_id="task_done456",
        model="sora-2-8s",
        product_name="ShopMate",
        region_name="泰国",
        size="1280x720",
        seconds=8,
        prompt="产品镜头沿金属边缘滑过，冷光、干净背景、浅景深。",
        error_text=None,
        queue_text="已完成",
        download_attempts=1,
        created_at=now,
        updated_at=now,
        queued_at=now,
        started_at=now,
    ),
]
job = jobs[0]
batch = ns(id=12, batch_code="B20260604-001", batch_name="NiceReels 竖屏广告", product_name="NiceReels", region_name="菲律宾", user_id=2, total_count=2, created_at=now)
pagination = {
    "page": 1,
    "per_page": 20,
    "total_items": 2,
    "total_pages": 1,
    "has_prev": False,
    "has_next": False,
}

common = {
    "now": now,
    "wallet": wallet,
    "jobs": jobs,
    "job": job,
    "output_file": ns(id=9, file_type="output_video", file_name="result.mp4", file_size=1234567),
    "events": [ns(created_at=now, message="Polling upstream status."), ns(created_at=now, message="Remote job is still processing.")],
    "files": [ns(file_type="output_video", file_name="result.mp4", file_size="12.4 MB")],
    "api_calls": [ns(id=1, method="GET", endpoint="/v1/video/status", status_code=200, success=True, latency_ms=380, request_summary="task_id=task_abc123", response_summary='{"status":"processing"}', error_text=None, created_at=dt(now))],
    "can_redownload": True,
    "can_resume": True,
    "can_pause": True,
    "can_manage": True,
    "remote_download_url": "/app/jobs/101/remote-download",
    "public_remote_download_url": "/app/jobs/101/public-remote-download?token=mock",
    "data_endpoint": "/app/jobs/101",
    "stats": ns(available=85, remaining=88, reserved=3, total_used=42, today_usage=5, running=2, max_running=3, queued=6, today_jobs=18, today_completed=11, download_failed_jobs=2, active_users=9, users=12, jobs=120, completed_jobs=94, failed_jobs=8, stuck=1, disabled=2, sub_admin=1, total=12, download_failed=2),
    "queue_stats": ns(running=2, max_running=3, queued=6),
    "queue_map": {101: "运行中，第 1 位", 102: "已完成"},
    "pagination": ns(**pagination),
    "page": 1,
    "total_pages": 1,
    "has_prev": False,
    "has_next": False,
    "rows": [],
    "batches": [batch],
    "batch": batch,
    "batch_jobs": jobs,
    "batch_map": {12: batch},
    "summary": {"total": 2, "state_class": "status-polling", "state_label": "进行中", "text": "1 运行中 / 1 已完成"},
    "summary_map": {12: {"total": 2, "state_class": "status-polling", "state_label": "进行中", "text": "1 运行中 / 1 已完成"}},
    "batch_summary_map": {12: {"total": 2, "state_class": "status-polling", "state_label": "进行中", "text": "1 运行中 / 1 已完成"}},
    "job_batch_map": {12: batch},
    "job_user_map": {2: user},
    "user_map": {2: user},
    "user_filter": "",
    "status_filter": "all",
    "status_tabs": [ns(key="all", label="全部", count=2, active=True), ns(key="running", label="运行中", count=1, active=False)],
    "reference_presets": [ns(id=1, name="竖屏人物", image_url="https://example.com/ref.png", width=720, height=1280, aspect_ratio="9:16", status="active", sort_order=1)],
    "supported_seconds": [8, 12],
    "new_request_id": "mock-request",
    "cards": [
        {"job_id": 102, "output_file_id": 9, "size": "1280x720", "seconds": 8, "product_name": "ShopMate", "region_name": "泰国", "prompt": jobs[1].prompt, "created_at": "2026-06-04 16:30", "created_date": "2026-06-04", "completed_at": "2026-06-04 16:35", "is_starred": True, "local_download_url": "/app/files/9/download"}
    ],
    "starred": False,
    "start_date": "",
    "end_date": "",
    "settings_rows": [ns(key="download_retry_delays_seconds", label="下载重试间隔秒", value="0,15,30,60", restart=False)],
    "registration_enabled": True,
    "subject": user,
    "user_stats": ns(jobs=12, completed=9, queued=1, running=1, today_usage=2, failed=1),
    "ledger": [],
    "calls": [],
    "audits": [],
    "filters": ns(q="", role="all", status="all"),
    "notice": "",
    "provider_keys": [ns(id=1, name="主线路", provider_name="sora_api", api_base_url="https://example.com", model_id="sora-2", model_id_4s=None, model_id_5s=None, model_id_8s="sora-2-8s", model_id_10s=None, model_id_12s="sora-2-12s", model_id_15s=None, key_masked="sk-***", status="active", weight=10, daily_limit=100, concurrent_limit=None, consecutive_failures=0, last_error_at=None, last_used_at=now)],
    "presets": [ns(id=1, name="竖屏人物", image_url="https://example.com/ref.png", width=720, height=1280, aspect_ratio="9:16", status="active", sort_order=1)],
    "failures": [ns(job=jobs[0], user=user, events=[ns(created_at=now, message="Download failed: upstream file not ready.")], calls=[])],
    "running_jobs": jobs[:1],
    "queued_jobs": jobs[1:],
    "stuck_jobs": [],
    "rankings": [ns(user_id=2, username="creator01", usage_count=18, success_count=14, failed_count=1, download_failure_count=1)],
    "period": "month",
    "period_label": "本月",
    "month": "2026-06",
    "prev_month": "2026-05",
    "next_month": "2026-07",
    "days": list(range(1, 8)),
    "usage_query": "",
    "hide_zero": False,
    "can_manage_usage": True,
    "real_total": 18,
    "display_total": 18,
    "override_count": 0,
    "groups": {"important": ns(label="重要记录"), "all": ns(label="全部记录")},
    "group": "important",
    "noise_count": 0,
    "quota_requests": [ns(id=1, user_id=2, amount=30, reason="新广告批次需要补充额度", status="pending", reviewer_user_id=None, review_note=None, reviewed_at=None, created_at=now, updated_at=now)],
    "counts": ns(pending=1, approved=0, rejected=0),
}

pages = [
    ("login.html", "/login", None, {"app_name": "流光 Lumora", "login_error": "", "login_notice": "", "prefill_username": "admin", "next_url": "", "registration_enabled": True}),
    ("app/dashboard.html", "/app", user, {}),
    ("app/jobs.html", "/app/jobs/page", user, {}),
    ("app/job_detail.html", "/app/jobs/101/page", user, {}),
    ("app/job_batches.html", "/app/job-batches/page", user, {}),
    ("app/job_batch_result.html", "/app/job-batches/12/result", user, {}),
    ("app/library.html", "/app/library/page", user, {}),
    ("app/plaza.html", "/app/plaza/page", user, {}),
    ("app/quota.html", "/app/quota/page", user, {}),
    ("app/guide.html", "/app/guide/page", user, {}),
    ("admin/dashboard.html", "/admin", admin, {}),
    ("admin/jobs.html", "/admin/jobs/page", admin, {}),
    ("admin/job_detail.html", "/admin/jobs/101/page", admin, {}),
    ("admin/job_batches.html", "/admin/job-batches/page", admin, {}),
    ("admin/queue.html", "/admin/queue/page", admin, {}),
    ("admin/users.html", "/admin/users/page", admin, {"rows": [(user, wallet)]}),
    ("admin/user_detail.html", "/admin/users/2/page", admin, {}),
    ("admin/provider_keys.html", "/admin/provider-keys/page", admin, {"rows": common["provider_keys"]}),
    ("admin/reference_images.html", "/admin/reference-images/page", admin, {"rows": common["presets"]}),
    ("admin/settings.html", "/admin/settings/page", admin, {}),
    ("admin/download_failures.html", "/admin/download-failures/page", admin, {"rows": common["failures"]}),
    ("admin/usage_monthly.html", "/admin/usage/monthly/page", admin, {"rows": [ns(user=user, monthly_display=18, monthly_real=18, daily=[{"date": f"2026-06-{day:02d}", "real": day % 3, "display": day % 3, "is_override": False, "note": ""} for day in range(1, 8)])]}),
    ("admin/rankings.html", "/admin/rankings/page", admin, {}),
    ("admin/quota_ledger.html", "/admin/quota-ledger/page", admin, {"rows": []}),
    ("admin/quota_requests.html", "/admin/quota-requests/page", admin, {"rows": common["quota_requests"], "status_filter": "pending"}),
    ("admin/api_calls.html", "/admin/api-call-logs/page", admin, {"rows": common["api_calls"]}),
    ("admin/audit_logs.html", "/admin/audit-logs/page", admin, {"rows": [ns(id=1, actor_label="admin", action_label="修改系统设置", action="update_system_settings", target_type="settings", target_id=None, detail_text="更新下载重试间隔", created_at=now)]}),
    ("errors/403.html", "/admin/settings/page", None, {"app_name": "流光 Lumora"}),
]


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )
    env.globals["status_label"] = status_label
    env.globals["role_label"] = role_label
    env.globals["user_display_name"] = user_display_name
    env.filters["dt"] = dt
    env.filters["dt_full"] = dt

    errors = []
    index_links = []
    for template_name, path, current_user, extra in pages:
        context = {**common, **extra, "request": request(path), "current_user": current_user}
        try:
            html = env.get_template(template_name).render(context)
        except Exception as exc:
            errors.append(f"{template_name}: {type(exc).__name__}: {exc}")
            continue
        out_name = template_name.replace("/", "__")
        out_path = OUT_DIR / out_name
        out_path.write_text(html, encoding="utf-8")
        index_links.append((template_name, out_name))

    index = ["<!doctype html><meta charset='utf-8'><title>UI Snapshots</title><h1>UI Snapshots</h1><ul>"]
    index.extend(f"<li><a href='{href}'>{name}</a></li>" for name, href in index_links)
    index.append("</ul>")
    (OUT_DIR / "index.html").write_text("\n".join(index), encoding="utf-8")

    if errors:
        raise SystemExit("UI_SNAPSHOT_ERRORS\n" + "\n".join(errors))
    print(f"UI_SNAPSHOTS_OK {OUT_DIR}")


if __name__ == "__main__":
    main()
