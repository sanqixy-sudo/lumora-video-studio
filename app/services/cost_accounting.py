"""Reconcile successful New API video tasks with the token's actual billing logs."""

from __future__ import annotations

import json
import base64
import binascii
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from types import SimpleNamespace

import httpx
from sqlalchemy.orm import Session

from app.core.timezone import to_shanghai_date
from app.db import SessionLocal
from app.models.tables import Job, JobCost, JobCostRevision, JobEvent, ProviderKey, User
from app.services.crypto import decrypt_secret
from app.services.network_settings import get_proxy_url
from app.services.provider_keys import normalize_provider_name
from app.services import flow_omni
from app.services.sora_api import COMPLETED_STATUSES, UpstreamError, fetch_video_status, normalize_api_base_url

NEWAPI_PROVIDERS = frozenset({"oaire_grok", "oaire_omni", "flow_omni"})
FAILED_REMOTE_STATUSES = frozenset({"failed", "error", "stopped", "cancelled", "canceled"})


def register_job_cost(db: Session, job: Job, provider_key: ProviderKey) -> JobCost | None:
    """Register accepted tasks only; this function never charges a failed generation."""
    provider_name = normalize_provider_name(provider_key.provider_name)
    if provider_name not in NEWAPI_PROVIDERS or not job.remote_task_id:
        return None
    base_url = normalize_api_base_url(provider_key.api_base_url or (flow_omni.DEFAULT_BASE_URL if provider_name in {"flow_omni", "oaire_omni"} else None))
    row = db.query(JobCost).filter(JobCost.source_job_id == job.id).first()
    if row is None:
        user = db.query(User).filter(User.id == job.user_id).first()
        row = JobCost(
            source_job_id=job.id,
            source_user_id=job.user_id,
            username=user.username if user else str(job.user_id),
            provider_key_id=provider_key.id,
            api_base_url=base_url,
            provider_name=provider_name,
            remote_task_id=job.remote_task_id,
            model=job.model,
            seconds=job.seconds,
            resolution=job.resolution,
            state="pending",
            next_check_at=datetime.now(UTC) + timedelta(seconds=5),
        )
    elif row.remote_task_id != job.remote_task_id:
        if row.state == "settled":
            raise ValueError("A settled cost cannot be reassigned to another task")
        row.remote_task_id = job.remote_task_id
        row.api_base_url = base_url
        row.provider_key_id = provider_key.id
        row.model = job.model
        row.seconds = job.seconds
        row.resolution = job.resolution
        row.state = "pending"
        row.next_check_at = datetime.now(UTC) + timedelta(seconds=5)
    db.add(row)
    return row


def _read_json(client: httpx.Client, url: str, api_key: str | None = None) -> dict:
    headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = client.get(url, headers=headers)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise ValueError("New API returned an unsuccessful billing response")
    return payload


