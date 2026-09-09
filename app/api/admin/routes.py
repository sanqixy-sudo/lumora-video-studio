from __future__ import annotations

import calendar
import io
import zipfile
from xml.sax.saxutils import escape
from datetime import UTC, date, datetime, timedelta
from math import ceil
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response, StreamingResponse
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.timezone import date_bounds_utc, format_shanghai_datetime, month_bounds_utc, shanghai_now
from app.deps import get_db, require_admin_or_subadmin, require_super_admin
from app.models.tables import (
    APICallLog,
    AppSetting,
    AuditLog,
    DailyUsageOverride,
    Job,
    JobBatch,
    JobEvent,
    JobFile,
    ProviderKey,
    PackageQuotaLedger,
    QuotaPlan,
    ReferenceImagePreset,
    RiskControlRule,
    QuotaLedger,
    QuotaRequest,
    QuotaWallet,
    User,
    UserQuotaPlanAssignment,
    UserProfile,
)
from app.schemas import AdminCreateProviderKeyRequest, AdminCreateUserRequest, AdminGrantQuotaRequest, AdminResetPasswordRequest
from app.services.audit import write_audit
from app.services.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.services.download_names import attachment_disposition, job_video_download_filename
from app.services.jobs import (
    RUNNING_STATUSES,
    can_pause,
    can_redownload,
    can_resume,
    get_output_file,
    queue_text,
    release_reserved_quota_for_job,
    serialize_event,
    serialize_job,
    make_public_remote_download_token,
    verify_public_remote_download_token,
)
from app.services.sora_api import UpstreamError, iter_video_stream, open_video_stream, normalize_api_base_url
from app.services.provider_keys import normalize_provider_name, provider_is_retired
from app.services.reference_images import aspect_ratio_for_dimensions, fetch_image_dimensions, normalize_public_image_url
from app.services.risk_control import parse_keywords
from app.services.quota_plans import PLAN_PERIOD_TYPES, bind_plan_to_user, deactivate_plan_assignments, plan_quota_amount, quota_totals_for_user, quota_totals_for_users, refresh_due_packages, refresh_user_packages, update_assignment_custom_quota
from app.services.user_admin import attach_display_names, create_user_with_wallet, deduct_quota, grant_quota, reset_user_password, set_user_display_name, set_user_role, set_user_showcase, set_user_status, user_display_name
from app.services.system_settings import get_system_setting_int, get_system_settings_view, upsert_system_setting

router = APIRouter(prefix="/admin", tags=["admin"])

FAILED_STATUSES = {"failed", "download_failed", "interrupted", "create_failed", "submit_failed", "remote_failed"}
AUDIT_NOISE_ACTIONS = {"queue_job"}
AUDIT_ACTION_LABELS = {
    "delete_job": "删除任务",
    "delete_job_batch": "删除批量记录",
    "delete_failed_jobs": "批量删除失败任务",
    "delete_stuck_jobs": "删除卡住任务",
    "delete_user": "删除用户",
    "set_user_status": "修改用户状态",
    "set_user_role": "修改用户角色",
    "reset_password": "重置密码",
    "grant_quota": "增加额度",
    "approve_quota_request": "通过额度申请",
    "reject_quota_request": "拒绝额度申请",
    "deduct_quota": "扣减额度",
    "update_user_rate_limits": "修改用户限速",
    "update_system_settings": "修改系统设置",
    "set_daily_usage_override": "修改日数量",
    "delete_daily_usage_override": "恢复日数量",
    "clear_api_call_logs": "清空调用日志",
    "create_provider_key": "创建密钥",
    "toggle_provider_key": "切换密钥状态",
    "update_provider_key": "修改密钥",
    "delete_provider_key": "删除密钥",
    "create_reference_image_preset": "创建参考图预设",
    "update_reference_image_preset": "修改参考图预设",
    "delete_reference_image_preset": "删除参考图预设",
    "set_user_showcase": "修改展示权限",
    "set_user_report_hidden": "修改报表隐藏",
    "create_risk_rule": "创建风控规则",
    "update_risk_rule": "修改风控规则",
    "toggle_risk_rule": "切换风控规则",
    "delete_risk_rule": "删除风控规则",
    "create_quota_plan": "创建套餐",
    "update_quota_plan": "修改套餐",
    "toggle_quota_plan": "切换套餐状态",
    "bind_quota_plan": "绑定套餐",
    "unbind_quota_plan": "解绑套餐",
    "update_user_quota_plan": "修改用户套餐",
    "cleanup_noise_audit_logs": "清理普通审计记录",
    "create_user": "创建用户",
}
AUDIT_GROUPS = {
    "important": {"label": "重要记录", "exclude_noise": True},
    "user": {"label": "用户操作", "actions": {"create_user", "delete_user", "set_user_status", "set_user_role", "reset_password", "grant_quota", "deduct_quota", "approve_quota_request", "reject_quota_request", "update_user_rate_limits", "set_user_showcase", "set_user_report_hidden", "bind_quota_plan", "unbind_quota_plan", "update_user_quota_plan"}},
    "job": {"label": "任务操作", "actions": {"delete_job", "delete_job_batch", "delete_failed_jobs", "delete_stuck_jobs"}},
    "system": {"label": "系统设置", "actions": {"update_system_settings", "clear_api_call_logs", "create_provider_key", "toggle_provider_key", "cleanup_noise_audit_logs", "update_provider_key", "delete_provider_key", "create_reference_image_preset", "update_reference_image_preset", "delete_reference_image_preset", "create_risk_rule", "update_risk_rule", "toggle_risk_rule", "delete_risk_rule", "create_quota_plan", "update_quota_plan", "toggle_quota_plan"}},
    "usage": {"label": "日数量", "actions": {"set_daily_usage_override", "delete_daily_usage_override"}},
    "all": {"label": "全部记录"},
}


def render(request: Request, template: str, **context):
    return request.app.state.templates.TemplateResponse(request, template, {"request": request, **context})


def _latest_job_event_at(db: Session, job_id: int, event_types: set[str]):
    row = (
        db.query(JobEvent.created_at)
        .filter(JobEvent.job_id == int(job_id), JobEvent.event_type.in_(event_types))
        .order_by(JobEvent.created_at.desc())
        .first()
    )
    return row[0] if row else None


def _has_confirmed_remote_completed(db: Session, job: Job) -> bool:
    """Return True once polling has confirmed the upstream task is complete."""
    return _latest_job_event_at(db, int(job.id), {"remote_completed"}) is not None


def _pagination(query, page: int, per_page: int):
    per_page = min(max(int(per_page or 20), 1), 100)
    total_items = int(query.order_by(None).count() or 0)
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    page = min(max(int(page or 1), 1), total_pages)
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }


def _parse_month(month: str | None) -> tuple[int, int]:
    if not month:
        now = shanghai_now()
        return now.year, now.month
    try:
        year_text, month_text = month.split("-", 1)
        year = int(year_text)
        month_num = int(month_text)
        if not 1 <= month_num <= 12:
            raise ValueError
        return year, month_num
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="月份格式应为 YYYY-MM") from exc


def _month_nav(year: int, month_num: int) -> dict:
    prev_year, prev_month = (year - 1, 12) if month_num == 1 else (year, month_num - 1)
    next_year, next_month = (year + 1, 1) if month_num == 12 else (year, month_num + 1)
    return {
        "month": f"{year:04d}-{month_num:02d}",
        "prev_month": f"{prev_year:04d}-{prev_month:02d}",
        "next_month": f"{next_year:04d}-{next_month:02d}",
        "days": list(range(1, calendar.monthrange(year, month_num)[1] + 1)),
    }


def _filter_usage_rows(data: dict, keyword: str | None, hide_zero: bool) -> dict:
    keyword = (keyword or "").strip().lower()
    rows = []
    for row in data["rows"]:
        username = str(row["user"].username or "")
        user_id = str(row["user"].id)
        if keyword and keyword not in username.lower() and keyword != user_id:
            continue
        if hide_zero and int(row["monthly_display"] or 0) == 0:
            continue
        rows.append(row)
    return _recompute_usage_totals({
        **data,
        "rows": rows,
        "display_total": sum(int(row["monthly_display"] or 0) for row in rows),
        "real_total": sum(int(row["monthly_real"] or 0) for row in rows),
        "filtered_user_count": len(rows),
    })


def _recompute_usage_totals(data: dict) -> dict:
    daily_totals = []
    for day_index, day in enumerate(data["days"]):
        real = 0
        display = 0
        for row in data["rows"]:
            item = row["daily"][day_index]
            real += int(item["real"] or 0)
            display += int(item["display"] or 0)
        daily_totals.append({"day": day, "real": real, "display": display})
    data["daily_totals"] = daily_totals
    data["real_total"] = sum(int(row["monthly_real"] or 0) for row in data["rows"])
    data["display_total"] = sum(int(row["monthly_display"] or 0) for row in data["rows"])
    return data


def _xlsx_col_name(index: int) -> str:
    name = ""
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _xlsx_cell(row_idx: int, col_idx: int, value) -> str:
    ref = f"{_xlsx_col_name(col_idx)}{row_idx}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = escape(str(value if value is not None else ""))
    return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'


def _build_usage_xlsx(data: dict) -> bytes:
    table_rows = [["用户", "合计", *[str(day) for day in data["days"]]]]
    daily_totals = data.get("daily_totals") or []
    if daily_totals:
        table_rows.append(["每日合计", data.get("display_total", 0), *[item["display"] for item in daily_totals]])
    for row in data["rows"]:
        table_rows.append([user_display_name(row["user"]), row["monthly_display"], *[item["display"] for item in row["daily"]]])

    row_xml = []
    for row_idx, values in enumerate(table_rows, start=1):
        cells = "".join(_xlsx_cell(row_idx, col_idx, value) for col_idx, value in enumerate(values, start=1))
        row_xml.append(f'<row r="{row_idx}">{cells}</row>')

    col_count = len(table_rows[0]) if table_rows else 1
    last_col = _xlsx_col_name(col_count)
    dimension = f"A1:{last_col}{max(len(table_rows), 1)}"
    cols_xml = '<cols><col min="1" max="1" width="22" customWidth="1"/><col min="2" max="2" width="12" customWidth="1"/><col min="3" max="64" width="8" customWidth="1"/></cols>'
    sheet_xml = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <dimension ref="{dimension}"/>
  <sheetViews><sheetView workbookViewId="0"><pane xSplit="2" ySplit="1" topLeftCell="C2" activePane="bottomRight" state="frozen"/></sheetView></sheetViews>
  {cols_xml}
  <sheetData>{"".join(row_xml)}</sheetData>
</worksheet>'''
    workbook_xml = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="日数量" sheetId="1" r:id="rId1"/></sheets></workbook>'''
    workbook_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'''
    root_rels = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'''
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", root_rels)
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        zf.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


