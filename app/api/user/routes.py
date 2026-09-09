from __future__ import annotations

import zipfile
from datetime import date
from math import ceil
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.timezone import date_bounds_utc, format_shanghai_datetime, shanghai_now
from app.services.crypto import decrypt_secret
from app.deps import get_current_user, get_db
from app.models.tables import APICallLog, Job, JobBatch, JobEvent, JobFile, PackageQuotaLedger, ProviderKey, QuotaLedger, QuotaPlan, QuotaRequest, QuotaWallet, ReferenceImagePreset, User, UserProfile, UserQuotaPlanAssignment
from app.services.download_names import attachment_disposition, job_video_download_filename
from app.services.jobs import (
    can_pause,
    can_redownload,
    can_resume,
    create_jobs_batch_and_reserve,
    get_output_file,
    normalize_prompt_list,
    queue_text,
    serialize_event,
    serialize_file,
    serialize_job,
    make_public_remote_download_token,
    utcnow,
    verify_public_remote_download_token,
)
from app.services.sora_api import UpstreamError, iter_video_stream, open_video_stream
from app.services.provider_keys import provider_is_retired, PROVIDER_LABELS, PROVIDER_SECONDS, model_id_for_seconds, normalize_provider_name, provider_supports_seconds, select_provider_key
from app.services.risk_control import match_risk_message
from app.services.quota_plans import plan_quota_amount, quota_totals_for_user, refresh_user_packages
from app.services.system_settings import get_system_setting_int
from app.services.user_admin import user_display_name
from app.services.reference_images import (
    IMAGE_FETCH_TIMEOUT,
    SUPPORTED_SECONDS,
    SUPPORTED_VIDEO_SIZES,
    dimensions_match_size_ratio,
    fetch_image_dimensions,
    supported_reference_size_label,
    normalize_public_image_url,
    validate_seconds,
)

router = APIRouter(prefix="/app", tags=["app"])
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
REFERENCE_IMAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SoraDispatch/1.0)",
    "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
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
    downloadable = {batch_id: set() for batch_id in ids}
    output_rows = db.query(Job.batch_id, Job.id, JobFile.file_path).join(JobFile, JobFile.job_id == Job.id).filter(Job.batch_id.in_(ids), Job.status == "completed", JobFile.file_type == "output_video").all()
    for batch_id, job_id, file_path in output_rows:
        if Path(file_path).is_file():
            downloadable[int(batch_id)].add(int(job_id))
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
        parts = []
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
        downloadable_count = len(downloadable.get(batch_id, set()))
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
            "downloadable_count": downloadable_count,
        }
    return summaries


def _serialize_batch(batch: JobBatch, summary: dict | None = None) -> dict:
    summary = summary or {}
    return {
        "id": batch.id,
        "batch_code": batch.batch_code,
        "batch_name": batch.batch_name,
        "display_name": batch.batch_name or batch.batch_code,
        "product_name": batch.product_name,
        "region_name": batch.region_name,
        "total_count": batch.total_count,
        "created_at": format_shanghai_datetime(batch.created_at),
        "created_at_short": format_shanghai_datetime(batch.created_at),
        "summary": summary.get("text", "-"),
        "state_label": summary.get("state_label", "-"),
        "counts": summary.get("counts", {}),
        "active_count": summary.get("active_count", 0),
        "completed_count": summary.get("completed_count", 0),
        "failed_count": summary.get("failed_count", 0),
        "downloadable_count": summary.get("downloadable_count", 0),
    }


def _serialize_api_call(call: APICallLog) -> dict:
    return {
        "id": call.id,
        "method": call.method,
        "endpoint": call.endpoint,
        "status_code": call.status_code,
        "success": bool(call.success),
        "latency_ms": call.latency_ms,
        "request_summary": call.request_summary,
        "response_summary": call.response_summary,
        "error_text": call.error_text,
        "created_at": format_shanghai_datetime(call.created_at),
    }


def _save_reference_upload(file: UploadFile | None) -> Path | None:
    if not file or not file.filename:
        return None
    suffix = (Path(file.filename).suffix or ".bin").lower()
    if suffix not in SUPPORTED_IMAGE_SUFFIXES:
        raise HTTPException(status_code=400, detail="参考图仅支持 png、jpg、jpeg 或 webp 格式")
    dest = settings.files_upload_dir / f"{uuid4().hex}{suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with dest.open("wb") as fh:
        while True:
            chunk = file.file.read(1024 * 1024)
            if not chunk:
                break
            total_bytes += len(chunk)
            if total_bytes > settings.reference_image_max_bytes:
                fh.close()
                dest.unlink(missing_ok=True)
                limit_mb = max(1, settings.reference_image_max_bytes // (1024 * 1024))
                raise HTTPException(status_code=400, detail=f"参考图大小不能超过 {limit_mb}MB")
            fh.write(chunk)
    return dest


def _parse_video_size(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = size.lower().split("x", 1)
        return int(width_text), int(height_text)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="视频尺寸格式无效") from exc


def _validate_job_form(seconds: int | str | None, size: str | None) -> int:
    try:
        parsed_seconds = validate_seconds(seconds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not size or size not in SUPPORTED_VIDEO_SIZES:
        raise HTTPException(status_code=400, detail="请选择支持的 720p 尺寸")
    return parsed_seconds


def _validate_video_size(size: str | None) -> str:
    if not size or size not in SUPPORTED_VIDEO_SIZES:
        raise HTTPException(status_code=400, detail="请选择支持的 720p 尺寸")
    return size


def _risk_failure_map(db: Session, prompts: list[str] | tuple[str, ...]) -> dict[int, str]:
    failures: dict[int, str] = {}
    for index, prompt in enumerate(prompts):
        message = match_risk_message(db, [prompt])
        if message:
            failures[index] = message
    return failures


def _model_options(db: Session) -> list[dict]:
    options: list[dict] = []
    provider_keys = (
        db.query(ProviderKey)
        .filter(ProviderKey.status == "active")
        .order_by(ProviderKey.id.asc())
        .all()
    )
    for provider_key in provider_keys:
        provider_name = normalize_provider_name(provider_key.provider_name)
        if provider_is_retired(provider_name):
            continue
        seconds_values = PROVIDER_SECONDS.get(provider_name, ())
        for seconds in seconds_values:
            model_id = model_id_for_seconds(provider_key, seconds)
            if not model_id:
                continue
            options.append(
                {
                    "value": f"key:{provider_key.id}:{seconds}",
                    "provider_key_id": provider_key.id,
                    "provider_name": provider_name,
                    "provider_label": provider_key.name,
                    "seconds": seconds,
                    "model_id": model_id,
                    "label": f"{provider_key.name.strip()} · {model_id} · {seconds} 秒",
                }
            )
    return options


def _parse_model_choice(model_choice: str | None, seconds: int | str | None) -> tuple[str, int, int | None]:
    text = str(model_choice or "").strip()
    if text.startswith("key:"):
        parts = text.split(":")
        if len(parts) != 3:
            raise HTTPException(status_code=400, detail="请选择有效模型")
        try:
            provider_key_id = int(parts[1])
            parsed_seconds = int(parts[2])
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="请选择有效模型") from exc
        return "", parsed_seconds, provider_key_id
    if ":" in text:
        provider_name, seconds_text = text.split(":", 1)
        provider_name = normalize_provider_name(provider_name)
        try:
            parsed_seconds = int(seconds_text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="请选择有效模型") from exc
        if provider_is_retired(provider_name):
            raise HTTPException(status_code=400, detail="该渠道已下线，请选择其他模型")
        if not provider_supports_seconds(provider_name, parsed_seconds):
            raise HTTPException(status_code=400, detail="所选渠道不支持这个时长")
        return provider_name, parsed_seconds, None
    parsed_seconds = _validate_job_form(seconds, "720x1280")
    return "sora_api", parsed_seconds, None


def _assert_requested_key_available(db: Session, provider_key_id: int | None) -> None:
    if provider_key_id:
        key = db.query(ProviderKey).filter(ProviderKey.id == provider_key_id).first()
        if key and provider_is_retired(key.provider_name):
            raise HTTPException(status_code=400, detail="该渠道已下线，请选择其他模型")


def _select_model_provider_key(db: Session, provider_name: str, seconds: int, provider_key_id: int | None) -> ProviderKey | None:
    if provider_key_id:
        provider_key = (
            db.query(ProviderKey)
            .filter(ProviderKey.id == provider_key_id, ProviderKey.status == "active")
            .first()
        )
        if not provider_key:
            return None
        if provider_is_retired(provider_key.provider_name):
            raise HTTPException(status_code=400, detail="该渠道已下线，请选择其他模型")
        if not provider_supports_seconds(provider_key.provider_name, int(seconds)):
            return None
        if not model_id_for_seconds(provider_key, int(seconds)):
            return None
        return provider_key
    return select_provider_key(db, provider_name, seconds)


def _validate_reference_image(reference_path: Path | None, size: str) -> None:
    if not reference_path:
        return
    try:
        with Image.open(reference_path) as image:
            actual_width, actual_height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="参考图无法读取") from exc
    if not dimensions_match_size_ratio(actual_width, actual_height, size):
        raise HTTPException(
            status_code=400,
            detail=f"参考图尺寸不匹配 {size}，当前 {actual_width}x{actual_height}，请使用 {supported_reference_size_label()}。",
        )