def _other(log: dict) -> dict:
    value = log.get("other") or {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            return {}
    return value if isinstance(value, dict) else {}


def _billing_expression(other: dict) -> str | None:
    encoded = other.get("expr_b64")
    if not isinstance(encoded, str) or not encoded:
        return None
    try:
        return base64.b64decode(encoded, validate=True).decode("utf-8")[:1000]
    except (ValueError, UnicodeError, binascii.Error):
        return None


def matching_billing_logs(logs: list, task_id: str) -> tuple[int, list[dict]]:
    """Sum every consume/refund record for one task from a complete API snapshot."""
    net_quota = 0
    matched: list[dict] = []
    for log in logs:
        if not isinstance(log, dict):
            continue
        other = _other(log)
        if str(other.get("task_id") or "") != task_id:
            continue
        log_type = int(log.get("type") or 0)
        if log_type not in {2, 6}:
            continue
        quota = int(log.get("quota") or 0)
        if quota < 0:
            raise ValueError("New API returned a negative log quota")
        net_quota += quota if log_type == 2 else -quota
        matched.append({
            "request_id": str(log.get("request_id") or ""),
            "type": log_type,
            "quota": quota,
            "created_at": log.get("created_at"),
            "model_name": str(log.get("model_name") or ""),
            "expr_b64": other.get("expr_b64"),
            "billing_expression": _billing_expression(other),
            "usage_facts": other.get("usage_facts"),
            "group_ratio": other.get("group_ratio"),
            "matched_tier": other.get("matched_tier"),
        })
    return net_quota, matched


def merge_billing_logs(previous: list[dict] | None, latest: list[dict]) -> tuple[int, list[dict]]:
    """Keep precharges when New API's recent-log window rolls forward."""
    merged: dict[tuple, dict] = {}
    for item in [*(previous or []), *latest]:
        request_id = str(item.get("request_id") or "")
        identity = (
            request_id,
            item.get("type"),
            item.get("quota"),
            item.get("created_at"),
            item.get("model_name"),
        )
        merged[identity] = item
    records = list(merged.values())
    net = sum((int(item["quota"]) if int(item["type"]) == 2 else -int(item["quota"]) for item in records), 0)
    if net < 0:
        raise ValueError("New API task has a negative net quota")
    return net, records


def _completed_at(data: dict, fallback: datetime) -> datetime:
    raw = data.get("_raw")
    inner = raw.get("data") if isinstance(raw, dict) else None
    candidates = [data.get("completed_at"), data.get("finished_at"), data.get("finish_time")]
    if isinstance(inner, dict):
        candidates.extend(inner.get(key) for key in ("completed_at", "finished_at", "finish_time"))
    for value in candidates:
        if isinstance(value, (int, float)) and value > 0:
            return datetime.fromtimestamp(value / 1000 if value > 10_000_000_000 else value, UTC)
        if isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
                return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
            except ValueError:
                pass
    return fallback


def _fetch_snapshot(row: JobCost, api_key: str, request_proxy: str) -> tuple[str, dict, int | None, int | None, list[dict] | None]:
    video, _code, _latency = fetch_video_status(
        api_key, row.remote_task_id, row.api_base_url, row.provider_name, request_proxy=request_proxy
    )
    status = str(video.get("status") or "").lower()
    with httpx.Client(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10), proxy=request_proxy or None, trust_env=False) as client:
        base = row.api_base_url.rstrip("/")
        log_body = _read_json(client, base + "/api/log/token", api_key)
        logs = log_body.get("data")
        if not isinstance(logs, list):
            raise ValueError("New API billing log response has no list")
        net_quota, matched = matching_billing_logs(logs, row.remote_task_id)
        if not matched and status in COMPLETED_STATUSES and not row.source_logs:
            raise ValueError("No billing log for task in recent token logs" + (" (1000-row window full)" if len(logs) >= 1000 else ""))
        if len(logs) >= 1000 and row.created_at and not row.source_logs:
            oldest = min((int(item.get("created_at") or 0) for item in logs if isinstance(item, dict)), default=0)
            submitted = row.created_at.replace(tzinfo=UTC) if row.created_at.tzinfo is None else row.created_at
            if oldest and oldest > int(submitted.timestamp()):
                raise ValueError("Token log window may omit this task's first charge")
        status_body = _read_json(client, base + "/api/status")
        status_data = status_body.get("data") or {}
        if str(status_data.get("quota_display_type") or "").upper() != "USD":
            raise ValueError("New API quota currency is not USD")
        quota_per_unit = int(status_data.get("quota_per_unit") or 0)
        if quota_per_unit <= 0:
            raise ValueError("New API returned no valid quota_per_unit")
        return status, video, net_quota, quota_per_unit, matched