def _usage_month_data(db: Session, year: int, month_num: int, hide_subadmin_hidden: bool = False) -> dict:
    start_utc, end_utc = month_bounds_utc(year, month_num)
    nav = _month_nav(year, month_num)
    start_date = date(year, month_num, 1)
    end_date = date(year, month_num, nav["days"][-1])

    user_query = db.query(User).filter(User.role == "user", User.status == "active")
    if hide_subadmin_hidden:
        user_query = user_query.filter(User.hidden_from_subadmin_reports.is_(False))
    users = user_query.order_by(User.id.asc()).all()
    attach_display_names(db, users)
    day_expr = func.date(func.timezone("Asia/Shanghai", QuotaLedger.created_at))
    debit_rows = (
        db.query(QuotaLedger.user_id, day_expr.label("usage_date"), func.count(QuotaLedger.id).label("count"))
        .filter(
            QuotaLedger.action == "debit_create_success",
            QuotaLedger.created_at >= start_utc,
            QuotaLedger.created_at < end_utc,
        )
        .group_by(QuotaLedger.user_id, day_expr)
        .all()
    )
    refund_rows = (
        db.query(QuotaLedger.user_id, day_expr.label("usage_date"), func.count(QuotaLedger.id).label("count"))
        .filter(
            QuotaLedger.action == "refund_failed_job",
            QuotaLedger.created_at >= start_utc,
            QuotaLedger.created_at < end_utc,
        )
        .group_by(QuotaLedger.user_id, day_expr)
        .all()
    )
    package_day_expr = func.date(func.timezone("Asia/Shanghai", PackageQuotaLedger.created_at))
    package_debit_rows = (
        db.query(PackageQuotaLedger.user_id, package_day_expr.label("usage_date"), func.count(PackageQuotaLedger.id).label("count"))
        .filter(
            PackageQuotaLedger.action == "package_debit_create_success",
            PackageQuotaLedger.created_at >= start_utc,
            PackageQuotaLedger.created_at < end_utc,
        )
        .group_by(PackageQuotaLedger.user_id, package_day_expr)
        .all()
    )
    package_refund_rows = (
        db.query(PackageQuotaLedger.user_id, package_day_expr.label("usage_date"), func.count(PackageQuotaLedger.id).label("count"))
        .filter(
            PackageQuotaLedger.action == "package_refund_failed_job",
            PackageQuotaLedger.created_at >= start_utc,
            PackageQuotaLedger.created_at < end_utc,
        )
        .group_by(PackageQuotaLedger.user_id, package_day_expr)
        .all()
    )
    real_counts: dict[tuple[int, date], int] = {}
    for user_id, usage_date, count in debit_rows:
        if isinstance(usage_date, datetime):
            usage_date = usage_date.date()
        real_counts[(int(user_id), usage_date)] = int(count or 0)
    for user_id, usage_date, count in package_debit_rows:
        if isinstance(usage_date, datetime):
            usage_date = usage_date.date()
        key = (int(user_id), usage_date)
        real_counts[key] = int(real_counts.get(key, 0)) + int(count or 0)
    for user_id, usage_date, count in refund_rows:
        if isinstance(usage_date, datetime):
            usage_date = usage_date.date()
        key = (int(user_id), usage_date)
        real_counts[key] = max(int(real_counts.get(key, 0)) - int(count or 0), 0)
    for user_id, usage_date, count in package_refund_rows:
        if isinstance(usage_date, datetime):
            usage_date = usage_date.date()
        key = (int(user_id), usage_date)
        real_counts[key] = max(int(real_counts.get(key, 0)) - int(count or 0), 0)

    visible_user_ids = [user.id for user in users]
    override_rows = []
    if visible_user_ids:
        override_rows = (
            db.query(DailyUsageOverride)
            .filter(
                DailyUsageOverride.user_id.in_(visible_user_ids),
                DailyUsageOverride.usage_date >= start_date,
                DailyUsageOverride.usage_date <= end_date,
            )
            .all()
        )
    overrides = {(row.user_id, row.usage_date): row for row in override_rows}

    rows = []
    real_total = 0
    display_total = 0
    for user in users:
        daily = []
        monthly_real = 0
        monthly_display = 0
        for day in nav["days"]:
            usage_date = date(year, month_num, day)
            real_count = real_counts.get((user.id, usage_date), 0)
            monthly_real += real_count
            override = overrides.get((user.id, usage_date))
            display_count = int(override.override_count) if override else real_count
            monthly_display += display_count
            daily.append(
                {
                    "day": day,
                    "date": usage_date.isoformat(),
                    "real": real_count,
                    "display": display_count,
                    "is_override": bool(override),
                    "note": override.note if override else None,
                }
            )
        real_total += monthly_real
        display_total += monthly_display
        rows.append(
            {
                "user": user,
                "daily": daily,
                "monthly_real": monthly_real,
                "monthly_display": monthly_display,
            }
        )
    return _recompute_usage_totals({**nav, "rows": rows, "real_total": real_total, "display_total": display_total, "override_count": len(overrides)})


def _real_usage_for_date(db: Session, user_id: int, usage_date: date) -> int:
    from app.core.timezone import date_bounds_utc

    start_utc, end_utc = date_bounds_utc(usage_date)
    debit_count = int(
        db.query(func.count(QuotaLedger.id))
        .filter(
            QuotaLedger.user_id == user_id,
            QuotaLedger.action == "debit_create_success",
            QuotaLedger.created_at >= start_utc,
            QuotaLedger.created_at < end_utc,
        )
        .scalar()
        or 0
    )
    refund_count = int(
        db.query(func.count(QuotaLedger.id))
        .filter(
            QuotaLedger.user_id == user_id,
            QuotaLedger.action == "refund_failed_job",
            QuotaLedger.created_at >= start_utc,
            QuotaLedger.created_at < end_utc,
        )
        .scalar()
        or 0
    )
    package_debit_count = int(
        db.query(func.count(PackageQuotaLedger.id))
        .filter(
            PackageQuotaLedger.user_id == user_id,
            PackageQuotaLedger.action == "package_debit_create_success",
            PackageQuotaLedger.created_at >= start_utc,
            PackageQuotaLedger.created_at < end_utc,
        )
        .scalar()
        or 0
    )
    package_refund_count = int(
        db.query(func.count(PackageQuotaLedger.id))
        .filter(
            PackageQuotaLedger.user_id == user_id,
            PackageQuotaLedger.action == "package_refund_failed_job",
            PackageQuotaLedger.created_at >= start_utc,
            PackageQuotaLedger.created_at < end_utc,
        )
        .scalar()
        or 0
    )
    return max(debit_count + package_debit_count - refund_count - package_refund_count, 0)


def _delete_job(db: Session, job: Job, actor: User, reason: str) -> None:
    release_reserved_quota_for_job(db, job)
    files = db.query(JobFile).filter(JobFile.job_id == job.id).all()
    for file in files:
        try:
            Path(file.file_path).unlink(missing_ok=True)
        except OSError:
            pass
        # Poster generated by media helper uses same stem with .jpg in most deployments.
        try:
            path = Path(file.file_path)
            path.with_suffix(".jpg").unlink(missing_ok=True)
        except OSError:
            pass
        db.delete(file)
    db.query(APICallLog).filter(APICallLog.job_id == job.id).update({APICallLog.job_id: None}, synchronize_session=False)
    db.query(QuotaLedger).filter(QuotaLedger.job_id == job.id).update({QuotaLedger.job_id: None}, synchronize_session=False)
    db.query(JobEvent).filter(JobEvent.job_id == job.id).delete(synchronize_session=False)
    write_audit(db, actor.id, "delete_job", "job", job.id, {"reason": reason, "status": job.status})
    db.delete(job)


def _stuck_filter(now: datetime):
    return or_(
        and_(Job.status == "queued", Job.updated_at < now - timedelta(hours=24)),
        and_(Job.status == "submitting", Job.updated_at < now - timedelta(minutes=10)),
        and_(Job.status == "submitted", Job.updated_at < now - timedelta(hours=2)),
        and_(Job.status == "polling", Job.updated_at < now - timedelta(hours=6)),
        and_(Job.status == "remote_completed", Job.updated_at < now - timedelta(hours=1)),
        and_(Job.status == "download_waiting", Job.updated_at < now - timedelta(hours=1)),
        and_(Job.status == "downloading", Job.updated_at < now - timedelta(minutes=30)),
    )


def _queue_stats(db: Session) -> dict:
    now = datetime.now(UTC)
    return {
        "running": int(db.query(func.count(Job.id)).filter(Job.status.in_(RUNNING_STATUSES)).scalar() or 0),
        "queued": int(db.query(func.count(Job.id)).filter(Job.status == "queued").scalar() or 0),
        "download_failed": int(db.query(func.count(Job.id)).filter(Job.status == "download_failed").scalar() or 0),
        "stuck": int(db.query(func.count(Job.id)).filter(_stuck_filter(now)).scalar() or 0),
        "max_running": get_system_setting_int(db, "max_running_jobs", settings.max_running_jobs) or settings.max_running_jobs,
    }


def _today_bounds() -> tuple[datetime, datetime]:
    return date_bounds_utc(shanghai_now().date())


def _net_usage_count(db: Session, start_utc: datetime, end_utc: datetime, user_id: int | None = None) -> int:
    filters = [QuotaLedger.created_at >= start_utc, QuotaLedger.created_at < end_utc]
    package_filters = [PackageQuotaLedger.created_at >= start_utc, PackageQuotaLedger.created_at < end_utc]
    if user_id is not None:
        filters.append(QuotaLedger.user_id == user_id)
        package_filters.append(PackageQuotaLedger.user_id == user_id)
    personal_debit = int(db.query(func.count(QuotaLedger.id)).filter(*filters, QuotaLedger.action == "debit_create_success").scalar() or 0)
    personal_refund = int(db.query(func.count(QuotaLedger.id)).filter(*filters, QuotaLedger.action == "refund_failed_job").scalar() or 0)
    package_debit = int(db.query(func.count(PackageQuotaLedger.id)).filter(*package_filters, PackageQuotaLedger.action == "package_debit_create_success").scalar() or 0)
    package_refund = int(db.query(func.count(PackageQuotaLedger.id)).filter(*package_filters, PackageQuotaLedger.action == "package_refund_failed_job").scalar() or 0)
    return max(personal_debit + package_debit - personal_refund - package_refund, 0)


def _net_usage_counts_by_user(db: Session, start_utc: datetime, end_utc: datetime) -> dict[int, int]:
    counts: dict[int, int] = {}
    for user_id, count in db.query(QuotaLedger.user_id, func.count(QuotaLedger.id)).filter(QuotaLedger.action == "debit_create_success", QuotaLedger.created_at >= start_utc, QuotaLedger.created_at < end_utc).group_by(QuotaLedger.user_id).all():
        counts[int(user_id)] = counts.get(int(user_id), 0) + int(count or 0)
    for user_id, count in db.query(PackageQuotaLedger.user_id, func.count(PackageQuotaLedger.id)).filter(PackageQuotaLedger.action == "package_debit_create_success", PackageQuotaLedger.created_at >= start_utc, PackageQuotaLedger.created_at < end_utc).group_by(PackageQuotaLedger.user_id).all():
        counts[int(user_id)] = counts.get(int(user_id), 0) + int(count or 0)
    for user_id, count in db.query(QuotaLedger.user_id, func.count(QuotaLedger.id)).filter(QuotaLedger.action == "refund_failed_job", QuotaLedger.created_at >= start_utc, QuotaLedger.created_at < end_utc).group_by(QuotaLedger.user_id).all():
        counts[int(user_id)] = max(counts.get(int(user_id), 0) - int(count or 0), 0)
    for user_id, count in db.query(PackageQuotaLedger.user_id, func.count(PackageQuotaLedger.id)).filter(PackageQuotaLedger.action == "package_refund_failed_job", PackageQuotaLedger.created_at >= start_utc, PackageQuotaLedger.created_at < end_utc).group_by(PackageQuotaLedger.user_id).all():
        counts[int(user_id)] = max(counts.get(int(user_id), 0) - int(count or 0), 0)
    return {user_id: count for user_id, count in counts.items() if count > 0}


def _parse_optional_date(value: str | date | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    value = str(value).strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日期格式应为 YYYY-MM-DD") from exc


def _audit_detail_text(detail: dict | None) -> str:
    if not detail:
        return "-"
    if not isinstance(detail, dict):
        return str(detail)
    labels = {
        "provider_key_id": "密钥ID",
        "count": "数量",
        "reason": "原因",
        "status": "状态",
        "username": "账号",
        "role": "角色",
        "old_role": "原角色",
        "amount": "额度",
        "note": "备注",
        "date": "日期",
        "download_retry_delays_seconds": "下载重试间隔秒",
        "public_download_token_ttl_seconds": "临时下载链接有效期秒",
        "max_running_jobs": "全站并发运行数",
        "submit_max_attempts": "提交上游最大重试",
        "default_daily_job_limit": "默认每日提交上限",
        "default_concurrent_job_limit": "默认同时生成数",
        "default_min_submit_interval_seconds": "默认提交间隔秒",
        "daily_job_limit": "每日提交上限",
        "concurrent_job_limit": "同时生成数",
        "min_submit_interval_seconds": "提交间隔秒",
        "showcase_enabled": "展示权限",
        "hidden_from_subadmin_reports": "子管理员报表隐藏",
        "keywords": "关键词",
        "plan_id": "套餐ID",
        "assignment_id": "绑定ID",
        "period_type": "周期",
        "quota_amount": "套餐额度",
        "custom_quota_amount": "定制额度",
        "unbound": "解绑数量",
    }
    parts = []
    for key, value in detail.items():
        label = labels.get(str(key), str(key))
        if value is None or value == "":
            text = "空"
        else:
            text = str(value)
        parts.append(f"{label}：{text}")
    return "；".join(parts) if parts else "-"


def _audit_display_rows(db: Session, rows: list[AuditLog]) -> list[dict]:
    actor_ids = [int(row.actor_user_id) for row in rows if row.actor_user_id]
    users = db.query(User).filter(User.id.in_(actor_ids)).all() if actor_ids else []
    user_map = {int(user.id): user for user in users}
    display_rows = []
    for row in rows:
        actor = user_map.get(int(row.actor_user_id)) if row.actor_user_id else None
        actor_label = f"{actor.username} / ID:{actor.id}" if actor else (f"ID:{row.actor_user_id}" if row.actor_user_id else "系统")
        display_rows.append({
            "id": row.id,
            "actor_label": actor_label,
            "action": row.action,
            "action_label": AUDIT_ACTION_LABELS.get(row.action, row.action),
            "target_type": row.target_type,
            "target_id": row.target_id,
            "detail_text": _audit_detail_text(row.detail_json),
            "created_at": row.created_at,
        })
    return display_rows


def _period_bounds(period: str, start_date: date | None = None, end_date: date | None = None) -> tuple[datetime, datetime, str]:
    now_cn = shanghai_now()
    if period == "custom" and start_date and end_date:
        start_utc, _ = date_bounds_utc(start_date)
        _, end_utc = date_bounds_utc(end_date)
        return start_utc, end_utc, f"{start_date.isoformat()} 至 {end_date.isoformat()}"
    if period == "today":
        start_utc, end_utc = date_bounds_utc(now_cn.date())
        return start_utc, end_utc, "今日"
    if period == "week":
        start_day = now_cn.date() - timedelta(days=now_cn.weekday())
        end_day = start_day + timedelta(days=6)
        start_utc, _ = date_bounds_utc(start_day)
        _, end_utc = date_bounds_utc(end_day)
        return start_utc, end_utc, "本周"
    year, month_num = now_cn.year, now_cn.month
    start_utc, end_utc = month_bounds_utc(year, month_num)
    return start_utc, end_utc, f"{year:04d}-{month_num:02d}"


def _download_failure_rows(db: Session, page: int, per_page: int):
    query = db.query(Job).filter(Job.status == "download_failed").order_by(Job.updated_at.desc(), Job.id.desc())
    paged = _pagination(query, page, per_page)
    user_map = _job_user_map(db, paged["items"])
    details = []
    for job in paged["items"]:
        events = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id.desc()).limit(12).all()
        calls = db.query(APICallLog).filter(APICallLog.job_id == job.id).order_by(APICallLog.id.desc()).limit(8).all()
        details.append({"job": job, "user": user_map.get(job.user_id), "events": events, "calls": calls, "queue_text": queue_text(db, job)})
    return paged, details