def _parse_reference_preset_id(value: str | int | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="参考图预设无效") from exc


def _resolve_reference_image_url(
    db: Session,
    current_user: User,
    reference_preset_id: str | int | None,
    reference_image_url: str | None,
    size: str,
    confirmed_image_urls: set[str] | None = None,
    *,
    require_matching_size: bool = True,
) -> tuple[str | None, str | None, int | None, int | None]:
    preset_id = _parse_reference_preset_id(reference_preset_id)
    name: str | None = None
    width: int | None = None
    height: int | None = None
    url: str | None = None

    if preset_id:
        preset = (
            db.query(ReferenceImagePreset)
            .filter(
                ReferenceImagePreset.id == preset_id,
                ReferenceImagePreset.status == "active",
                or_(ReferenceImagePreset.owner_user_id.is_(None), ReferenceImagePreset.owner_user_id == current_user.id),
            )
            .first()
        )
        if not preset:
            raise HTTPException(status_code=400, detail="参考图预设不存在或不可用")
        url = preset.image_url
        name = preset.name
        width = preset.width
        height = preset.height
    else:
        try:
            url = normalize_public_image_url(reference_image_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        name = "图片链接参考图" if url else None

    if not url:
        return None, None, None, None

    # Confirmation applies only to this direct URL, never to a preset or its permissions.
    if not preset_id and url in (confirmed_image_urls or set()):
        return url, name, None, None

    if not width or not height:
        try:
            width, height, _, _ = fetch_image_dimensions(url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    _ensure_reference_dimensions(width, height)
    if require_matching_size and not dimensions_match_size_ratio(width, height, size):
        raise HTTPException(
            status_code=400,
            detail=f"参考图尺寸不匹配 {size}，当前 {width}x{height}，请使用 {supported_reference_size_label()}。",
        )
    return url, name, width, height


def _resolve_reference_video_url(reference_video_url: str | None, provider_name: str | None) -> str | None:
    value = str(reference_video_url or "").strip()
    if not value:
        return None
    provider = normalize_provider_name(provider_name)
    if provider not in {"veo_omni", "wuyin_omni"}:
        raise HTTPException(status_code=400, detail="参考视频仅支持 Omni 渠道")
    parsed = urlparse(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="参考视频必须是有效的公开 HTTP/HTTPS 链接")
    return value


def _resolve_job_reference_materials(
    db: Session,
    current_user: User,
    provider_name: str | None,
    size: str,
    *,
    reference_preset_id: str | int | None = None,
    reference_image_url: str | None = None,
    reference_video_url: str | None = None,
    omni_mode: str | None = None,
    omni_reference_preset_ids: list[str] | None = None,
    omni_reference_image_urls: list[str] | None = None,
    omni_reference_video_url: str | None = None,
    confirmed_reference_image_urls: list[str] | None = None,
) -> tuple[list[tuple[str, str | None, int | None, int | None]], str | None]:
    provider = normalize_provider_name(provider_name)
    try:
        confirmed = {url for value in (confirmed_reference_image_urls or []) if (url := normalize_public_image_url(value))}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if provider not in {"veo_omni", "wuyin_omni"}:
        image = _resolve_reference_image_url(db, current_user, reference_preset_id, reference_image_url, size, confirmed)
        video = _resolve_reference_video_url(reference_video_url, provider) if reference_video_url else None
        return ([image] if image[0] else []), video

    if provider == "veo_omni" and (reference_video_url or omni_reference_video_url or (omni_mode and omni_mode != "multi_image")):
        raise HTTPException(status_code=400, detail="VEO Omni 视频编辑已下线，请使用多图生视频")

    preset_ids = [str(value).strip() for value in (omni_reference_preset_ids or []) if str(value).strip()]
    image_urls = [str(value).strip() for value in (omni_reference_image_urls or []) if str(value).strip()]
    if reference_preset_id:
        preset_ids.append(str(reference_preset_id).strip())
    if reference_image_url and str(reference_image_url).strip():
        image_urls.append(str(reference_image_url).strip())

    maximum = 6 if provider == "veo_omni" else 1
    if len(preset_ids) + len(image_urls) > maximum:
        label = "VEO Omni" if provider == "veo_omni" else "Wuyin Omni"
        raise HTTPException(status_code=400, detail=f"{label} 最多支持 {maximum} 张参考图")

    resolved: list[tuple[str, str | None, int | None, int | None]] = []
    seen: set[str] = set()
    for preset_id in preset_ids:
        item = _resolve_reference_image_url(db, current_user, preset_id, None, size, require_matching_size=False)
        if item[0] and item[0] not in seen:
            resolved.append(item)
            seen.add(item[0])
    for image_url in image_urls:
        item = _resolve_reference_image_url(db, current_user, None, image_url, size, confirmed, require_matching_size=False)
        if item[0] and item[0] not in seen:
            resolved.append(item)
            seen.add(item[0])
    if len(resolved) > maximum:
        raise HTTPException(status_code=400, detail=f"当前渠道最多支持 {maximum} 张参考图")

    video_value = omni_reference_video_url or reference_video_url
    video = _resolve_reference_video_url(video_value, provider) if video_value else None
    if provider == "veo_omni" and not resolved:
        raise HTTPException(status_code=400, detail="VEO Omni 多图生视频至少需要 1 张参考图")
    return resolved, video


def _reference_preset_query_for_user(db: Session, user_id: int):
    return (
        db.query(ReferenceImagePreset)
        .filter(or_(ReferenceImagePreset.owner_user_id.is_(None), ReferenceImagePreset.owner_user_id == user_id))
        .order_by(ReferenceImagePreset.owner_user_id.asc().nullsfirst(), ReferenceImagePreset.sort_order.asc(), ReferenceImagePreset.id.desc())
    )


def _ensure_reference_dimensions(width: int, height: int) -> None:
    # Presets are channel-neutral; generation validates the selected provider's limits.
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=400, detail="参考图尺寸无效")


def _parse_reference_sort_order(value: str | int | None) -> int:
    try:
        return max(0, int(str(value or "100").strip()))
    except ValueError:
        return 100


def _apply_reference_preset_values(row: ReferenceImagePreset, name: str, image_url: str, sort_order: str | int | None) -> None:
    from app.services.reference_images import aspect_ratio_for_dimensions

    try:
        normalized_url = normalize_public_image_url(image_url)
        width, height, _, _ = fetch_image_dimensions(normalized_url)
        _ensure_reference_dimensions(width, height)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="棰勮鍚嶇О涓嶈兘涓虹┖")
    row.name = clean_name[:128]
    row.image_url = normalized_url
    row.width = width
    row.height = height
    row.aspect_ratio = aspect_ratio_for_dimensions(width, height)
    row.sort_order = _parse_reference_sort_order(sort_order)