def reconcile_job_cost(source_job_id: int) -> None:
    """Read upstream outside a DB transaction, then atomically save one snapshot."""
    with SessionLocal() as db:
        row = db.query(JobCost).filter(JobCost.source_job_id == source_job_id).first()
        if row is None or row.state == "excluded" or row.next_check_at is None:
            return
        provider_key = db.query(ProviderKey).filter(ProviderKey.id == row.provider_key_id).first()
        if not provider_key:
            _set_retry(db, row, "Provider key missing", minutes=10)
            return
        snapshot = (row.remote_task_id, row.api_base_url, row.provider_key_id)
        event = (
            db.query(JobEvent.created_at)
            .filter(JobEvent.job_id == source_job_id, JobEvent.event_type == "remote_completed")
            .order_by(JobEvent.created_at.asc())
            .first()
        )
        fallback_time = row.upstream_completed_at or (event[0] if event else None) or datetime.now(UTC)
        if fallback_time.tzinfo is None:
            fallback_time = fallback_time.replace(tzinfo=UTC)
        key_encrypted = provider_key.key_encrypted
        request_proxy = get_proxy_url(db, "request")
        lookup = SimpleNamespace(
            remote_task_id=row.remote_task_id,
            api_base_url=row.api_base_url,
            provider_name=row.provider_name,
            source_logs=row.source_logs,
            created_at=row.created_at,
        )

    try:
        api_key = decrypt_secret(key_encrypted)
        status, video, net_quota, quota_per_unit, matched = _fetch_snapshot(lookup, api_key, request_proxy)
    except (UpstreamError, httpx.HTTPError, ValueError, TypeError, OverflowError) as exc:
        detail = str(exc)[:200] if isinstance(exc, ValueError) else type(exc).__name__
        with SessionLocal() as db:
            row = db.query(JobCost).filter(JobCost.source_job_id == source_job_id).with_for_update().first()
            if row and row.state != "excluded" and (row.remote_task_id, row.api_base_url, row.provider_key_id) == snapshot:
                _set_retry(db, row, f"Billing lookup failed: {detail}", minutes=2)
        return

    with SessionLocal() as db:
        row = db.query(JobCost).filter(JobCost.source_job_id == source_job_id).with_for_update().first()
        if row is None or (row.remote_task_id, row.api_base_url, row.provider_key_id) != snapshot:
            return
        now = datetime.now(UTC)
        row.checked_at = now
        assert matched is not None and quota_per_unit is not None
        try:
            net_quota, source_logs = merge_billing_logs(row.source_logs, matched)
        except ValueError as exc:
            _set_retry(db, row, str(exc), minutes=2)
            return
        row.source_logs = source_logs
        row.quota_per_unit = row.quota_per_unit or quota_per_unit
        if status in FAILED_REMOTE_STATUSES:
            if row.state == "settled" and row.amount is not None:
                db.add(JobCostRevision(
                    source_job_id=source_job_id,
                    previous_quota=row.net_quota,
                    new_quota=0,
                    previous_amount=row.amount,
                    new_amount=Decimal(0),
                    source_logs=source_logs,
                ))
            row.net_quota = None
            row.amount = None
            row.usage_date = None
            row.state = "excluded"
            row.next_check_at = None
            row.last_error = None
        elif status not in COMPLETED_STATUSES:
            if row.state != "settled":
                row.state = "pending"
            row.next_check_at = now + timedelta(minutes=1)
            row.last_error = "Upstream status is not completed on recheck" if row.state == "settled" else None
        else:
            if not source_logs:
                _set_retry(db, row, "No task billing log yet", minutes=1)
                return
            was_settled = row.state == "settled"
            unit = row.quota_per_unit
            amount = (Decimal(net_quota) / Decimal(unit)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            completed_at = _completed_at(video, fallback_time)
            if row.net_quota != net_quota or row.amount != amount:
                db.add(JobCostRevision(
                    source_job_id=source_job_id,
                    previous_quota=row.net_quota,
                    new_quota=net_quota,
                    previous_amount=row.amount,
                    new_amount=amount,
                    source_logs=source_logs,
                ))
            row.state = "settled"
            row.quota_per_unit = unit
            row.net_quota = net_quota
            row.amount = amount
            row.currency = "USD"
            row.source_logs = source_logs
            row.upstream_completed_at = completed_at
            row.usage_date = to_shanghai_date(completed_at)
            row.last_error = None
            # Check for late adjustments while the source logs are still likely retained.
            row.next_check_at = now + timedelta(minutes=15) if not was_settled or now - completed_at < timedelta(days=2) else None
        db.add(row)
        db.commit()


def _set_retry(db: Session, row: JobCost, message: str, *, minutes: int) -> None:
    row.last_error = message
    row.checked_at = datetime.now(UTC)
    row.next_check_at = row.checked_at + timedelta(minutes=minutes)
    db.add(row)
    db.commit()