@router.get("", response_class=HTMLResponse)
def admin_dashboard_page(request: Request, current_user: User = Depends(require_admin_or_subadmin), db: Session = Depends(get_db)):
    if current_user.role == "sub_admin":
        return RedirectResponse("/admin/usage/monthly/page", status_code=303)
    today_start, today_end = _today_bounds()
    today_usage = _net_usage_count(db, today_start, today_end)
    stats = {
        "users": db.query(func.count(User.id)).filter(User.role == "user").scalar() or 0,
        "active_users": db.query(func.count(User.id)).filter(User.role == "user", User.status == "active").scalar() or 0,
        "jobs": db.query(func.count(Job.id)).scalar() or 0,
        "today_jobs": db.query(func.count(Job.id)).filter(Job.created_at >= today_start, Job.created_at < today_end).scalar() or 0,
        "today_completed": db.query(func.count(Job.id)).filter(Job.status == "completed", Job.completed_at >= today_start, Job.completed_at < today_end).scalar() or 0,
        "today_usage": today_usage,
        "completed_jobs": db.query(func.count(Job.id)).filter(Job.status == "completed").scalar() or 0,
        "failed_jobs": db.query(func.count(Job.id)).filter(Job.status.in_(FAILED_STATUSES)).scalar() or 0,
        "download_failed_jobs": db.query(func.count(Job.id)).filter(Job.status == "download_failed").scalar() or 0,
        "api_calls": db.query(func.count(APICallLog.id)).scalar() or 0,
        "provider_keys": db.query(func.count(ProviderKey.id)).scalar() or 0,
        **_queue_stats(db),
    }
    recent_jobs = db.query(Job).order_by(Job.id.desc()).limit(10).all()
    user_map = _job_user_map(db, recent_jobs)
    latest_failures = db.query(Job).filter(Job.status.in_(FAILED_STATUSES)).order_by(Job.updated_at.desc()).limit(8).all()
    return render(request, "admin/dashboard.html", current_user=current_user, stats=stats, jobs=recent_jobs, job_user_map=user_map, failures=latest_failures)