@router.get("", response_class=HTMLResponse)
def app_dashboard_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if refresh_user_packages(db, int(current_user.id)):
        db.commit()
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == current_user.id).first()
    quota_stats = quota_totals_for_user(db, int(current_user.id), wallet)
    recent_jobs = db.query(Job).filter(Job.user_id == current_user.id).order_by(Job.id.desc()).limit(4).all()
    reference_presets = _reference_preset_query_for_user(db, current_user.id).filter(ReferenceImagePreset.status == "active").all()
    return render(
        request,
        "app/dashboard.html",
        current_user=current_user,
        wallet=wallet,
        quota_stats=quota_stats,
        jobs=recent_jobs,
        default_seconds=settings.default_video_seconds,
        default_size=settings.default_video_size,
        supported_seconds=sorted({seconds for values in PROVIDER_SECONDS.values() for seconds in values}),
        model_options=_model_options(db),
        reference_presets=reference_presets,
        new_request_id=str(uuid4()),
    )


@router.get("/reference-images/page", response_class=HTMLResponse)
def reference_images_page(request: Request, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.owner_user_id == current_user.id).order_by(ReferenceImagePreset.sort_order.asc(), ReferenceImagePreset.id.desc()).all()
    common_count = db.query(func.count(ReferenceImagePreset.id)).filter(ReferenceImagePreset.owner_user_id.is_(None), ReferenceImagePreset.status == "active").scalar() or 0
    return render(request, "app/reference_images.html", current_user=current_user, rows=rows, common_count=common_count)


@router.post("/reference-images/form")
def create_reference_image_form(
    name: str = Form(...),
    image_url: str = Form(...),
    sort_order: str = Form("100"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = ReferenceImagePreset(owner_user_id=current_user.id, status="active")
    _apply_reference_preset_values(row, name, image_url, sort_order)
    db.add(row)
    db.commit()
    return RedirectResponse("/app/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/update/form")
def update_reference_image_form(
    preset_id: int,
    name: str = Form(...),
    image_url: str = Form(...),
    sort_order: str = Form("100"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id, ReferenceImagePreset.owner_user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    _apply_reference_preset_values(row, name, image_url, sort_order)
    db.add(row)
    db.commit()
    return RedirectResponse("/app/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/toggle/form")
def toggle_reference_image_form(preset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id, ReferenceImagePreset.owner_user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    row.status = "disabled" if row.status == "active" else "active"
    db.add(row)
    db.commit()
    return RedirectResponse("/app/reference-images/page", status_code=303)


@router.post("/reference-images/{preset_id}/delete/form")
def delete_reference_image_form(preset_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.query(ReferenceImagePreset).filter(ReferenceImagePreset.id == preset_id, ReferenceImagePreset.owner_user_id == current_user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Preset not found")
    db.delete(row)
    db.commit()
    return RedirectResponse("/app/reference-images/page", status_code=303)


@router.get("/dashboard")
def dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if refresh_user_packages(db, int(current_user.id)):
        db.commit()
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == current_user.id).first()
    quota_stats = quota_totals_for_user(db, int(current_user.id), wallet)
    recent_jobs = db.query(Job).filter(Job.user_id == current_user.id).order_by(Job.id.desc()).limit(4).all()
    return {
        "user": current_user.username,
        "remaining_quota": wallet.remaining_quota if wallet else 0,
        "available_quota": quota_stats["total_available"],
        "total_remaining_quota": quota_stats["total_remaining"],
        "total_reserved_quota": quota_stats["total_reserved"],
        "personal_remaining_quota": quota_stats["personal_remaining"],
        "personal_available_quota": quota_stats["personal_available"],
        "personal_reserved_quota": quota_stats["personal_reserved"],
        "package_remaining_quota": quota_stats["package_remaining"],
        "package_available_quota": quota_stats["package_available"],
        "package_reserved_quota": quota_stats["package_reserved"],
        "total_used": wallet.total_used if wallet else 0,
        "recent_jobs": [serialize_job(job, get_output_file(db, job.id)) for job in recent_jobs],
    }


@router.get("/plaza/page", response_class=HTMLResponse)
def plaza_page(
    request: Request,
    product_name: str | None = Query(default=None),
    region_name: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    per_page = min(max(int(per_page or 20), 1), 100)
    product_filter = " ".join(str(product_name or "").split()).strip()
    region_filter = " ".join(str(region_name or "").split()).strip()
    filters = [Job.status == "completed", User.showcase_enabled.is_(True)]
    if product_filter:
        filters.append(Job.product_name.ilike(f"%{product_filter}%"))
    if region_filter:
        filters.append(Job.region_name.ilike(f"%{region_filter}%"))
    total_items = (
        db.query(func.count(func.distinct(Job.id)))
        .join(User, User.id == Job.user_id)
        .join(JobFile, and_(JobFile.job_id == Job.id, JobFile.file_type == "output_video"))
        .filter(*filters)
        .scalar()
        or 0
    )
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    page = min(page, total_pages)
    offset = (page - 1) * per_page
    jobs = (
        db.query(Job, User, JobFile, UserProfile)
        .join(User, User.id == Job.user_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .join(JobFile, and_(JobFile.job_id == Job.id, JobFile.file_type == "output_video"))
        .filter(*filters)
        .order_by(Job.id.desc())
        .offset(offset)
        .limit(per_page)
        .all()
    )
    cards = [
        {
            "job_id": job.id,
            "user_id": owner.id,
            "creator": user_display_name(owner),
            "product_name": job.product_name,
            "region_name": job.region_name,
            "prompt": job.prompt,
            "status": job.status,
            "size": job.size,
            "seconds": job.seconds,
            "model": job.model,
            "output_file_id": output_file.id,
            "local_download_url": f"/app/files/{output_file.id}/download",
            "created_at": format_shanghai_datetime(job.created_at),
            "created_date": format_shanghai_datetime(job.created_at)[:10],
            "is_private_protected": bool(job.is_private_protected),
        }
        for job, owner, output_file, profile in jobs
        for _ in (setattr(owner, "display_name", (profile.display_name or "").strip() if profile else ""),)
    ]
    return render(
        request,
        "app/plaza.html",
        current_user=current_user,
        cards=cards,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_items=total_items,
        has_prev=page > 1,
        has_next=page < total_pages,
        product_name=product_filter,
        region_name=region_filter,
        per_page_options=[20, 40, 60, 100],
        per_page_storage_key="plaza.per_page",
    )


@router.get("/plaza/jobs/{job_id}")
def plaza_job_detail(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    row = (
        db.query(Job, User, UserProfile)
        .join(User, User.id == Job.user_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .filter(Job.id == job_id, Job.status == "completed", User.showcase_enabled.is_(True))
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    job, owner, profile = row
    setattr(owner, "display_name", (profile.display_name or "").strip() if profile else "")
    output_file = get_output_file(db, job.id)
    if not output_file:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job.id,
        "creator": user_display_name(owner),
        "product_name": job.product_name,
        "region_name": job.region_name,
        "prompt": job.prompt,
        "size": job.size,
        "seconds": job.seconds,
        "model": job.model,
        "created_at": format_shanghai_datetime(job.created_at),
        "is_private_protected": bool(job.is_private_protected),
        "output_file": serialize_file(output_file),
    }


@router.get("/library/page", response_class=HTMLResponse)
def library_page(
    request: Request,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    product_name: str | None = Query(default=None),
    region_name: str | None = Query(default=None),
    starred: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Job, JobFile)
        .join(JobFile, and_(JobFile.job_id == Job.id, JobFile.file_type == "output_video"))
        .filter(Job.user_id == current_user.id, Job.status == "completed")
    )
    if starred:
        query = query.filter(Job.is_starred.is_(True))
    product_filter = " ".join(str(product_name or "").split()).strip()
    region_filter = " ".join(str(region_name or "").split()).strip()
    if product_filter:
        query = query.filter(Job.product_name.ilike(f"%{product_filter}%"))
    if region_filter:
        query = query.filter(Job.region_name.ilike(f"%{region_filter}%"))
    parsed_start = None
    parsed_end = None
    if start_date:
        try:
            parsed_start = date.fromisoformat(start_date)
            start_utc, _ = date_bounds_utc(parsed_start)
            query = query.filter(Job.created_at >= start_utc)
        except ValueError:
            parsed_start = None
    if end_date:
        try:
            parsed_end = date.fromisoformat(end_date)
            _, end_utc = date_bounds_utc(parsed_end)
            query = query.filter(Job.created_at < end_utc)
        except ValueError:
            parsed_end = None
    query = query.order_by(Job.completed_at.desc().nullslast(), Job.id.desc())
    paged = _pagination(query, page, per_page)
    cards = []
    for job, output_file in paged["items"]:
        token = make_public_remote_download_token(job.id, job.remote_task_id, get_system_setting_int(db, "public_download_token_ttl_seconds", settings.public_download_token_ttl_seconds))
        cards.append({
            "job_id": job.id,
            "prompt": job.prompt,
            "product_name": job.product_name,
            "region_name": job.region_name,
            "size": job.size,
            "seconds": job.seconds,
            "model": job.model,
            "output_file_id": output_file.id,
            "created_at": format_shanghai_datetime(job.created_at),
            "created_date": format_shanghai_datetime(job.created_at)[:10],
            "completed_at": format_shanghai_datetime(job.completed_at),
            "is_starred": bool(job.is_starred),
            "starred_at": format_shanghai_datetime(job.starred_at),
            "is_private_protected": bool(job.is_private_protected),
            "private_protected_at": format_shanghai_datetime(job.private_protected_at),
            "local_download_url": f"/app/files/{output_file.id}/download",
            "remote_download_url": f"/app/jobs/{job.id}/remote-download" if job.remote_task_id else None,
            "public_remote_download_url": f"/app/jobs/{job.id}/public-remote-download?token={token}" if token else None,
        })
    return render(
        request,
        "app/library.html",
        current_user=current_user,
        cards=cards,
        pagination=paged,
        start_date=start_date or "",
        end_date=end_date or "",
        product_name=product_filter,
        region_name=region_filter,
        starred=starred,
        per_page_options=[20, 40, 60, 100],
        per_page_storage_key="library.per_page",
    )


def _parse_bulk_job_ids(value: str) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for item in str(value or "").replace("，", ",").split(","):
        text = item.strip()
        if not text:
            continue
        if not text.isdigit():
            raise HTTPException(status_code=400, detail="选择的作品无效")
        job_id = int(text)
        if job_id > 0 and job_id not in seen:
            ids.append(job_id)
            seen.add(job_id)
    if not ids:
        raise HTTPException(status_code=400, detail="请选择要下载的作品")
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="一次最多下载 100 个作品")
    return ids


def _unique_zip_name(name: str, used: set[str]) -> str:
    path = Path(name)
    stem = path.stem or "video"
    suffix = path.suffix or ".mp4"
    candidate = f"{stem}{suffix}"
    index = 2
    while candidate in used:
        candidate = f"{stem} ({index}){suffix}"
        index += 1
    used.add(candidate)
    return candidate


def _clean_zip_label(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    for char in '\\/:*?"<>|\r\n\t':
        text = text.replace(char, "-")
    text = text.strip(" .-_")
    return text[:80] or fallback


def _build_jobs_zip_response(
    db: Session,
    rows: list[tuple[Job, JobFile]],
    zip_prefix: str,
    download_filename: str,
    skip_missing_files: bool = False,
) -> FileResponse:
    settings.files_temp_dir.mkdir(parents=True, exist_ok=True)
    zip_path = settings.files_temp_dir / f"{zip_prefix}_{uuid4().hex}.zip"
    used_names: set[str] = set()
    written = 0
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as archive:
            for job, output_file in rows:
                file_path = Path(output_file.file_path)
                if not file_path.exists() or not file_path.is_file():
                    if skip_missing_files:
                        continue
                    raise HTTPException(status_code=404, detail=f"作品 #{job.id} 的本地文件不存在")
                archive.write(file_path, _unique_zip_name(job_video_download_filename(db, job), used_names))
                written += 1
        if written <= 0:
            raise HTTPException(status_code=404, detail="暂无可下载视频")
    except Exception:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)
        raise

    return FileResponse(
        path=zip_path,
        filename=download_filename,
        media_type="application/zip",
        background=BackgroundTask(lambda: zip_path.unlink(missing_ok=True)),
    )


@router.get("/library/bulk-download")
def library_bulk_download(
    job_ids: str = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    ids = _parse_bulk_job_ids(job_ids)
    rows = (
        db.query(Job, JobFile)
        .join(JobFile, and_(JobFile.job_id == Job.id, JobFile.file_type == "output_video"))
        .filter(Job.user_id == current_user.id, Job.status == "completed", Job.id.in_(ids))
        .all()
    )
    by_id = {int(job.id): (job, output_file) for job, output_file in rows}
    missing = [job_id for job_id in ids if job_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail=f"部分作品不存在或无权下载：{', '.join(map(str, missing[:10]))}")

    date_text = shanghai_now().strftime("%Y%m%d_%H%M%S")
    ordered_rows = [by_id[job_id] for job_id in ids]
    return _build_jobs_zip_response(
        db,
        ordered_rows,
        f"library_bulk_{current_user.id}",
        f"我的作品_{date_text}_{len(ids)}个.zip",
    )


@router.get("/quota/page", response_class=HTMLResponse)
def quota_page(request: Request, page: int = Query(default=1, ge=1), per_page: int = Query(default=20, ge=1, le=100), current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if refresh_user_packages(db, int(current_user.id)):
        db.commit()
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == current_user.id).first()
    personal_rows = db.query(QuotaLedger).filter(QuotaLedger.user_id == current_user.id).order_by(QuotaLedger.id.desc()).limit(100).all()
    package_ledger_rows = db.query(PackageQuotaLedger).filter(PackageQuotaLedger.user_id == current_user.id).order_by(PackageQuotaLedger.id.desc()).limit(100).all()
    ledger_rows = []
    for row in personal_rows:
        ledger_rows.append({"id": row.id, "source": "个人额度", "change_amount": row.change_amount, "action": row.action, "job_id": row.job_id, "note": row.note, "created_at": row.created_at})
    for row in package_ledger_rows:
        ledger_rows.append({"id": row.id, "source": "套餐额度", "change_amount": row.change_amount, "action": row.action, "job_id": row.job_id, "note": row.note, "created_at": row.created_at})
    ledger_rows.sort(key=lambda item: item["created_at"], reverse=True)
    total_items = len(ledger_rows)
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    page = min(max(int(page or 1), 1), total_pages)
    paged = {
        "items": ledger_rows[(page - 1) * per_page:page * per_page],
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }
    quota_requests = db.query(QuotaRequest).filter(QuotaRequest.user_id == current_user.id).order_by(QuotaRequest.id.desc()).limit(10).all()
    package_rows = (
        db.query(UserQuotaPlanAssignment, QuotaPlan)
        .join(QuotaPlan, QuotaPlan.id == UserQuotaPlanAssignment.plan_id)
        .filter(UserQuotaPlanAssignment.user_id == current_user.id, UserQuotaPlanAssignment.status == "active", QuotaPlan.status == "active")
        .order_by(UserQuotaPlanAssignment.id.asc())
        .all()
    )
    package_available = sum(max(int(assignment.remaining_quota or 0) - int(assignment.reserved_quota or 0), 0) for assignment, _plan in package_rows)
    package_remaining = sum(int(assignment.remaining_quota or 0) for assignment, _plan in package_rows)
    package_reserved = sum(int(assignment.reserved_quota or 0) for assignment, _plan in package_rows)
    today_start, today_end = date_bounds_utc(shanghai_now().date())
    package_today_usage = db.query(func.count(PackageQuotaLedger.id)).filter(PackageQuotaLedger.user_id == current_user.id, PackageQuotaLedger.action == "package_debit_create_success", PackageQuotaLedger.created_at >= today_start, PackageQuotaLedger.created_at < today_end).scalar() or 0
    package_today_refund = db.query(func.count(PackageQuotaLedger.id)).filter(PackageQuotaLedger.user_id == current_user.id, PackageQuotaLedger.action == "package_refund_failed_job", PackageQuotaLedger.created_at >= today_start, PackageQuotaLedger.created_at < today_end).scalar() or 0
    personal_today_usage = db.query(func.count(QuotaLedger.id)).filter(QuotaLedger.user_id == current_user.id, QuotaLedger.action == "debit_create_success", QuotaLedger.created_at >= today_start, QuotaLedger.created_at < today_end).scalar() or 0
    personal_today_refund = db.query(func.count(QuotaLedger.id)).filter(QuotaLedger.user_id == current_user.id, QuotaLedger.action == "refund_failed_job", QuotaLedger.created_at >= today_start, QuotaLedger.created_at < today_end).scalar() or 0
    personal_available = (int(wallet.remaining_quota or 0) - int(wallet.reserved_quota or 0)) if wallet else 0
    stats = {
        "remaining": wallet.remaining_quota if wallet else 0,
        "reserved": wallet.reserved_quota if wallet else 0,
        "available": personal_available,
        "package_available": package_available,
        "package_remaining": package_remaining,
        "package_reserved": package_reserved,
        "total_available": personal_available + package_available,
        "total_used": wallet.total_used if wallet else 0,
        "today_usage": max(int(personal_today_usage or 0) + int(package_today_usage or 0) - int(personal_today_refund or 0) - int(package_today_refund or 0), 0),
    }
    return render(request, "app/quota.html", current_user=current_user, wallet=wallet, rows=paged["items"], quota_requests=quota_requests, pagination=paged, stats=stats, package_rows=package_rows, plan_quota_amount=plan_quota_amount)


@router.post("/quota/requests/form")
def create_quota_request_form(
    amount: int = Form(...),
    reason: str = Form(""),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if amount <= 0:
        raise HTTPException(status_code=400, detail="申请额度必须大于 0")
    pending_count = db.query(func.count(QuotaRequest.id)).filter(QuotaRequest.user_id == current_user.id, QuotaRequest.status == "pending").scalar() or 0
    if pending_count >= 3:
        raise HTTPException(status_code=400, detail="待审批申请较多，请等待处理后再提交")
    row = QuotaRequest(user_id=current_user.id, amount=amount, reason=(reason or "").strip()[:500] or None, status="pending")
    db.add(row)
    db.commit()
    return RedirectResponse("/app/quota/page?notice=quota_request_created", status_code=303)


@router.get("/guide/page", response_class=HTMLResponse)
def guide_page(request: Request, current_user: User = Depends(get_current_user)):
    return render(request, "app/guide.html", current_user=current_user)


@router.get("/reference-image/dimensions")
def reference_image_dimensions(
    url: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
) -> dict:
    try:
        normalized = normalize_public_image_url(url)
        width, height, content_type, total = fetch_image_dimensions(normalized or "")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "url": normalized,
        "width": width,
        "height": height,
        "content_type": content_type,
        "bytes": total,
        "supported": dimensions_match_size_ratio(width, height, "720x1280") or dimensions_match_size_ratio(width, height, "1280x720"),
    }


@router.get("/reference-image/preview")
def reference_image_preview(
    url: str = Query(..., min_length=1),
    current_user: User = Depends(get_current_user),
) -> Response:
    try:
        normalized = normalize_public_image_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not normalized:
        raise HTTPException(status_code=400, detail="请填写图片链接")

    chunks: list[bytes] = []
    total = 0
    limit = int(settings.reference_image_max_bytes or 20 * 1024 * 1024)
    try:
        with httpx.Client(timeout=IMAGE_FETCH_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", normalized, headers=REFERENCE_IMAGE_HEADERS) as upstream:
                upstream.raise_for_status()
                content_type = upstream.headers.get("content-type") or "image/jpeg"
                if "svg" in content_type.lower() or not content_type.lower().startswith("image/"):
                    raise HTTPException(status_code=400, detail="图片链接不是有效的 PNG/JPG/WebP 直链")
                for chunk in upstream.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > limit:
                        raise HTTPException(status_code=400, detail="参考图过大")
                    chunks.append(chunk)
    except HTTPException:
        raise
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail="参考图无法加载") from exc

    return Response(
        b"".join(chunks),
        media_type=content_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/jobs/page", response_class=HTMLResponse)
def jobs_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    per_page = min(max(per_page, 1), 100)
    query = db.query(Job).filter(Job.user_id == current_user.id).order_by(Job.id.desc())
    total_items = query.order_by(None).count() or 0
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    page = min(page, total_pages)
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()
    pagination = {
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }
    queue_map = {job.id: queue_text(db, job) for job in jobs}
    batch_map = _job_batch_map(db, jobs)
    return render(request, "app/jobs.html", current_user=current_user, jobs=jobs, queue_map=queue_map, batch_map=batch_map, pagination=pagination)


@router.get("/jobs")
def list_jobs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    per_page = min(max(per_page, 1), 100)
    query = db.query(Job).filter(Job.user_id == current_user.id).order_by(Job.id.desc())
    total_items = query.order_by(None).count() or 0
    total_pages = max(1, ceil(total_items / per_page)) if total_items else 1
    page = min(page, total_pages)
    jobs = query.offset((page - 1) * per_page).limit(per_page).all()
    return {
        "items": [serialize_job(job, get_output_file(db, job.id)) for job in jobs],
        "page": page,
        "per_page": per_page,
        "total_items": total_items,
        "total_pages": total_pages,
        "has_prev": page > 1,
        "has_next": page < total_pages,
    }



@router.get("/job-batches/page", response_class=HTMLResponse)
def job_batches_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = db.query(JobBatch).filter(JobBatch.user_id == current_user.id).order_by(JobBatch.id.desc())
    paged = _pagination(query, page, per_page)
    summary_map = _batch_summary_map(db, {batch.id for batch in paged["items"]})
    return render(
        request,
        "app/job_batches.html",
        current_user=current_user,
        batches=paged["items"],
        summary_map=summary_map,
        pagination=paged,
    )


@router.get("/job-batches/{batch_id}/result", response_class=HTMLResponse)
def job_batch_result_page(
    batch_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    batch = db.query(JobBatch).filter(JobBatch.id == batch_id, JobBatch.user_id == current_user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs = (
        db.query(Job)
        .filter(Job.batch_id == batch.id, Job.user_id == current_user.id)
        .order_by(Job.batch_index.asc().nullslast(), Job.id.asc())
        .all()
    )
    queue_map = {job.id: queue_text(db, job) for job in jobs}
    summary_map = _batch_summary_map(db, {batch.id})
    return render(
        request,
        "app/job_batch_result.html",
        current_user=current_user,
        batch=batch,
        jobs=jobs,
        queue_map=queue_map,
        summary=summary_map.get(batch.id, {}),
    )


@router.get("/job-batches/{batch_id}")
def job_batch_detail(
    batch_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    batch = db.query(JobBatch).filter(JobBatch.id == batch_id, JobBatch.user_id == current_user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Job not found")
    jobs = (
        db.query(Job)
        .filter(Job.batch_id == batch.id, Job.user_id == current_user.id)
        .order_by(Job.batch_index.asc().nullslast(), Job.id.asc())
        .all()
    )
    summary = _batch_summary_map(db, {batch.id}).get(batch.id, {})
    return {
        "batch": _serialize_batch(batch, summary),
        "jobs": [{**serialize_job(job, get_output_file(db, job.id)), "queue_text": queue_text(db, job)} for job in jobs],
    }


@router.get("/job-batches/{batch_id}/download-zip")
def job_batch_download_zip(
    batch_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FileResponse:
    batch = db.query(JobBatch).filter(JobBatch.id == batch_id, JobBatch.user_id == current_user.id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Job not found")
    rows = (
        db.query(Job, JobFile)
        .join(JobFile, and_(JobFile.job_id == Job.id, JobFile.file_type == "output_video"))
        .filter(Job.batch_id == batch.id, Job.user_id == current_user.id, Job.status == "completed")
        .order_by(Job.batch_index.asc().nullslast(), Job.id.asc())
        .all()
    )
    date_text = shanghai_now().strftime("%Y%m%d_%H%M%S")
    batch_label = _clean_zip_label(batch.batch_name or batch.batch_code, f"批次{batch.id}")
    return _build_jobs_zip_response(
        db,
        rows,
        f"batch_bulk_{current_user.id}_{batch.id}",
        f"{batch_label}_{date_text}.zip",
        skip_missing_files=True,
    )


@router.post("/jobs")
def create_job(
    prompt: str = Form(...),
    product_name: str = Form(...),
    region_name: str = Form(...),
    seconds: str = Form(...),
    size: str = Form(...),
    model_choice: str | None = Form(default=None),
    request_id: str | None = Form(default=None),
    batch_name: str | None = Form(default=None),
    reference_image_url: str | None = Form(default=None),
    reference_video_url: str | None = Form(default=None),
    reference_preset_id: str | None = Form(default=None),
    omni_mode: str | None = Form(default=None),
    omni_reference_preset_ids: list[str] | None = Form(default=None),
    omni_reference_image_urls: list[str] | None = Form(default=None),
    omni_reference_video_url: str | None = Form(default=None),
    confirmed_reference_image_urls: list[str] | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _validate_video_size(size)
    provider_name, parsed_seconds, provider_key_id = _parse_model_choice(model_choice, seconds)
    _assert_requested_key_available(db, provider_key_id)
    cleaned_prompts = normalize_prompt_list([prompt])
    risk_failures = _risk_failure_map(db, cleaned_prompts)
    provider_key = None if risk_failures else _select_model_provider_key(db, provider_name, parsed_seconds, provider_key_id)
    if not risk_failures and not provider_key:
        raise HTTPException(status_code=400, detail="当前没有可用的对应渠道密钥")
    selected_model_id = model_id_for_seconds(provider_key, parsed_seconds) if provider_key else None
    selected_provider_name = provider_key.provider_name if provider_key else provider_name
    resolved_images: list[tuple[str, str | None, int | None, int | None]] = []
    resolved_video_url = None
    resolved_url, resolved_name, resolved_width, resolved_height = (None, None, None, None)
    if not risk_failures:
        resolved_images, resolved_video_url = _resolve_job_reference_materials(
            db, current_user, selected_provider_name, size,
            reference_preset_id=reference_preset_id, reference_image_url=reference_image_url,
            reference_video_url=reference_video_url, omni_mode=omni_mode,
            omni_reference_preset_ids=omni_reference_preset_ids,
            omni_reference_image_urls=omni_reference_image_urls,
            omni_reference_video_url=omni_reference_video_url,
            confirmed_reference_image_urls=confirmed_reference_image_urls,
        )
        if resolved_images:
            resolved_url, resolved_name, resolved_width, resolved_height = resolved_images[0]
    try:
        batch, jobs = create_jobs_batch_and_reserve(
            db,
            current_user,
            provider_key,
            cleaned_prompts,
            parsed_seconds,
            size,
            reference_image_url=resolved_url,
            reference_video_url=resolved_video_url,
            reference_image_name=resolved_name,
            reference_width=resolved_width,
            reference_height=resolved_height,
            reference_images=resolved_images,
            batch_request_id=request_id,
            batch_name=batch_name,
            product_name=product_name,
            region_name=region_name,
            model_id=selected_model_id,
            risk_failure_messages=risk_failures,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = jobs[0]
    return {
        "job_id": job.id,
        "batch_id": batch.id,
        "batch_code": batch.batch_code,
        "batch_name": batch.batch_name,
        "product_name": job.product_name,
        "region_name": job.region_name,
        "remote_task_id": job.remote_task_id,
        "status": job.status,
        "queue_text": queue_text(db, job),
    }



@router.post("/jobs/batch")
def create_jobs_batch(
    prompts: list[str] = Form(...),
    product_name: str = Form(...),
    region_name: str = Form(...),
    seconds: str = Form(...),
    size: str = Form(...),
    model_choice: str | None = Form(default=None),
    batch_request_id: str | None = Form(default=None),
    batch_name: str | None = Form(default=None),
    reference_image_url: str | None = Form(default=None),
    reference_video_url: str | None = Form(default=None),
    reference_preset_id: str | None = Form(default=None),
    omni_mode: str | None = Form(default=None),
    omni_reference_preset_ids: list[str] | None = Form(default=None),
    omni_reference_image_urls: list[str] | None = Form(default=None),
    omni_reference_video_url: str | None = Form(default=None),
    confirmed_reference_image_urls: list[str] | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    _validate_video_size(size)
    provider_name, parsed_seconds, provider_key_id = _parse_model_choice(model_choice, seconds)
    _assert_requested_key_available(db, provider_key_id)
    cleaned_prompts = normalize_prompt_list(prompts)
    risk_failures = _risk_failure_map(db, cleaned_prompts)
    has_normal_prompts = len(risk_failures) < len(cleaned_prompts)
    provider_key = _select_model_provider_key(db, provider_name, parsed_seconds, provider_key_id) if has_normal_prompts else None
    if has_normal_prompts and not provider_key:
        raise HTTPException(status_code=400, detail="当前没有可用的对应渠道密钥")
    selected_model_id = model_id_for_seconds(provider_key, parsed_seconds) if provider_key else None
    selected_provider_name = provider_key.provider_name if provider_key else provider_name
    resolved_images: list[tuple[str, str | None, int | None, int | None]] = []
    resolved_video_url = None
    resolved_url, resolved_name, resolved_width, resolved_height = (None, None, None, None)
    if has_normal_prompts:
        resolved_images, resolved_video_url = _resolve_job_reference_materials(
            db, current_user, selected_provider_name, size,
            reference_preset_id=reference_preset_id, reference_image_url=reference_image_url,
            reference_video_url=reference_video_url, omni_mode=omni_mode,
            omni_reference_preset_ids=omni_reference_preset_ids,
            omni_reference_image_urls=omni_reference_image_urls,
            omni_reference_video_url=omni_reference_video_url,
            confirmed_reference_image_urls=confirmed_reference_image_urls,
        )
        if resolved_images:
            resolved_url, resolved_name, resolved_width, resolved_height = resolved_images[0]
    try:
        batch, jobs = create_jobs_batch_and_reserve(
            db,
            current_user,
            provider_key,
            cleaned_prompts,
            parsed_seconds,
            size,
            reference_image_url=resolved_url,
            reference_video_url=resolved_video_url,
            reference_image_name=resolved_name,
            reference_width=resolved_width,
            reference_height=resolved_height,
            reference_images=resolved_images,
            batch_request_id=batch_request_id,
            batch_name=batch_name,
            product_name=product_name,
            region_name=region_name,
            model_id=selected_model_id,
            risk_failure_messages=risk_failures,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "created_count": len(jobs),
        "batch_id": batch.id,
        "batch_code": batch.batch_code,
        "batch_name": batch.batch_name,
        "product_name": batch.product_name,
        "region_name": batch.region_name,
        "job_ids": [job.id for job in jobs],
        "target": f"/app/job-batches/{batch.id}/result",
        "message": f"已创建 {len(jobs)} 个任务，已进入队列",
    }


@router.post("/jobs/batch/form")
def create_jobs_batch_form(
    prompts: list[str] = Form(...),
    product_name: str = Form(...),
    region_name: str = Form(...),
    seconds: str = Form(...),
    size: str = Form(...),
    model_choice: str | None = Form(default=None),
    batch_request_id: str | None = Form(default=None),
    batch_name: str | None = Form(default=None),
    reference_image_url: str | None = Form(default=None),
    reference_video_url: str | None = Form(default=None),
    reference_preset_id: str | None = Form(default=None),
    omni_mode: str | None = Form(default=None),
    omni_reference_preset_ids: list[str] | None = Form(default=None),
    omni_reference_image_urls: list[str] | None = Form(default=None),
    omni_reference_video_url: str | None = Form(default=None),
    confirmed_reference_image_urls: list[str] | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_video_size(size)
    provider_name, parsed_seconds, provider_key_id = _parse_model_choice(model_choice, seconds)
    _assert_requested_key_available(db, provider_key_id)
    cleaned_prompts = normalize_prompt_list(prompts)
    risk_failures = _risk_failure_map(db, cleaned_prompts)
    has_normal_prompts = len(risk_failures) < len(cleaned_prompts)
    provider_key = _select_model_provider_key(db, provider_name, parsed_seconds, provider_key_id) if has_normal_prompts else None
    if has_normal_prompts and not provider_key:
        raise HTTPException(status_code=400, detail="当前没有可用的对应渠道密钥")
    selected_model_id = model_id_for_seconds(provider_key, parsed_seconds) if provider_key else None
    selected_provider_name = provider_key.provider_name if provider_key else provider_name
    resolved_images: list[tuple[str, str | None, int | None, int | None]] = []
    resolved_video_url = None
    resolved_url, resolved_name, resolved_width, resolved_height = (None, None, None, None)
    if has_normal_prompts:
        resolved_images, resolved_video_url = _resolve_job_reference_materials(
            db, current_user, selected_provider_name, size,
            reference_preset_id=reference_preset_id, reference_image_url=reference_image_url,
            reference_video_url=reference_video_url, omni_mode=omni_mode,
            omni_reference_preset_ids=omni_reference_preset_ids,
            omni_reference_image_urls=omni_reference_image_urls,
            omni_reference_video_url=omni_reference_video_url,
            confirmed_reference_image_urls=confirmed_reference_image_urls,
        )
        if resolved_images:
            resolved_url, resolved_name, resolved_width, resolved_height = resolved_images[0]
    try:
        batch, jobs = create_jobs_batch_and_reserve(
            db,
            current_user,
            provider_key,
            cleaned_prompts,
            parsed_seconds,
            size,
            reference_image_url=resolved_url,
            reference_video_url=resolved_video_url,
            reference_image_name=resolved_name,
            reference_width=resolved_width,
            reference_height=resolved_height,
            reference_images=resolved_images,
            batch_request_id=batch_request_id,
            batch_name=batch_name,
            product_name=product_name,
            region_name=region_name,
            model_id=selected_model_id,
            risk_failure_messages=risk_failures,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(f"/app/job-batches/{batch.id}/result?created={len(jobs)}", status_code=303)


@router.post("/jobs/form")
def create_job_form(
    prompt: str = Form(...),
    product_name: str = Form(...),
    region_name: str = Form(...),
    seconds: str = Form(...),
    size: str = Form(...),
    model_choice: str | None = Form(default=None),
    request_id: str | None = Form(default=None),
    batch_name: str | None = Form(default=None),
    reference_image_url: str | None = Form(default=None),
    reference_video_url: str | None = Form(default=None),
    reference_preset_id: str | None = Form(default=None),
    omni_mode: str | None = Form(default=None),
    omni_reference_preset_ids: list[str] | None = Form(default=None),
    omni_reference_image_urls: list[str] | None = Form(default=None),
    omni_reference_video_url: str | None = Form(default=None),
    confirmed_reference_image_urls: list[str] | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _validate_video_size(size)
    provider_name, parsed_seconds, provider_key_id = _parse_model_choice(model_choice, seconds)
    _assert_requested_key_available(db, provider_key_id)
    cleaned_prompts = normalize_prompt_list([prompt])
    risk_failures = _risk_failure_map(db, cleaned_prompts)
    provider_key = None if risk_failures else _select_model_provider_key(db, provider_name, parsed_seconds, provider_key_id)
    if not risk_failures and not provider_key:
        raise HTTPException(status_code=400, detail="当前没有可用的对应渠道密钥")
    selected_model_id = model_id_for_seconds(provider_key, parsed_seconds) if provider_key else None
    selected_provider_name = provider_key.provider_name if provider_key else provider_name
    resolved_images: list[tuple[str, str | None, int | None, int | None]] = []
    resolved_video_url = None
    resolved_url, resolved_name, resolved_width, resolved_height = (None, None, None, None)
    if not risk_failures:
        resolved_images, resolved_video_url = _resolve_job_reference_materials(
            db, current_user, selected_provider_name, size,
            reference_preset_id=reference_preset_id, reference_image_url=reference_image_url,
            reference_video_url=reference_video_url, omni_mode=omni_mode,
            omni_reference_preset_ids=omni_reference_preset_ids,
            omni_reference_image_urls=omni_reference_image_urls,
            omni_reference_video_url=omni_reference_video_url,
            confirmed_reference_image_urls=confirmed_reference_image_urls,
        )
        if resolved_images:
            resolved_url, resolved_name, resolved_width, resolved_height = resolved_images[0]
    try:
        _batch, jobs = create_jobs_batch_and_reserve(
            db,
            current_user,
            provider_key,
            cleaned_prompts,
            parsed_seconds,
            size,
            reference_image_url=resolved_url,
            reference_video_url=resolved_video_url,
            reference_image_name=resolved_name,
            reference_width=resolved_width,
            reference_height=resolved_height,
            reference_images=resolved_images,
            batch_request_id=request_id,
            batch_name=batch_name,
            product_name=product_name,
            region_name=region_name,
            model_id=selected_model_id,
            risk_failure_messages=risk_failures,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job = jobs[0]
    return RedirectResponse(f"/app/jobs/{job.id}/page", status_code=303)


@router.get("/jobs/{job_id}/page", response_class=HTMLResponse)
def job_detail_page(
    job_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    events = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id.asc()).all()
    files = db.query(JobFile).filter(JobFile.job_id == job.id).order_by(JobFile.id.asc()).all()
    api_calls = db.query(APICallLog).filter(APICallLog.job_id == job.id).order_by(APICallLog.id.asc()).all()
    job_data = serialize_job(job, output_file)
    job_data["queue_text"] = queue_text(db, job)
    job_data["remote_download_url"] = f"/app/jobs/{job.id}/remote-download" if job.remote_task_id else None
    token = make_public_remote_download_token(job.id, job.remote_task_id, get_system_setting_int(db, "public_download_token_ttl_seconds", settings.public_download_token_ttl_seconds))
    job_data["public_remote_download_url"] = f"/app/jobs/{job.id}/public-remote-download?token={token}" if token else None
    return render(
        request,
        "app/job_detail.html",
        current_user=current_user,
        job=job_data,
        output_file=output_file,
        events=[serialize_event(event) for event in events],
        files=files,
        api_calls=[_serialize_api_call(call) for call in api_calls],
        can_redownload=can_redownload(job, output_file),
        can_resume=can_resume(job),
        can_pause=can_pause(job),
        data_endpoint=f"/app/jobs/{job.id}",
        remote_download_url=job_data.get("remote_download_url"),
        public_remote_download_url=job_data.get("public_remote_download_url"),
    )


@router.get("/jobs/{job_id}")
def job_detail(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    events = db.query(JobEvent).filter(JobEvent.job_id == job.id).order_by(JobEvent.id.asc()).all()
    api_calls = db.query(APICallLog).filter(APICallLog.job_id == job.id).order_by(APICallLog.id.asc()).all()
    job_data = serialize_job(job, output_file)
    job_data["queue_text"] = queue_text(db, job)
    job_data["remote_download_url"] = f"/app/jobs/{job.id}/remote-download" if job.remote_task_id else None
    token = make_public_remote_download_token(job.id, job.remote_task_id, get_system_setting_int(db, "public_download_token_ttl_seconds", settings.public_download_token_ttl_seconds))
    job_data["public_remote_download_url"] = f"/app/jobs/{job.id}/public-remote-download?token={token}" if token else None
    return {
        "job": job_data,
        "events": [serialize_event(event) for event in events],
        "api_calls": [_serialize_api_call(call) for call in api_calls],
        "can_redownload": can_redownload(job, output_file),
        "can_resume": can_resume(job),
        "can_pause": can_pause(job),
    }


@router.get("/jobs/{job_id}/public-remote-download")
def public_remote_download_job(job_id: int, token: str = Query(...), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not verify_public_remote_download_token(token, job.id, job.remote_task_id):
        raise HTTPException(status_code=403, detail="涓嬭浇閾炬帴鏃犳晥鎴栧凡杩囨湡")
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
def remote_download_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
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
def redownload_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    if not can_redownload(job, output_file):
        raise HTTPException(status_code=400, detail="Current job status does not allow redownload")
    if output_file is None and not _has_confirmed_remote_completed(db, job):
        job.status = "polling" if job.remote_task_id else "queued"
        job.download_attempts = 0
        job.error_text = None
        db.add(job)
        db.add(JobEvent(
            job_id=job.id,
            level="info",
            event_type="redownload_redirect_polling",
            message="Remote completion is not confirmed yet; returning job to polling.",
        ))
        db.commit()
        return {"ok": True, "mode": "polling"}

    job.status = "remote_completed"
    job.download_attempts = 0
    job.error_text = None
    job.progress = 100
    db.add(job)
    db.add(JobEvent(job_id=job.id, level="info", event_type="redownload_requested", message="User requested redownload."))
    db.commit()
    try:
        from app.services.worker_runtime import schedule_job_now
        kicked = schedule_job_now(int(job.id))
        db.add(JobEvent(job_id=job.id, level="info", event_type="manual_kick", message=f"Worker kick requested; scheduled={kicked}."))
        db.commit()
    except Exception:
        pass
    return {"ok": True, "mode": "download"}


@router.post("/jobs/{job_id}/resume")
def resume_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
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
    db.add(JobEvent(job_id=job.id, level="info", event_type="resume_requested", message=f"User requested resume; mode={mode_text}."))
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
def pause_job(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if not can_pause(job):
        raise HTTPException(status_code=400, detail="Current job status does not allow pause")
    job.status = "interrupted"
    db.add(job)
    db.add(JobEvent(job_id=job.id, level="info", event_type="pause_requested", message="User requested pause."))
    db.commit()
    return {"ok": True}


@router.post("/jobs/{job_id}/toggle-star")
def toggle_job_star(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    if job.status != "completed" or not output_file:
        raise HTTPException(status_code=400, detail="Only completed jobs with a saved file can be starred")
    job.is_starred = not bool(job.is_starred)
    job.starred_at = utcnow() if job.is_starred else None
    db.add(job)
    db.commit()
    return {"ok": True, "job_id": job.id, "is_starred": bool(job.is_starred)}


@router.post("/jobs/{job_id}/toggle-private-protection")
def toggle_job_private_protection(job_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    output_file = get_output_file(db, job.id)
    if job.status != "completed" or not output_file:
        raise HTTPException(status_code=400, detail="Only completed jobs with a saved file can be protected")
    current_protection = True if job.is_private_protected is True or job.is_private_protected == 1 else False
    job.is_private_protected = not current_protection
    job.private_protected_at = utcnow() if job.is_private_protected else None
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"ok": True, "job_id": job.id, "is_private_protected": bool(job.is_private_protected)}


@router.get("/quota")
def quota(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    if refresh_user_packages(db, int(current_user.id)):
        db.commit()
    wallet = db.query(QuotaWallet).filter(QuotaWallet.user_id == current_user.id).first()
    quota_stats = quota_totals_for_user(db, int(current_user.id), wallet)
    return {
        "remaining_quota": wallet.remaining_quota if wallet else 0,
        "available_quota": quota_stats["total_available"],
        "total_remaining_quota": quota_stats["total_remaining"],
        "total_reserved_quota": quota_stats["total_reserved"],
        "personal_remaining_quota": quota_stats["personal_remaining"],
        "personal_available_quota": quota_stats["personal_available"],
        "personal_reserved_quota": quota_stats["personal_reserved"],
        "package_remaining_quota": quota_stats["package_remaining"],
        "package_available_quota": quota_stats["package_available"],
        "package_reserved_quota": quota_stats["package_reserved"],
        "total_granted": wallet.total_granted if wallet else 0,
        "total_used": wallet.total_used if wallet else 0,
    }


@router.get("/quota/ledger")
def quota_ledger(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.query(QuotaLedger).filter(QuotaLedger.user_id == current_user.id).order_by(QuotaLedger.id.desc()).limit(100).all()
    return [
        {
            "id": row.id,
            "job_id": row.job_id,
            "change_amount": row.change_amount,
            "action": row.action,
            "note": row.note,
            "created_at": format_shanghai_datetime(row.created_at),
        }
        for row in rows
    ]