@router.get("/dashboard")
def dashboard_json(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    today_start, today_end = _today_bounds()
    today_usage = _net_usage_count(db, today_start, today_end)
    return {
        "users": db.query(func.count(User.id)).filter(User.role == "user").scalar() or 0,
        "active_users": db.query(func.count(User.id)).filter(User.role == "user", User.status == "active").scalar() or 0,
        "jobs": db.query(func.count(Job.id)).scalar() or 0,
        "today_jobs": db.query(func.count(Job.id)).filter(Job.created_at >= today_start, Job.created_at < today_end).scalar() or 0,
        "today_completed": db.query(func.count(Job.id)).filter(Job.status == "completed", Job.completed_at >= today_start, Job.completed_at < today_end).scalar() or 0,
        "download_failed_jobs": db.query(func.count(Job.id)).filter(Job.status == "download_failed").scalar() or 0,
        "today_usage": today_usage,
        **_queue_stats(db),
    }


@router.get("/usage/monthly/page", response_class=HTMLResponse)
def usage_monthly_page(
    request: Request,
    month: str | None = Query(default=None),
    q: str | None = Query(default=None),
    hide_zero: bool = Query(default=False),
    current_user: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    year, month_num = _parse_month(month)
    data = _filter_usage_rows(_usage_month_data(db, year, month_num, current_user.role == "sub_admin"), q, hide_zero)
    return render(
        request,
        "admin/usage_monthly.html",
        current_user=current_user,
        can_manage=current_user.role == "admin",
        usage_query=(q or "").strip(),
        hide_zero=hide_zero,
        **data,
    )


@router.get("/usage/monthly")
def usage_monthly_json(
    month: str | None = Query(default=None),
    q: str | None = Query(default=None),
    hide_zero: bool = Query(default=False),
    current_user: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    year, month_num = _parse_month(month)
    data = _filter_usage_rows(_usage_month_data(db, year, month_num, current_user.role == "sub_admin"), q, hide_zero)
    is_admin = current_user.role == "admin"
    rows = []
    for row in data["rows"]:
        item = {
            "user_id": row["user"].id,
            "username": row["user"].username,
            "monthly_display": row["monthly_display"],
            "daily": [{"day": d["day"], "date": d["date"], "display": d["display"]} for d in row["daily"]],
        }
        if is_admin:
            item["monthly_real"] = row["monthly_real"]
            item["daily"] = row["daily"]
        rows.append(item)
    payload = {"month": data["month"], "display_total": data["display_total"], "rows": rows}
    if is_admin:
        payload["real_total"] = data["real_total"]
        payload["override_count"] = data["override_count"]
    return payload


@router.get("/usage/monthly/export")
def usage_monthly_export(
    month: str | None = Query(default=None),
    q: str | None = Query(default=None),
    hide_zero: bool = Query(default=False),
    current_user: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    year, month_num = _parse_month(month)
    data = _filter_usage_rows(_usage_month_data(db, year, month_num, current_user.role == "sub_admin"), q, hide_zero)
    filename = f"usage_{data['month']}.xlsx"
    return Response(
        _build_usage_xlsx(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/usage/daily-override/form")
def save_daily_override_form(
    user_id: int = Form(...),
    usage_date: date = Form(...),
    override_count: int = Form(...),
    note: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if override_count < 0:
        raise HTTPException(status_code=400, detail="数量不能小于 0")
    user = db.query(User).filter(User.id == user_id, User.role == "user", User.status == "active").first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    real_count = _real_usage_for_date(db, user_id, usage_date)
    row = (
        db.query(DailyUsageOverride)
        .filter(DailyUsageOverride.user_id == user_id, DailyUsageOverride.usage_date == usage_date)
        .first()
    )
    if not row:
        row = DailyUsageOverride(user_id=user_id, usage_date=usage_date)
        db.add(row)
    row.override_count = override_count
    row.real_count_snapshot = real_count
    row.note = note or None
    row.operator_user_id = admin.id
    db.add(row)
    write_audit(db, admin.id, "set_daily_usage_override", "user", user_id, {"date": usage_date.isoformat(), "count": override_count})
    db.commit()
    return RedirectResponse(f"/admin/usage/monthly/page?month={usage_date:%Y-%m}", status_code=303)


@router.post("/usage/daily-override/delete/form")
def delete_daily_override_form(
    user_id: int = Form(...),
    usage_date: date = Form(...),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(DailyUsageOverride)
        .filter(DailyUsageOverride.user_id == user_id, DailyUsageOverride.usage_date == usage_date)
        .first()
    )
    if row:
        db.delete(row)
        write_audit(db, admin.id, "delete_daily_usage_override", "user", user_id, {"date": usage_date.isoformat()})
        db.commit()
    return RedirectResponse(f"/admin/usage/monthly/page?month={usage_date:%Y-%m}", status_code=303)


@router.get("/users/page", response_class=HTMLResponse)
def users_page(
    request: Request,
    q: str = Query(""),
    role: str = Query("all"),
    status: str = Query("all"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if refresh_due_packages(db, limit=500):
        db.commit()
    query = (
        db.query(User, QuotaWallet)
        .outerjoin(QuotaWallet, QuotaWallet.user_id == User.id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
    )
    keyword = (q or "").strip()
    if keyword:
        conditions = [User.username.ilike(f"%{keyword}%"), UserProfile.display_name.ilike(f"%{keyword}%")]
        if keyword.isdigit():
            conditions.append(User.id == int(keyword))
        query = query.filter(or_(*conditions))
    if role in {"user", "sub_admin", "admin"}:
        query = query.filter(User.role == role)
    if status in {"active", "disabled"}:
        query = query.filter(User.status == status)
    rows = query.order_by(User.id.desc()).all()
    attach_display_names(db, [user for user, _wallet in rows])
    quota_stats_by_user = quota_totals_for_users(
        db,
        [int(user.id) for user, _wallet in rows],
        {int(user.id): wallet for user, wallet in rows},
    )

    stats = {
        "total": db.query(func.count(User.id)).scalar() or 0,
        "active": db.query(func.count(User.id)).filter(User.status == "active").scalar() or 0,
        "disabled": db.query(func.count(User.id)).filter(User.status != "active").scalar() or 0,
        "sub_admin": db.query(func.count(User.id)).filter(User.role == "sub_admin").scalar() or 0,
    }
    notice_map = {
        "user_created": "用户已创建。",
        "quota_granted": "额度已增加。",
        "quota_deducted": "额度已扣减。",
        "status_updated": "用户状态已更新。",
        "user_deleted": "用户已删除。",
    }
    notice = notice_map.get(request.query_params.get("notice", ""))
    return render(
        request,
        "admin/users.html",
        current_user=admin,
        rows=rows,
        quota_stats_by_user=quota_stats_by_user,
        notice=notice,
        stats=stats,
        filters={"q": keyword, "role": role, "status": status},
    )


@router.get("/users")
def list_users(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[dict]:
    if refresh_due_packages(db, limit=500):
        db.commit()
    rows = db.query(User, QuotaWallet).outerjoin(QuotaWallet, QuotaWallet.user_id == User.id).order_by(User.id.desc()).all()
    attach_display_names(db, [user for user, _wallet in rows])
    quota_stats_by_user = quota_totals_for_users(
        db,
        [int(user.id) for user, _wallet in rows],
        {int(user.id): wallet for user, wallet in rows},
    )
    return [
        {
            "id": user.id,
            "username": user.username,
            "display_name": user_display_name(user),
            "role": user.role,
            "status": user.status,
            "hidden_from_subadmin_reports": bool(user.hidden_from_subadmin_reports),
            "remaining_quota": wallet.remaining_quota if wallet else 0,
            "reserved_quota": wallet.reserved_quota if wallet else 0,
            "available_quota": quota_stats_by_user[int(user.id)]["total_available"],
            "total_remaining_quota": quota_stats_by_user[int(user.id)]["total_remaining"],
            "total_reserved_quota": quota_stats_by_user[int(user.id)]["total_reserved"],
            "package_remaining_quota": quota_stats_by_user[int(user.id)]["package_remaining"],
            "package_available_quota": quota_stats_by_user[int(user.id)]["package_available"],
            "package_reserved_quota": quota_stats_by_user[int(user.id)]["package_reserved"],
            "personal_remaining_quota": quota_stats_by_user[int(user.id)]["personal_remaining"],
            "personal_available_quota": quota_stats_by_user[int(user.id)]["personal_available"],
            "personal_reserved_quota": quota_stats_by_user[int(user.id)]["personal_reserved"],
            "total_used": wallet.total_used if wallet else 0,
            "daily_job_limit": user.daily_job_limit,
            "concurrent_job_limit": user.concurrent_job_limit,
            "min_submit_interval_seconds": user.min_submit_interval_seconds,
        }
        for user, wallet in rows
    ]


@router.post("/users")
def create_user(payload: AdminCreateUserRequest, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    try:
        user = create_user_with_wallet(db, payload.username, payload.password, payload.role, payload.display_name)
        write_audit(db, admin.id, "create_user", "user", user.id, {"username": payload.username, "role": payload.role, "display_name": payload.display_name})
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"id": user.id, "username": user.username, "display_name": user_display_name(user), "role": user.role, "created_by": admin.username}


@router.post("/users/form")
def create_user_form(
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form("user"),
    display_name: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        user = create_user_with_wallet(db, username, password, role, display_name)
        write_audit(db, admin.id, "create_user", "user", user.id, {"username": username, "role": role, "display_name": display_name})
        db.commit()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse("/admin/users/page?notice=user_created", status_code=303)


@router.get("/users/{user_id}/page", response_class=HTMLResponse)
def user_detail_page(user_id: int, request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    if refresh_user_packages(db, int(user.id)):
        db.commit()
    attach_display_names(db, [user])
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == user.id).first()
    quota_stats = quota_totals_for_user(db, int(user.id), wallet)
    jobs = db.query(Job).filter(Job.user_id == user.id).order_by(Job.id.desc()).limit(30).all()
    calls = db.query(APICallLog).filter(APICallLog.user_id == user.id).order_by(APICallLog.id.desc()).limit(30).all()
    ledger = db.query(QuotaLedger).filter(QuotaLedger.user_id == user.id).order_by(QuotaLedger.id.desc()).limit(30).all()
    package_ledger = db.query(PackageQuotaLedger).filter(PackageQuotaLedger.user_id == user.id).order_by(PackageQuotaLedger.id.desc()).limit(30).all()
    package_rows = (
        db.query(UserQuotaPlanAssignment, QuotaPlan)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.user_id == user.id, UserQuotaPlanAssignment.status == "active")
        .order_by(UserQuotaPlanAssignment.id.asc())
        .all()
    )
    active_plans = db.query(QuotaPlan).filter(QuotaPlan.status == "active").order_by(QuotaPlan.id.desc()).all()
    assigned_plan_ids = {int(assignment.plan_id) for assignment, _plan in package_rows}
    available_plans = [plan for plan in active_plans if int(plan.id) not in assigned_plan_ids]
    audits = db.query(AuditLog).filter(AuditLog.actor_user_id == user.id).order_by(AuditLog.id.desc()).limit(30).all()
    today_start, today_end = _today_bounds()
    user_today_usage = _net_usage_count(db, today_start, today_end, int(user.id))
    user_stats = {
        "jobs": db.query(func.count(Job.id)).filter(Job.user_id == user.id).scalar() or 0,
        "completed": db.query(func.count(Job.id)).filter(Job.user_id == user.id, Job.status == "completed").scalar() or 0,
        "failed": db.query(func.count(Job.id)).filter(Job.user_id == user.id, Job.status.in_(FAILED_STATUSES)).scalar() or 0,
        "running": db.query(func.count(Job.id)).filter(Job.user_id == user.id, Job.status.in_(RUNNING_STATUSES)).scalar() or 0,
        "queued": db.query(func.count(Job.id)).filter(Job.user_id == user.id, Job.status == "queued").scalar() or 0,
        "today_usage": user_today_usage,
    }
    response = render(request, "admin/user_detail.html", current_user=admin, subject=user, wallet=wallet, quota_stats=quota_stats, jobs=jobs, calls=calls, ledger=ledger, package_ledger=package_ledger, package_rows=package_rows, available_plans=available_plans, audits=audits, user_stats=user_stats, plan_quota_amount=plan_quota_amount, notice={"showcase_on":"已开启广场公开","showcase_off":"已关闭广场公开"}.get(request.query_params.get("notice"), request.query_params.get("notice")))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return response


@router.post("/users/{user_id}/display-name/form")
def update_user_display_name_form(
    user_id: int,
    display_name: str = Form(""),
    return_to: str = Form("/admin/users/page"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    set_user_display_name(db, user, display_name, admin.id)
    db.commit()
    if not return_to.startswith("/admin/users"):
        return_to = "/admin/users/page"
    return RedirectResponse(return_to, status_code=303)


@router.post("/users/{user_id}/grant-quota")
def admin_grant_quota(user_id: int, payload: AdminGrantQuotaRequest, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    wallet = grant_quota(db, user, payload.amount, admin.id, payload.note)
    db.commit()
    return {"user_id": user.id, "remaining_quota": wallet.remaining_quota}


@router.post("/users/{user_id}/deduct-quota")
def admin_deduct_quota(user_id: int, payload: AdminGrantQuotaRequest, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    wallet = deduct_quota(db, user, payload.amount, admin.id, payload.note)
    db.commit()
    return {"user_id": user.id, "remaining_quota": wallet.remaining_quota}


@router.post("/users/{user_id}/grant-quota/form")
def admin_grant_quota_form(user_id: int, amount: int = Form(...), note: str = Form(""), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    grant_quota(db, user, amount, admin.id, note or None)
    db.commit()
    return RedirectResponse("/admin/users/page?notice=quota_granted", status_code=303)


@router.post("/users/{user_id}/deduct-quota/form")
def admin_deduct_quota_form(user_id: int, amount: int = Form(...), note: str = Form(""), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    deduct_quota(db, user, amount, admin.id, note or None)
    db.commit()
    return RedirectResponse("/admin/users/page?notice=quota_deducted", status_code=303)


@router.post("/users/{user_id}/quota-plans/bind/form")
def bind_user_quota_plan_form(user_id: int, plan_id: int = Form(...), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    plan = db.query(QuotaPlan).filter(QuotaPlan.id == plan_id, QuotaPlan.status == "active").first()
    if not user or not plan:
        raise HTTPException(status_code=404, detail="用户或套餐不存在")
    assignment = bind_plan_to_user(db, user, plan, admin.id)
    write_audit(db, admin.id, "bind_quota_plan", "user", user.id, {"plan_id": plan.id, "assignment_id": assignment.id})
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}/page#packages", status_code=303)


@router.post("/users/{user_id}/quota-plans/{assignment_id}/custom/form")
def update_user_quota_plan_custom_form(
    user_id: int,
    assignment_id: int,
    custom_quota_amount: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = (
        db.query(UserQuotaPlanAssignment, QuotaPlan)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.id == assignment_id, UserQuotaPlanAssignment.user_id == user_id, UserQuotaPlanAssignment.status == "active")
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="套餐绑定不存在")
    assignment, plan = row
    value_text = str(custom_quota_amount or "").strip()
    value = None if not value_text else int(value_text)
    if value is not None and value < 0:
        raise HTTPException(status_code=400, detail="额度不能小于 0")
    update_assignment_custom_quota(db, assignment, plan, value, admin.id)
    write_audit(db, admin.id, "update_user_quota_plan", "user", user_id, {"assignment_id": assignment.id, "custom_quota_amount": value})
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}/page#packages", status_code=303)


@router.post("/users/{user_id}/quota-plans/{assignment_id}/unbind/form")
def unbind_user_quota_plan_form(user_id: int, assignment_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    assignment = db.query(UserQuotaPlanAssignment).filter(UserQuotaPlanAssignment.id == assignment_id, UserQuotaPlanAssignment.user_id == user_id, UserQuotaPlanAssignment.status == "active").first()
    if not assignment:
        raise HTTPException(status_code=404, detail="套餐绑定不存在")
    assignment.status = "disabled"
    db.add(assignment)
    db.add(PackageQuotaLedger(assignment_id=assignment.id, plan_id=assignment.plan_id, user_id=user_id, change_amount=0, action="package_unbind", note="管理员解绑套餐", period_start_at=assignment.period_start_at, operator_user_id=admin.id))
    write_audit(db, admin.id, "unbind_quota_plan", "user", user_id, {"assignment_id": assignment.id, "plan_id": assignment.plan_id})
    db.commit()
    return RedirectResponse(f"/admin/users/{user_id}/page#packages", status_code=303)


@router.post("/users/{user_id}/toggle-status")
def toggle_user_status(user_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    new_status = "disabled" if user.status == "active" else "active"
    set_user_status(db, user, new_status, admin.id)
    db.commit()
    return {"id": user.id, "status": user.status}


@router.post("/users/{user_id}/toggle-status/form")
def toggle_user_status_form(user_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    new_status = "disabled" if user.status == "active" else "active"
    set_user_status(db, user, new_status, admin.id)
    db.commit()
    return RedirectResponse("/admin/users/page?notice=status_updated", status_code=303)


@router.post("/users/{user_id}/role/form")
def update_user_role_form(
    user_id: int,
    role: str = Form(...),
    return_to: str = Form("/admin/users/page"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    if user.id == admin.id and role != "admin":
        raise HTTPException(status_code=400, detail="不能取消自己的主管理员权限")
    if user.role == "admin" and role != "admin":
        admin_count = db.query(func.count(User.id)).filter(User.role == "admin", User.status == "active").scalar() or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能取消最后一个主管理员")
    try:
        set_user_role(db, user, role, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.commit()
    if not return_to.startswith("/admin/users"):
        return_to = "/admin/users/page"
    return RedirectResponse(return_to, status_code=303)


@router.post("/users/{user_id}/rate-limits/form")
def update_user_rate_limits_form(
    user_id: int,
    daily_job_limit: str = Form(""),
    concurrent_job_limit: str = Form(""),
    min_submit_interval_seconds: str = Form(""),
    return_to: str = Form("/admin/users/page"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    def parse_optional(value: str) -> int | None:
        value = (value or "").strip()
        if not value:
            return None
        parsed = int(value)
        if parsed < 0:
            raise ValueError("数值不能小于 0")
        return parsed or None
    try:
        user.daily_job_limit = parse_optional(daily_job_limit)
        user.concurrent_job_limit = parse_optional(concurrent_job_limit)
        user.min_submit_interval_seconds = parse_optional(min_submit_interval_seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.add(user)
    write_audit(db, admin.id, "update_user_rate_limits", "user", user.id, {
        "daily_job_limit": user.daily_job_limit,
        "concurrent_job_limit": user.concurrent_job_limit,
        "min_submit_interval_seconds": user.min_submit_interval_seconds,
    })
    db.commit()
    if not return_to.startswith("/admin/users"):
        return_to = "/admin/users/page"
    return RedirectResponse(return_to, status_code=303)


@router.post("/users/{user_id}/delete/form")
def delete_user_form(
    user_id: int,
    confirm_username: str = Form(...),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    if confirm_username.strip() != user.username:
        raise HTTPException(status_code=400, detail="账号名确认不一致")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="不能删除当前登录的主管理员")
    if user.role == "admin":
        admin_count = db.query(func.count(User.id)).filter(User.role == "admin", User.status == "active").scalar() or 0
        if admin_count <= 1:
            raise HTTPException(status_code=400, detail="不能删除最后一个主管理员")
    username = user.username
    user_role = user.role
    jobs = db.query(Job).filter(Job.user_id == user.id).all()
    for job in jobs:
        _delete_job(db, job, admin, "delete_user")
    db.query(APICallLog).filter(APICallLog.user_id == user.id).update({APICallLog.user_id: None}, synchronize_session=False)
    db.query(QuotaLedger).filter(QuotaLedger.operator_user_id == user.id).update({QuotaLedger.operator_user_id: None}, synchronize_session=False)
    db.query(DailyUsageOverride).filter(DailyUsageOverride.operator_user_id == user.id).update({DailyUsageOverride.operator_user_id: None}, synchronize_session=False)
    db.query(AuditLog).filter(AuditLog.actor_user_id == user.id).update({AuditLog.actor_user_id: None}, synchronize_session=False)
    write_audit(db, admin.id, "delete_user", "user", user.id, {"username": username, "role": user_role})
    db.delete(user)
    db.commit()
    return RedirectResponse("/admin/users/page?notice=user_deleted", status_code=303)


@router.post("/users/{user_id}/toggle-showcase/form")
def toggle_user_showcase_form(user_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    set_user_showcase(db, user, not bool(user.showcase_enabled), admin.id)
    db.commit()
    state = "on" if bool(user.showcase_enabled) else "off"
    return RedirectResponse(f"/admin/users/{user_id}/page?notice=showcase_{state}", status_code=303, headers={"Cache-Control":"no-store"})


@router.post("/users/{user_id}/toggle-report-hidden/form")
def toggle_user_report_hidden_form(
    user_id: int,
    return_to: str = Form("/admin/users/page"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    user.hidden_from_subadmin_reports = not bool(user.hidden_from_subadmin_reports)
    db.add(user)
    write_audit(db, admin.id, "set_user_report_hidden", "user", user.id, {"hidden_from_subadmin_reports": bool(user.hidden_from_subadmin_reports)})
    db.commit()
    if not return_to.startswith("/admin/users"):
        return_to = "/admin/users/page"
    return RedirectResponse(return_to, status_code=303)


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: int, payload: AdminResetPasswordRequest, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    reset_user_password(db, user, payload.password, admin.id)
    db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/reset-password/form")
def reset_password_form(user_id: int, password: str = Form(...), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Job not found")
    reset_user_password(db, user, password, admin.id)
    db.commit()
    state = "on" if bool(user.showcase_enabled) else "off"
    return RedirectResponse(f"/admin/users/{user_id}/page?notice=showcase_{state}", status_code=303, headers={"Cache-Control":"no-store"})


@router.get("/quota-ledger/page", response_class=HTMLResponse)
def quota_ledger_page(request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    paged = _pagination(db.query(QuotaLedger).order_by(QuotaLedger.id.desc()), page, per_page)
    return render(request, "admin/quota_ledger.html", current_user=admin, rows=paged["items"], pagination=paged)


@router.get("/quota-ledger")
def quota_ledger(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), _: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    paged = _pagination(db.query(QuotaLedger).order_by(QuotaLedger.id.desc()), page, per_page)
    return {**{k: v for k, v in paged.items() if k != "items"}, "items": [
        {"id": row.id, "user_id": row.user_id, "job_id": row.job_id, "change_amount": row.change_amount, "action": row.action, "note": row.note, "created_at": format_shanghai_datetime(row.created_at)}
        for row in paged["items"]
    ]}


@router.get("/quota-requests/page", response_class=HTMLResponse)
def quota_requests_page(
    request: Request,
    status: str = Query("pending"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    admin: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    status_filter = (status or "pending").strip()
    query = db.query(QuotaRequest).order_by(QuotaRequest.id.desc())
    if status_filter in {"pending", "approved", "rejected"}:
        query = query.filter(QuotaRequest.status == status_filter)
    paged = _pagination(query, page, per_page)
    user_ids = sorted({int(row.user_id) for row in paged["items"] if row.user_id is not None} | {int(row.reviewer_user_id) for row in paged["items"] if row.reviewer_user_id is not None})
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    attach_display_names(db, users)
    user_map = {int(user.id): user for user in users}
    counts = {
        "pending": db.query(func.count(QuotaRequest.id)).filter(QuotaRequest.status == "pending").scalar() or 0,
        "approved": db.query(func.count(QuotaRequest.id)).filter(QuotaRequest.status == "approved").scalar() or 0,
        "rejected": db.query(func.count(QuotaRequest.id)).filter(QuotaRequest.status == "rejected").scalar() or 0,
    }
    return render(request, "admin/quota_requests.html", current_user=admin, rows=paged["items"], user_map=user_map, counts=counts, status_filter=status_filter, pagination=paged)


@router.post("/quota-requests/{request_id}/approve/form")
def approve_quota_request_form(
    request_id: int,
    review_note: str = Form(""),
    admin: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    row = db.query(QuotaRequest).filter(QuotaRequest.id == request_id).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail="Quota request not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="申请已处理")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    note = (review_note or "").strip() or f"额度申请 #{row.id} 审批通过"
    grant_quota(db, user, int(row.amount), admin.id, note)
    row.status = "approved"
    row.reviewer_user_id = admin.id
    row.review_note = note
    row.reviewed_at = shanghai_now()
    db.add(row)
    write_audit(db, admin.id, "approve_quota_request", "quota_request", row.id, {"user_id": user.id, "amount": row.amount, "note": note})
    db.commit()
    return RedirectResponse("/admin/quota-requests/page?status=pending", status_code=303)


@router.post("/quota-requests/{request_id}/reject/form")
def reject_quota_request_form(
    request_id: int,
    review_note: str = Form(""),
    admin: User = Depends(require_admin_or_subadmin),
    db: Session = Depends(get_db),
):
    row = db.query(QuotaRequest).filter(QuotaRequest.id == request_id).with_for_update().first()
    if not row:
        raise HTTPException(status_code=404, detail="Quota request not found")
    if row.status != "pending":
        raise HTTPException(status_code=400, detail="申请已处理")
    note = (review_note or "").strip()[:500] or None
    row.status = "rejected"
    row.reviewer_user_id = admin.id
    row.review_note = note
    row.reviewed_at = shanghai_now()
    db.add(row)
    write_audit(db, admin.id, "reject_quota_request", "quota_request", row.id, {"user_id": row.user_id, "amount": row.amount, "note": note})
    db.commit()
    return RedirectResponse("/admin/quota-requests/page?status=pending", status_code=303)


@router.get("/provider-keys/page", response_class=HTMLResponse)
def provider_keys_page(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(ProviderKey).filter(ProviderKey.status != "deleted").order_by(ProviderKey.id.desc()).all()
    for row in rows:
        row.is_retired = provider_is_retired(row.provider_name)
    return render(request, "admin/provider_keys.html", current_user=admin, rows=rows)


@router.get("/provider-keys")
def list_provider_keys(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(ProviderKey).filter(ProviderKey.status != "deleted").order_by(ProviderKey.id.desc()).all()
    return [
        {"id": row.id, "name": row.name, "provider_name": row.provider_name, "api_base_url": row.api_base_url, "model_id": row.model_id, "model_id_4s": row.model_id_4s, "model_id_5s": row.model_id_5s, "model_id_8s": row.model_id_8s, "model_id_10s": row.model_id_10s, "model_id_12s": row.model_id_12s, "model_id_15s": row.model_id_15s, "key_masked": row.key_masked, "status": row.status, "weight": row.weight, "daily_limit": row.daily_limit, "concurrent_limit": row.concurrent_limit, "consecutive_failures": row.consecutive_failures, "last_error_at": row.last_error_at.isoformat() if row.last_error_at else None, "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None}
        for row in rows
    ]


def _parse_optional_int(value, default: int | None = None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return default
    parsed = int(text)
    return parsed


def _parse_positive_int(value, default: int = 1) -> int:
    try:
        parsed = int(str(value or "").strip() or default)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, 1)


def _provider_base_url(provider_name: str | None, api_base_url: str | None) -> str:
    provider = normalize_provider_name(provider_name)
    if provider_is_retired(provider):
        raise HTTPException(status_code=400, detail="该渠道已下线，不能新增或修改配置")
    value = str(api_base_url or "").strip()
    if provider == "wuyin_omni" and value.rstrip("/") in {"", "https://niubi.zeabur.app"}:
        value = "https://api.wuyinkeji.com"
    return normalize_api_base_url(value)


@router.post("/provider-keys")
def create_provider_key(payload: AdminCreateProviderKeyRequest, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    row = ProviderKey(name=payload.name, provider_name=normalize_provider_name(payload.provider_name), api_base_url=_provider_base_url(payload.provider_name, payload.api_base_url), model_id=(payload.model_id or "").strip() or None, model_id_4s=(payload.model_id_4s or "").strip() or None, model_id_5s=(payload.model_id_5s or "").strip() or None, model_id_8s=(payload.model_id_8s or "").strip() or None, model_id_10s=(payload.model_id_10s or "").strip() or None, model_id_12s=(payload.model_id_12s or "").strip() or None, model_id_15s=(payload.model_id_15s or "").strip() or None, key_masked=mask_secret(payload.raw_key), key_encrypted=encrypt_secret(payload.raw_key), weight=payload.weight, daily_limit=payload.daily_limit, concurrent_limit=payload.concurrent_limit)
    row.consecutive_failures = 0
    row.last_error_at = None
    db.add(row)
    write_audit(db, admin.id, "create_provider_key", "provider_key", None, {"name": payload.name})
    db.commit()
    db.refresh(row)
    return {"id": row.id, "name": row.name, "key_masked": row.key_masked, "api_base_url": row.api_base_url, "model_id": row.model_id, "model_id_4s": row.model_id_4s, "model_id_5s": row.model_id_5s, "model_id_8s": row.model_id_8s, "model_id_10s": row.model_id_10s, "model_id_12s": row.model_id_12s, "model_id_15s": row.model_id_15s, "concurrent_limit": row.concurrent_limit}


@router.post("/provider-keys/form")
def create_provider_key_form(
    name: str = Form(...),
    raw_key: str = Form(...),
    provider_name: str = Form("sora_api"),
    api_base_url: str = Form("https://niubi.zeabur.app"),
    model_id: str = Form(""),
    model_id_4s: str = Form(""),
    model_id_5s: str = Form(""),
    model_id_8s: str = Form(""),
    model_id_10s: str = Form(""),
    model_id_12s: str = Form(""),
    model_id_15s: str = Form(""),
    weight: str = Form("100"),
    daily_limit: str = Form(""),
    concurrent_limit: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = ProviderKey(
        name=name.strip(),
        provider_name=normalize_provider_name(provider_name),
        api_base_url=_provider_base_url(provider_name, api_base_url),
        model_id=(model_id or "").strip() or None,
        model_id_4s=(model_id_4s or "").strip() or None,
        model_id_5s=(model_id_5s or "").strip() or None,
        model_id_8s=(model_id_8s or "").strip() or None,
        model_id_10s=(model_id_10s or "").strip() or None,
        model_id_12s=(model_id_12s or "").strip() or None,
        model_id_15s=(model_id_15s or "").strip() or None,
        key_masked=mask_secret(raw_key),
        key_encrypted=encrypt_secret(raw_key),
        weight=_parse_positive_int(weight, 100),
        daily_limit=_parse_optional_int(daily_limit),
        concurrent_limit=_parse_optional_int(concurrent_limit),
    )
    row.consecutive_failures = 0
    row.last_error_at = None
    db.add(row)
    write_audit(db, admin.id, "create_provider_key", "provider_key", None, {"name": name, "api_base_url": row.api_base_url, "model_id": row.model_id})
    db.commit()
    return RedirectResponse("/admin/provider-keys/page", status_code=303)


@router.post("/provider-keys/{key_id}/toggle-status/form")
def toggle_provider_key_form(key_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if provider_is_retired(row.provider_name):
        raise HTTPException(status_code=400, detail="该渠道已下线，不能重新启用")
    row.status = "disabled" if row.status == "active" else "active"
    if row.status == "active":
        row.consecutive_failures = 0
        row.last_error_at = None
    db.add(row)
    write_audit(db, admin.id, "toggle_provider_key", "provider_key", row.id, {"status": row.status})
    db.commit()
    return RedirectResponse("/admin/provider-keys/page", status_code=303)


@router.post("/provider-keys/{key_id}/update/form")
def update_provider_key_form(
    key_id: int,
    name: str = Form(...),
    raw_key: str = Form(""),
    provider_name: str = Form("sora_api"),
    api_base_url: str = Form("https://niubi.zeabur.app"),
    model_id: str = Form(""),
    model_id_4s: str = Form(""),
    model_id_5s: str = Form(""),
    model_id_8s: str = Form(""),
    model_id_10s: str = Form(""),
    model_id_12s: str = Form(""),
    model_id_15s: str = Form(""),
    weight: str = Form("100"),
    daily_limit: str = Form(""),
    concurrent_limit: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if provider_is_retired(row.provider_name):
        raise HTTPException(status_code=400, detail="已下线渠道仅保留历史记录")
    row.name = name.strip()
    row.provider_name = normalize_provider_name(provider_name)
    row.api_base_url = _provider_base_url(provider_name, api_base_url)
    row.model_id = (model_id or "").strip() or None
    row.model_id_4s = (model_id_4s or "").strip() or None
    row.model_id_5s = (model_id_5s or "").strip() or None
    row.model_id_8s = (model_id_8s or "").strip() or None
    row.model_id_10s = (model_id_10s or "").strip() or None
    row.model_id_12s = (model_id_12s or "").strip() or None
    row.model_id_15s = (model_id_15s or "").strip() or None
    row.weight = _parse_positive_int(weight, 100)
    row.daily_limit = _parse_optional_int(daily_limit)
    row.concurrent_limit = _parse_optional_int(concurrent_limit)
    if raw_key and raw_key.strip():
        row.key_masked = mask_secret(raw_key.strip())
        row.key_encrypted = encrypt_secret(raw_key.strip())
    row.consecutive_failures = 0
    row.last_error_at = None
    db.add(row)
    write_audit(db, admin.id, "update_provider_key", "provider_key", row.id, {"name": row.name, "api_base_url": row.api_base_url, "model_id": row.model_id})
    db.commit()
    return RedirectResponse("/admin/provider-keys/page", status_code=303)


@router.post("/provider-keys/{key_id}/delete/form")
def delete_provider_key_form(key_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(ProviderKey).filter(ProviderKey.id == key_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    used_count = int(db.query(func.count(Job.id)).filter(Job.provider_key_id == row.id).scalar() or 0)
    if used_count:
        row.status = "deleted"
        row.name = f"{row.name}（已删除）"[:128]
        db.add(row)
    else:
        db.delete(row)
    write_audit(db, admin.id, "delete_provider_key", "provider_key", key_id, {"used_count": used_count})
    db.commit()
    return RedirectResponse("/admin/provider-keys/page", status_code=303)


@router.get("/reference-images/page", response_class=HTMLResponse)
def reference_images_page(
    request: Request,
    scope: str = Query(default="all"),
    status: str = Query(default="all"),
    user_id: str = Query(default=""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(ReferenceImagePreset)
    if scope == "common":
        query = query.filter(ReferenceImagePreset.owner_user_id.is_(None))
    elif scope == "user":
        query = query.filter(ReferenceImagePreset.owner_user_id.isnot(None))
    if status in {"active", "disabled"}:
        query = query.filter(ReferenceImagePreset.status == status)
    selected_user_id = None
    if user_id.strip().isdigit():
        selected_user_id = int(user_id.strip())
        query = query.filter(ReferenceImagePreset.owner_user_id == selected_user_id)
    rows = query.order_by(ReferenceImagePreset.owner_user_id.asc().nullsfirst(), ReferenceImagePreset.sort_order.asc(), ReferenceImagePreset.id.desc()).all()
    owner_ids = [int(row.owner_user_id) for row in rows if row.owner_user_id]
    owners = {}
    if owner_ids:
        users = db.query(User, UserProfile).outerjoin(UserProfile, UserProfile.user_id == User.id).filter(User.id.in_(owner_ids)).all()
        for user, profile in users:
            setattr(user, "display_name", (profile.display_name or "").strip() if profile else "")
            owners[int(user.id)] = user
    for row in rows:
        owner = owners.get(int(row.owner_user_id)) if row.owner_user_id else None
        setattr(row, "owner_label", user_display_name(owner) if owner else "通用预设")
        setattr(row, "owner_username", owner.username if owner else "")
    user_options = db.query(User, UserProfile).outerjoin(UserProfile, UserProfile.user_id == User.id).order_by(User.id.desc()).all()
    user_rows = []
    for user, profile in user_options:
        setattr(user, "display_name", (profile.display_name or "").strip() if profile else "")
        user_rows.append(user)
    return render(request, "admin/reference_images.html", current_user=admin, rows=rows, user_rows=user_rows, scope=scope, status=status, selected_user_id=selected_user_id)


def _ensure_reference_dimensions(width: int, height: int) -> None:
    # Presets are channel-neutral; generation validates the selected provider's limits.
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="参考图尺寸无效")


def _parse_reference_owner_user_id(db: Session, owner_user_id: str | None) -> int | None:
    text = str(owner_user_id or "").strip()
    if not text:
        return None
    if not text.isdigit():
        raise HTTPException(status_code=400, detail="预设归属用户无效")
    user_id = int(text)
    if not db.query(User.id).filter(User.id == user_id).first():
        raise HTTPException(status_code=400, detail="预设归属用户不存在")
    return user_id


@router.post("/reference-images/form")
def create_reference_image_form(
    name: str = Form(...),
    image_url: str = Form(...),
    sort_order: str = Form("100"),
    owner_user_id: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    try:
        normalized_url = normalize_public_image_url(image_url)
        width, height, _, _ = fetch_image_dimensions(normalized_url)
        _ensure_reference_dimensions(width, height)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = ReferenceImagePreset(
        owner_user_id=_parse_reference_owner_user_id(db, owner_user_id),
        name=name.strip(),
        image_url=normalized_url,
        width=width,
        height=height,
        aspect_ratio=aspect_ratio_for_dimensions(width, height),
        status="active",
        sort_order=_parse_positive_int(sort_order, 100),
    )
    db.add(row)
    write_audit(db, admin.id, "create_reference_image_preset", "reference_image_preset", None, {"name": row.name, "image_url": row.image_url})
    db.commit()
    return RedirectResponse("/admin/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/update/form")
def update_reference_image_form(
    preset_id: int,
    name: str = Form(...),
    image_url: str = Form(...),
    sort_order: str = Form("100"),
    owner_user_id: str = Form(""),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        normalized_url = normalize_public_image_url(image_url)
        width, height, _, _ = fetch_image_dimensions(normalized_url)
        _ensure_reference_dimensions(width, height)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.name = name.strip()
    row.owner_user_id = _parse_reference_owner_user_id(db, owner_user_id)
    row.image_url = normalized_url
    row.width = width
    row.height = height
    row.aspect_ratio = aspect_ratio_for_dimensions(width, height)
    row.sort_order = _parse_positive_int(sort_order, 100)
    db.add(row)
    write_audit(db, admin.id, "update_reference_image_preset", "reference_image_preset", row.id, {"name": row.name})
    db.commit()
    return RedirectResponse("/admin/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/toggle/form")
def toggle_reference_image_form(preset_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if provider_is_retired(row.provider_name):
        raise HTTPException(status_code=400, detail="该渠道已下线，不能重新启用")
    row.status = "disabled" if row.status == "active" else "active"
    db.add(row)
    write_audit(db, admin.id, "update_reference_image_preset", "reference_image_preset", row.id, {"status": row.status})
    db.commit()
    return RedirectResponse("/admin/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/delete/form")
def delete_reference_image_form(preset_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    db.delete(row)
    write_audit(db, admin.id, "delete_reference_image_preset", "reference_image_preset", preset_id, {})
    db.commit()
    return RedirectResponse("/admin/reference-images/page", status_code=303)


def _apply_job_user_filter(query, user_keyword: str | None):
    keyword = (user_keyword or "").strip()
    if not keyword:
        return query
    query = query.join(User, User.id == Job.user_id)
    query = query.outerjoin(UserProfile, UserProfile.user_id == User.id)
    filters = [
        User.username.ilike(f"%{keyword}%"),
        UserProfile.display_name.ilike(f"%{keyword}%"),
        Job.product_name.ilike(f"%{keyword}%"),
        Job.region_name.ilike(f"%{keyword}%"),
    ]
    if keyword.isdigit():
        filters.append(Job.user_id == int(keyword))
    return query.filter(or_(*filters))


def _apply_job_status_filter(query, status_filter: str | None):
    value = (status_filter or "all").strip() or "all"
    if value == "all":
        return query
    if value == "running":
        return query.filter(Job.status.in_(RUNNING_STATUSES))
    if value == "failed":
        return query.filter(Job.status.in_(FAILED_STATUSES - {"download_failed"}))
    if value in {"queued", "completed", "download_failed"}:
        return query.filter(Job.status == value)
    return query.filter(Job.status == value)


def _job_status_tabs(db: Session, user_filter: str | None, active: str, batch_id: int | None = None) -> list[dict]:
    base = _apply_job_user_filter(db.query(Job), user_filter)
    if batch_id is not None:
        base = base.filter(Job.batch_id == batch_id)
    tab_defs = [
        ("all", "全部", base),
        ("queued", "排队中", base.filter(Job.status == "queued")),
        ("running", "运行中", base.filter(Job.status.in_(RUNNING_STATUSES))),
        ("completed", "已完成", base.filter(Job.status == "completed")),
        ("download_failed", "下载失败", base.filter(Job.status == "download_failed")),
        ("failed", "失败", base.filter(Job.status.in_(FAILED_STATUSES - {"download_failed"}))),
    ]
    return [
        {"key": key, "label": label, "count": int(query.order_by(None).count() or 0), "active": key == active}
        for key, label, query in tab_defs
    ]


def _job_user_map(db: Session, jobs: list[Job]) -> dict[int, User]:
    user_ids = sorted({int(job.user_id) for job in jobs if job.user_id is not None})
    if not user_ids:
        return {}
    users = db.query(User).filter(User.id.in_(user_ids)).all()
    attach_display_names(db, users)
    return {int(user.id): user for user in users}


def _job_batch_map(db: Session, jobs: list[Job]) -> dict[int, JobBatch]:
    batch_ids = sorted({int(job.batch_id) for job in jobs if job.batch_id is not None})
    if not batch_ids:
        return {}
    batches = db.query(JobBatch).filter(JobBatch.id.in_(batch_ids)).all()
    return {int(batch.id): batch for batch in batches}



def _batch_summary_map(db: Session, batch_ids: list[int] | set[int]) -> dict[int, dict]:
    ids = [int(item) for item in batch_ids if item is not None]
    if not ids:
        return {}
    rows = (
        db.query(Job.batch_id, Job.status, func.count(Job.id).label("count"))
        .filter(Job.batch_id.in_(ids))
        .group_by(Job.batch_id, Job.status)
        .all()
    )
    label_order = [
        ("queued", "排队中"),
        ("submitting", "运行中"),
        ("submitted", "运行中"),
        ("polling", "运行中"),
        ("remote_completed", "待下载"),
        ("download_waiting", "等待下载"),
        ("downloading", "下载中"),
        ("completed", "已完成"),
        ("download_failed", "下载失败"),
        ("failed", "失败"),
        ("interrupted", "已暂停"),
        ("cancelled", "已取消"),
    ]
    raw: dict[int, dict[str, int]] = {batch_id: {} for batch_id in ids}
    for batch_id, status, count in rows:
        if batch_id is None:
            continue
        raw.setdefault(int(batch_id), {})[str(status or "-")] = int(count or 0)
    summaries: dict[int, dict] = {}
    for batch_id in ids:
        counts = raw.get(batch_id, {})
        total = sum(counts.values())
        parts: list[str] = []
        merged_running = 0
        for key, label in label_order:
            if key in {"submitting", "submitted", "polling"}:
                merged_running += counts.get(key, 0)
                continue
            value = counts.get(key, 0)
            if value:
                parts.append(f"{value} {label}")
        if merged_running:
            parts.insert(0, f"{merged_running} 运行中")
        if not parts:
            parts = ["暂无任务"]
        failed_count = sum(counts.get(item, 0) for item in ["failed", "download_failed", "interrupted", "cancelled"])
        active_count = sum(counts.get(item, 0) for item in ["queued", "submitting", "submitted", "polling", "remote_completed", "download_waiting", "downloading"])
        completed_count = counts.get("completed", 0)
        if total == 0:
            state_label = "已清空"
            state_class = "status-cleared"
        elif failed_count:
            state_label = "部分失败" if completed_count or active_count else "失败"
            state_class = "status-download_failed"
        elif active_count:
            state_label = "进行中"
            state_class = "status-polling"
        elif completed_count and completed_count == total:
            state_label = "已完成"
            state_class = "status-completed"
        else:
            state_label = "已清空"
            state_class = "status-cleared"
        summaries[batch_id] = {
            "counts": counts,
            "total": total,
            "text": " / ".join(parts),
            "state_label": state_label,
            "state_class": state_class,
            "active_count": active_count,
            "failed_count": failed_count,
            "completed_count": completed_count,
        }
    return summaries


def _job_user_label(user_map: dict[int, User], user_id: int | None) -> str:
    if user_id is None:
        return "-"
    user = user_map.get(int(user_id))
    if user:
        return f"{user_display_name(user)}（#{user.id}）"
    return f"用户 #{user_id}"


@router.get("/jobs/page", response_class=HTMLResponse)
def jobs_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: str | None = Query(default=None),
    status: str | None = Query(default="all"),
    batch_id: int | None = Query(default=None, ge=1),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    status_filter = (status or "all").strip() or "all"
    query = _apply_job_status_filter(_apply_job_user_filter(db.query(Job), user), status_filter).order_by(Job.id.desc())
    selected_batch = None
    selected_batch_summary = {}
    if batch_id is not None:
        selected_batch = db.query(JobBatch).filter(JobBatch.id == batch_id).first()
        if selected_batch is None:
            raise HTTPException(status_code=404, detail="批次不存在")
        query = query.filter(Job.batch_id == batch_id)
        selected_batch_summary = _batch_summary_map(db, {batch_id}).get(batch_id, {})
    paged = _pagination(query, page, per_page)
    user_map = _job_user_map(db, paged["items"])
    batch_map = _job_batch_map(db, paged["items"])
    queue_stats = {
        "running": db.query(func.count(Job.id)).filter(Job.status.in_(RUNNING_STATUSES)).scalar() or 0,
        "queued": db.query(func.count(Job.id)).filter(Job.status == "queued").scalar() or 0,
        "max_running": get_system_setting_int(db, "max_running_jobs", settings.max_running_jobs) or settings.max_running_jobs,
    }
    queue_map = {job.id: queue_text(db, job) for job in paged["items"]}
    return render(
        request,
        "admin/jobs.html",
        current_user=current_user,
        jobs=paged["items"],
        selected_batch=selected_batch,
        selected_batch_summary=selected_batch_summary,
        batch_files={job.id: get_output_file(db, job.id) for job in paged["items"] if job.status == "completed"} if selected_batch else {},
        job_user_map=user_map,
        job_batch_map=batch_map,
        queue_map=queue_map,
        pagination=paged,
        queue_stats=queue_stats,
        can_manage=current_user.role == "admin",
        user_filter=(user or "").strip(),
        status_filter=status_filter,
        status_tabs=_job_status_tabs(db, user, status_filter, batch_id),
    )


@router.get("/jobs")
def jobs_json(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: str | None = Query(default=None),
    status: str | None = Query(default="all"),
    _: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
) -> dict:
    query = _apply_job_status_filter(_apply_job_user_filter(db.query(Job), user), status).order_by(Job.id.desc())
    paged = _pagination(query, page, per_page)
    user_map = _job_user_map(db, paged["items"])
    items = []
    for job in paged["items"]:
        item = serialize_job(job, get_output_file(db, job.id))
        user_obj = user_map.get(int(job.user_id)) if job.user_id is not None else None
        item["username"] = user_obj.username if user_obj else None
        item["display_name"] = user_display_name(user_obj) if user_obj else None
        item["user_label"] = _job_user_label(user_map, job.user_id)
        if job.batch_id:
            batch = db.query(JobBatch).filter(JobBatch.id == job.batch_id).first()
            item["batch_code"] = batch.batch_code if batch else None
            item["batch_name"] = batch.batch_name if batch else None
        items.append(item)
    return {**{k: v for k, v in paged.items() if k != "items"}, "items": items}



@router.get("/job-batches/page", response_class=HTMLResponse)
def admin_job_batches_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    user: str | None = Query(default=None),
    current_user: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    query = db.query(JobBatch).order_by(JobBatch.id.desc())
    user_filter = (user or "").strip()
    if user_filter:
        if user_filter.isdigit():
            query = query.filter(
                or_(
                    JobBatch.user_id == int(user_filter),
                    JobBatch.batch_code.ilike(f"%{user_filter}%"),
                    JobBatch.batch_name.ilike(f"%{user_filter}%"),
                    JobBatch.product_name.ilike(f"%{user_filter}%"),
                    JobBatch.region_name.ilike(f"%{user_filter}%"),
                )
            )
        else:
            query = query.join(User, User.id == JobBatch.user_id).outerjoin(UserProfile, UserProfile.user_id == User.id).filter(
                or_(
                    User.username.ilike(f"%{user_filter}%"),
                    UserProfile.display_name.ilike(f"%{user_filter}%"),
                    JobBatch.batch_code.ilike(f"%{user_filter}%"),
                    JobBatch.batch_name.ilike(f"%{user_filter}%"),
                    JobBatch.product_name.ilike(f"%{user_filter}%"),
                    JobBatch.region_name.ilike(f"%{user_filter}%"),
                )
            )
    paged = _pagination(query, page, per_page)
    summary_map = _batch_summary_map(db, {batch.id for batch in paged["items"]})
    user_ids = sorted({int(batch.user_id) for batch in paged["items"] if batch.user_id is not None})
    users = db.query(User).filter(User.id.in_(user_ids)).all() if user_ids else []
    attach_display_names(db, users)
    user_map = {int(user.id): user for user in users}
    return render(
        request,
        "admin/job_batches.html",
        current_user=current_user,
        batches=paged["items"],
        summary_map=summary_map,
        user_map=user_map,
        pagination=paged,
        user_filter=user_filter,
        can_manage=current_user.role == "admin",
    )


@router.post("/job-batches/{batch_id}/delete/form")
def admin_delete_job_batch_form(batch_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    batch = db.query(JobBatch).filter(JobBatch.id == batch_id).with_for_update().first()
    if not batch:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs = db.query(Job).filter(Job.batch_id == batch.id).all()
    deleted_jobs = 0
    for job in jobs:
        _delete_job(db, job, admin, "delete_job_batch")
        deleted_jobs += 1
    write_audit(db, admin.id, "delete_job_batch", "job_batch", batch.id, {"batch_code": batch.batch_code, "batch_name": batch.batch_name, "deleted_jobs": deleted_jobs})
    db.delete(batch)
    db.commit()
    return RedirectResponse("/admin/job-batches/page", status_code=303)


@router.post("/job-batches/delete-empty/form")
def admin_delete_empty_job_batches_form(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    existing_batch_rows = db.query(Job.batch_id).filter(Job.batch_id.isnot(None)).distinct().all()
    existing_batch_ids = {int(row[0]) for row in existing_batch_rows if row[0] is not None}
    query = db.query(JobBatch)
    if existing_batch_ids:
        query = query.filter(~JobBatch.id.in_(existing_batch_ids))
    batches = query.all()
    count = 0
    for batch in batches:
        write_audit(db, admin.id, "delete_job_batch", "job_batch", batch.id, {"batch_code": batch.batch_code, "batch_name": batch.batch_name, "deleted_jobs": 0, "reason": "empty_cleanup"})
        db.delete(batch)
        count += 1
    db.commit()
    return RedirectResponse("/admin/job-batches/page", status_code=303)


@router.get("/jobs/{job_id}/page", response_class=HTMLResponse)
def job_detail_page(job_id: int, request: Request, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    events = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id.asc()).all()
    files = db.query(JobFile).filter(JobFile.job_id == job.id).order_by(JobFile.id.asc()).all()
    job_data = serialize_job(job, output_file, include_upstream_response=True)
    job_data["queue_text"] = queue_text(db, job)
    job_data["remote_download_url"] = f"/admin/jobs/{job.id}/remote-download" if job.remote_task_id else None
    token = make_public_remote_download_token(job.id, job.remote_task_id, get_system_setting_int(db, "public_download_token_ttl_seconds", settings.public_download_token_ttl_seconds))
    job_data["public_remote_download_url"] = f"/admin/jobs/{job.id}/public-remote-download?token={token}" if token else None
    return render(request, "admin/job_detail.html", current_user=current_user, job=job_data, output_file=output_file, events=[serialize_event(event) for event in events], files=files, can_redownload=current_user.role == "admin" and can_redownload(job, output_file), can_resume=current_user.role == "admin" and can_resume(job), can_pause=current_user.role == "admin" and can_pause(job), can_manage=True, data_endpoint=f"/admin/jobs/{job.id}", remote_download_url=job_data.get("remote_download_url"), public_remote_download_url=job_data.get("public_remote_download_url"))


@router.get("/jobs/{job_id}")
def job_detail_json(job_id: int, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    events = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id.asc()).all()
    job_data = serialize_job(job, output_file, include_upstream_response=True)
    job_data["queue_text"] = queue_text(db, job)
    job_data["remote_download_url"] = f"/admin/jobs/{job.id}/remote-download" if job.remote_task_id else None
    token = make_public_remote_download_token(job.id, job.remote_task_id, get_system_setting_int(db, "public_download_token_ttl_seconds", settings.public_download_token_ttl_seconds))
    job_data["public_remote_download_url"] = f"/admin/jobs/{job.id}/public-remote-download?token={token}" if token else None
    return {"job": job_data, "events": [serialize_event(event) for event in events], "can_redownload": current_user.role == "admin" and can_redownload(job, output_file), "can_resume": current_user.role == "admin" and can_resume(job), "can_pause": current_user.role == "admin" and can_pause(job)}


@router.get("/jobs/{job_id}/public-remote-download")
def public_remote_download_job(job_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not verify_public_remote_download_token(token, job.id, job.remote_task_id):
        raise HTTPException(status_code=403, detail="下载链接无效或已过期")
    if not job.remote_task_id:
        raise HTTPException(status_code=400, detail="Remote task has not been created yet")
    provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).first()
    if not provider_key:
        raise HTTPException(status_code=400, detail="Provider key not found for this job")
    api_key = decrypt_secret(provider_key.key_encrypted)
    try:
        response, client = open_video_stream(api_key, job.remote_task_id, provider_key.api_base_url, provider_key.provider_name)
    except UpstreamError as exc:
        detail = f"Remote download failed: {exc}"
        if exc.status_code:
            detail += f" ({exc.status_code})"
        raise HTTPException(status_code=502, detail=detail) from exc
    content_type = response.headers.get("content-type") or "video/mp4"
    headers = {"Content-Disposition": attachment_disposition(job_video_download_filename(db, job))}
    content_length = response.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length
    return StreamingResponse(iter_video_stream(response, client), media_type=content_type, headers=headers)


@router.get("/jobs/{job_id}/remote-download")
def remote_download_job(job_id: int, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not job.remote_task_id:
        raise HTTPException(status_code=400, detail="Remote task has not been created yet")
    provider_key = db.query(ProviderKey).filter(ProviderKey.id == job.provider_key_id).first()
    if not provider_key:
        raise HTTPException(status_code=400, detail="Provider key not found for this job")
    api_key = decrypt_secret(provider_key.key_encrypted)
    try:
        response, client = open_video_stream(api_key, job.remote_task_id, provider_key.api_base_url, provider_key.provider_name)
    except UpstreamError as exc:
        detail = f"Remote download failed: {exc}"
        if exc.status_code:
            detail += f" ({exc.status_code})"
        raise HTTPException(status_code=502, detail=detail) from exc
    content_type = response.headers.get("content-type") or "video/mp4"
    headers = {"Content-Disposition": attachment_disposition(job_video_download_filename(db, job))}
    content_length = response.headers.get("content-length")
    if content_length:
        headers["Content-Length"] = content_length
    return StreamingResponse(iter_video_stream(response, client), media_type=content_type, headers=headers)


@router.post("/jobs/{job_id}/redownload")
def redownload(job_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    if not can_redownload(job, output_file):
        raise HTTPException(status_code=400, detail="Current job status does not allow redownload")
    job.status = "remote_completed"
    job.download_attempts = 0
    job.error_text = None
    job.progress = 100
    db.add(job)
    db.add(JobEvent(job_id=job.id, level="info", event_type="redownload_requested", message="Admin requested redownload."))
    db.commit()
    try:
        from app.services.worker_runtime import schedule_job_now
        kicked = schedule_job_now(int(job.id))
        db.add(JobEvent(job_id=job.id, level="info", event_type="manual_kick", message=f"Worker kick requested; scheduled={kicked}."))
        db.commit()
    except Exception:
        pass
    return {"ok": True}


@router.post("/jobs/{job_id}/resume")
def resume(job_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    force_download_statuses = {"remote_completed", "download_failed", "download_waiting", "downloading"}
    if can_redownload(job, output_file):
        job.status = "remote_completed"
        job.download_attempts = 0
    elif can_resume(job):
        if job.remote_task_id:
            if job.status in force_download_statuses or int(job.progress or 0) >= 100 or _has_confirmed_remote_completed(db, job):
                job.status = "remote_completed"
                job.download_attempts = 0
            else:
                job.status = "polling"
        else:
            job.status = "queued"
            job.submit_attempts = 0
            job.started_at = None
    else:
        raise HTTPException(status_code=400, detail="Current job status does not allow resume")
    job.error_text = None
    db.add(job)
    mode_text = "download" if job.status == "remote_completed" else "polling"
    db.add(JobEvent(job_id=job.id, level="info", event_type="resume_requested", message=f"Admin requested resume; mode={mode_text}."))
    db.commit()
    try:
        from app.services.worker_runtime import schedule_job_now
        kicked = schedule_job_now(int(job.id))
        db.add(JobEvent(job_id=job.id, level="info", event_type="manual_kick", message=f"Worker kick requested; scheduled={kicked}."))
        db.commit()
    except Exception:
        pass
    return {"ok": True}


@router.post("/jobs/{job_id}/pause")
def pause(job_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not can_pause(job):
        raise HTTPException(status_code=400, detail="Current job status does not allow pause")
    job.status = "interrupted"
    db.add(job)
    db.add(JobEvent(job_id=job.id, level="info", event_type="pause_requested", message="Admin requested pause."))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/delete/form")
def delete_job_form(job_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).with_for_update().first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    _delete_job(db, job, admin, "single")
    db.commit()
    return RedirectResponse("/admin/jobs/page", status_code=303)


@router.post("/jobs/delete-failed/form")
def delete_failed_jobs_form(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    jobs = db.query(Job).filter(Job.status.in_(FAILED_STATUSES)).all()
    count = 0
    for job in jobs:
        _delete_job(db, job, admin, "failed_batch")
        count += 1
    write_audit(db, admin.id, "delete_failed_jobs", "job", None, {"count": count})
    db.commit()
    return RedirectResponse("/admin/jobs/page", status_code=303)


@router.post("/jobs/delete-stuck/form")
def delete_stuck_jobs_form(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    now_utc = datetime.now(UTC)
    jobs = db.query(Job).filter(_stuck_filter(now_utc)).all()
    count = 0
    for job in jobs:
        _delete_job(db, job, admin, "stuck_batch")
        count += 1
    write_audit(db, admin.id, "delete_stuck_jobs", "job", None, {"count": count})
    db.commit()
    return RedirectResponse("/admin/jobs/page", status_code=303)


@router.get("/queue/page", response_class=HTMLResponse)
def queue_page(request: Request, current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    running_jobs = db.query(Job).filter(Job.status.in_(RUNNING_STATUSES)).order_by(Job.started_at.asc().nullsfirst(), Job.id.asc()).limit(50).all()
    queued_jobs = db.query(Job).filter(Job.status == "queued").order_by(Job.queued_at.asc().nullsfirst(), Job.id.asc()).limit(100).all()
    stuck_jobs = db.query(Job).filter(_stuck_filter(datetime.now(UTC))).order_by(Job.updated_at.asc()).limit(50).all()
    all_jobs = list({job.id: job for job in [*running_jobs, *queued_jobs, *stuck_jobs]}.values())
    user_map = _job_user_map(db, all_jobs)
    queue_map = {job.id: queue_text(db, job) for job in all_jobs}
    return render(request, "admin/queue.html", current_user=current_user, stats=_queue_stats(db), running_jobs=running_jobs, queued_jobs=queued_jobs, stuck_jobs=stuck_jobs, user_map=user_map, queue_map=queue_map, can_manage=current_user.role == "admin")


@router.get("/queue")
def queue_json(_: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    queued = db.query(Job).filter(Job.status == "queued").order_by(Job.queued_at.asc().nullsfirst(), Job.id.asc()).limit(100).all()
    running = db.query(Job).filter(Job.status.in_(RUNNING_STATUSES)).order_by(Job.started_at.asc().nullsfirst(), Job.id.asc()).limit(50).all()
    return {
        "stats": _queue_stats(db),
        "queued": [serialize_job(job, get_output_file(db, job.id)) | {"queue_text": queue_text(db, job)} for job in queued],
        "running": [serialize_job(job, get_output_file(db, job.id)) | {"queue_text": queue_text(db, job)} for job in running],
    }


@router.get("/download-failures/page", response_class=HTMLResponse)
def download_failures_page(request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), current_user: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    paged, details = _download_failure_rows(db, page, per_page)
    return render(request, "admin/download_failures.html", current_user=current_user, rows=details, pagination=paged, can_manage=current_user.role == "admin")


@router.get("/rankings/page", response_class=HTMLResponse)
def rankings_page(request: Request, period: str = Query("month"), start_date: str | None = Query(None), end_date: str | None = Query(None), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    parsed_start = _parse_optional_date(start_date)
    parsed_end = _parse_optional_date(end_date)
    start_utc, end_utc, period_label = _period_bounds(period, parsed_start, parsed_end)
    usage_counts = _net_usage_counts_by_user(db, start_utc, end_utc)
    ranked_user_ids = [user_id for user_id, _count in sorted(usage_counts.items(), key=lambda item: (-item[1], item[0]))[:100]]
    users = db.query(User).filter(User.id.in_(ranked_user_ids), User.role == "user").all() if ranked_user_ids else []
    profiles = db.query(UserProfile).filter(UserProfile.user_id.in_(ranked_user_ids)).all() if ranked_user_ids else []
    user_map = {int(user.id): user for user in users}
    profile_map = {int(profile.user_id): profile for profile in profiles}
    user_ids = [user_id for user_id in ranked_user_ids if user_id in user_map]
    success_counts = {uid: 0 for uid in user_ids}
    failure_counts = {uid: 0 for uid in user_ids}
    download_failure_counts = {uid: 0 for uid in user_ids}
    if user_ids:
        for uid, count in db.query(Job.user_id, func.count(Job.id)).filter(Job.user_id.in_(user_ids), Job.status == "completed", Job.created_at >= start_utc, Job.created_at < end_utc).group_by(Job.user_id).all():
            success_counts[int(uid)] = int(count or 0)
        for uid, count in db.query(Job.user_id, func.count(Job.id)).filter(Job.user_id.in_(user_ids), Job.status.in_(FAILED_STATUSES - {"download_failed"}), Job.created_at >= start_utc, Job.created_at < end_utc).group_by(Job.user_id).all():
            failure_counts[int(uid)] = int(count or 0)
        for uid, count in db.query(Job.user_id, func.count(Job.id)).filter(Job.user_id.in_(user_ids), Job.status == "download_failed", Job.created_at >= start_utc, Job.created_at < end_utc).group_by(Job.user_id).all():
            download_failure_counts[int(uid)] = int(count or 0)
    rankings = [
        {
            "user_id": user_id,
            "username": user_map[user_id].username,
            "display_name": ((profile_map.get(user_id).display_name if profile_map.get(user_id) else "") or "").strip(),
            "usage_count": usage_counts.get(user_id, 0),
            "success_count": success_counts.get(user_id, 0),
            "failure_count": failure_counts.get(user_id, 0),
            "download_failure_count": download_failure_counts.get(user_id, 0),
        }
        for user_id in user_ids
    ]
    return render(request, "admin/rankings.html", current_user=admin, rankings=rankings, period=period, period_label=period_label, start_date=parsed_start, end_date=parsed_end)


@router.get("/settings/page", response_class=HTMLResponse)
def settings_page(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    return render(request, "admin/settings.html", current_user=admin, settings_rows=get_system_settings_view(db))


@router.get("/quota-plans/page", response_class=HTMLResponse)
def quota_plans_page(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = []
    plans = db.query(QuotaPlan).order_by(QuotaPlan.id.desc()).all()
    counts = {
        int(plan_id): int(count or 0)
        for plan_id, count in db.query(UserQuotaPlanAssignment.plan_id, func.count(UserQuotaPlanAssignment.id)).filter(UserQuotaPlanAssignment.status == "active").group_by(UserQuotaPlanAssignment.plan_id).all()
    }
    for plan in plans:
        rows.append({"plan": plan, "assignment_count": counts.get(int(plan.id), 0)})
    return render(request, "admin/quota_plans.html", current_user=admin, rows=rows)


def _validate_quota_plan_form(name: str, period_type: str, quota_amount: int) -> tuple[str, str, int]:
    clean_name = " ".join(str(name or "").split())
    if not clean_name:
        raise HTTPException(status_code=400, detail="请填写套餐名称")
    if period_type not in PLAN_PERIOD_TYPES:
        raise HTTPException(status_code=400, detail="套餐周期无效")
    amount = int(quota_amount or 0)
    if amount < 0:
        raise HTTPException(status_code=400, detail="套餐额度不能小于 0")
    return clean_name, period_type, amount


@router.post("/quota-plans/form")
def create_quota_plan_form(name: str = Form(...), period_type: str = Form(...), quota_amount: int = Form(...), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    clean_name, clean_period, amount = _validate_quota_plan_form(name, period_type, quota_amount)
    plan = QuotaPlan(name=clean_name, period_type=clean_period, quota_amount=amount, status="active")
    db.add(plan)
    db.flush()
    write_audit(db, admin.id, "create_quota_plan", "quota_plan", plan.id, {"name": clean_name, "period_type": clean_period, "quota_amount": amount})
    db.commit()
    return RedirectResponse("/admin/quota-plans/page", status_code=303)


@router.post("/quota-plans/{plan_id}/update/form")
def update_quota_plan_form(plan_id: int, name: str = Form(...), period_type: str = Form(...), quota_amount: int = Form(...), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    plan = db.query(QuotaPlan).filter(QuotaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")
    clean_name, clean_period, amount = _validate_quota_plan_form(name, period_type, quota_amount)
    plan.name = clean_name
    plan.period_type = clean_period
    plan.quota_amount = amount
    db.add(plan)
    write_audit(db, admin.id, "update_quota_plan", "quota_plan", plan.id, {"name": clean_name, "period_type": clean_period, "quota_amount": amount})
    db.commit()
    return RedirectResponse("/admin/quota-plans/page", status_code=303)


@router.post("/quota-plans/{plan_id}/toggle/form")
def toggle_quota_plan_form(plan_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    plan = db.query(QuotaPlan).filter(QuotaPlan.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="套餐不存在")
    if plan.status == "active":
        plan.status = "disabled"
        unbound = deactivate_plan_assignments(db, plan.id, admin.id)
    else:
        plan.status = "active"
        unbound = 0
    db.add(plan)
    write_audit(db, admin.id, "toggle_quota_plan", "quota_plan", plan.id, {"status": plan.status, "unbound": unbound})
    db.commit()
    return RedirectResponse("/admin/quota-plans/page", status_code=303)


@router.get("/risk-control/page", response_class=HTMLResponse)
def risk_control_page(request: Request, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    rows = db.query(RiskControlRule).order_by(RiskControlRule.id.desc()).all()
    return render(request, "admin/risk_control.html", current_user=admin, rows=rows)


def _validate_risk_rule_form(keywords: str, error_message: str) -> tuple[list[str], str]:
    parsed_keywords = parse_keywords(keywords)
    message = " ".join(str(error_message or "").split())
    if not parsed_keywords:
        raise HTTPException(status_code=400, detail="请至少填写 1 个关键词")
    if not message:
        raise HTTPException(status_code=400, detail="请填写失败提示")
    return parsed_keywords, message


@router.post("/risk-control/form")
def create_risk_rule_form(
    keywords: str = Form(...),
    error_message: str = Form(...),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    parsed_keywords, message = _validate_risk_rule_form(keywords, error_message)
    row = RiskControlRule(keywords=parsed_keywords, error_message=message, status="active", operator_user_id=admin.id)
    db.add(row)
    db.flush()
    write_audit(db, admin.id, "create_risk_rule", "risk_control_rule", row.id, {"keywords": ", ".join(parsed_keywords)})
    db.commit()
    return RedirectResponse("/admin/risk-control/page", status_code=303)


@router.post("/risk-control/{rule_id}/update/form")
def update_risk_rule_form(
    rule_id: int,
    keywords: str = Form(...),
    error_message: str = Form(...),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    row = db.query(RiskControlRule).filter(RiskControlRule.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    parsed_keywords, message = _validate_risk_rule_form(keywords, error_message)
    row.keywords = parsed_keywords
    row.error_message = message
    row.operator_user_id = admin.id
    db.add(row)
    write_audit(db, admin.id, "update_risk_rule", "risk_control_rule", row.id, {"keywords": ", ".join(parsed_keywords)})
    db.commit()
    return RedirectResponse("/admin/risk-control/page", status_code=303)


@router.post("/risk-control/{rule_id}/toggle/form")
def toggle_risk_rule_form(rule_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(RiskControlRule).filter(RiskControlRule.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    if provider_is_retired(row.provider_name):
        raise HTTPException(status_code=400, detail="该渠道已下线，不能重新启用")
    row.status = "disabled" if row.status == "active" else "active"
    row.operator_user_id = admin.id
    db.add(row)
    write_audit(db, admin.id, "toggle_risk_rule", "risk_control_rule", row.id, {"status": row.status})
    db.commit()
    return RedirectResponse("/admin/risk-control/page", status_code=303)


@router.post("/risk-control/{rule_id}/delete/form")
def delete_risk_rule_form(rule_id: int, admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    row = db.query(RiskControlRule).filter(RiskControlRule.id == rule_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="规则不存在")
    write_audit(db, admin.id, "delete_risk_rule", "risk_control_rule", row.id, {"keywords": ", ".join(parse_keywords(row.keywords))})
    db.delete(row)
    db.commit()
    return RedirectResponse("/admin/risk-control/page", status_code=303)


@router.post("/settings/update/form")
def settings_update_form(
    max_running_jobs: str = Form(""),
    submit_max_attempts: str = Form(""),
    download_retry_delays_seconds: str = Form(""),
    public_download_token_ttl_seconds: str = Form(""),
    content_fallback_after_seconds: str = Form(""),
    default_daily_job_limit: str = Form(""),
    default_concurrent_job_limit: str = Form(""),
    default_min_submit_interval_seconds: str = Form(""),
    registration_enabled: str = Form("0"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    values = {
        "max_running_jobs": max_running_jobs,
        "submit_max_attempts": submit_max_attempts,
        "download_retry_delays_seconds": download_retry_delays_seconds,
        "public_download_token_ttl_seconds": public_download_token_ttl_seconds,
        "content_fallback_after_seconds": content_fallback_after_seconds,
        "default_daily_job_limit": default_daily_job_limit,
        "default_concurrent_job_limit": default_concurrent_job_limit,
        "default_min_submit_interval_seconds": default_min_submit_interval_seconds,
        "registration_enabled": registration_enabled,
    }
    try:
        for key, value in values.items():
            upsert_system_setting(db, key, value, admin.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    write_audit(db, admin.id, "update_system_settings", "app_setting", None, values)
    db.commit()
    return RedirectResponse("/admin/settings/page", status_code=303)


@router.get("/api-call-logs/page", response_class=HTMLResponse)
def api_call_logs_page(request: Request, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    paged = _pagination(db.query(APICallLog).order_by(APICallLog.id.desc()), page, per_page)
    return render(request, "admin/api_calls.html", current_user=admin, rows=paged["items"], pagination=paged)


@router.get("/api-call-logs")
def api_call_logs(page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100), _: User = Depends(require_super_admin), db: Session = Depends(get_db)) -> dict:
    paged = _pagination(db.query(APICallLog).order_by(APICallLog.id.desc()), page, per_page)
    return {**{k: v for k, v in paged.items() if k != "items"}, "items": [{"id": row.id, "user_id": row.user_id, "job_id": row.job_id, "provider_key_id": row.provider_key_id, "endpoint": row.endpoint, "method": row.method, "status_code": row.status_code, "success": row.success, "latency_ms": row.latency_ms, "error_text": row.error_text, "created_at": format_shanghai_datetime(row.created_at)} for row in paged["items"]]}


@router.post("/api-call-logs/clear/form")
def clear_api_call_logs_form(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    count = int(db.query(func.count(APICallLog.id)).scalar() or 0)
    db.query(APICallLog).delete(synchronize_session=False)
    write_audit(db, admin.id, "clear_api_call_logs", "api_call_log", None, {"count": count})
    db.commit()
    return RedirectResponse("/admin/api-call-logs/page", status_code=303)


@router.get("/audit-logs/page", response_class=HTMLResponse)
def audit_logs_page(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    group: str = Query("important"),
    admin: User = Depends(require_super_admin),
    db: Session = Depends(get_db),
):
    if group not in AUDIT_GROUPS:
        group = "important"
    query = db.query(AuditLog)
    group_cfg = AUDIT_GROUPS[group]
    if group_cfg.get("exclude_noise"):
        query = query.filter(~AuditLog.action.in_(AUDIT_NOISE_ACTIONS))
    actions = group_cfg.get("actions")
    if actions:
        query = query.filter(AuditLog.action.in_(actions))
    paged = _pagination(query.order_by(AuditLog.id.desc()), page, per_page)
    display_rows = _audit_display_rows(db, paged["items"])
    noise_count = int(db.query(func.count(AuditLog.id)).filter(AuditLog.action.in_(AUDIT_NOISE_ACTIONS)).scalar() or 0)
    return render(
        request,
        "admin/audit_logs.html",
        current_user=admin,
        rows=display_rows,
        pagination=paged,
        group=group,
        groups=AUDIT_GROUPS,
        noise_count=noise_count,
    )


@router.post("/audit-logs/cleanup-noise/form")
def cleanup_noise_audit_logs_form(admin: User = Depends(require_super_admin), db: Session = Depends(get_db)):
    count = int(db.query(func.count(AuditLog.id)).filter(AuditLog.action.in_(AUDIT_NOISE_ACTIONS)).scalar() or 0)
    if count:
        db.query(AuditLog).filter(AuditLog.action.in_(AUDIT_NOISE_ACTIONS)).delete(synchronize_session=False)
    write_audit(db, admin.id, "cleanup_noise_audit_logs", "audit_log", None, {"count": count})
    db.commit()
    return RedirectResponse("/admin/audit-logs/page", status_code=303)


