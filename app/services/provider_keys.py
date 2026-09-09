import random
from datetime import UTC, datetime
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.timezone import date_bounds_utc, shanghai_now
from app.models.tables import APICallLog, ProviderKey

RETIRED_PROVIDERS = frozenset({"podsora", "podgrok"})

PROVIDER_LABELS = {
    "sora_api": "Sora",
    "seedance": "Seedance",
    "podsora": "PodSora",
    "podgrok": "PodGrok",
    "veo_omni": "Veo Omni",
    "wuyin_omni": "Wuyin Omni",
}

PROVIDER_SECONDS = {
    "sora_api": (8, 12),
    "seedance": (5, 10, 12),
    "podsora": (4, 8, 12),
    "podgrok": (12, 15),
    "veo_omni": (10,),
    "wuyin_omni": (10,),
}

def normalize_provider_name(value: str | None) -> str:
    text = str(value or "sora_api").strip().lower()
    if text in {"sora", "sora_api"}:
        return "sora_api"
    if text in {"seedance", "seedance_api"}:
        return "seedance"
    if text in {"podsora", "pod_sora", "apipod", "apipod_sora"}:
        return "podsora"
    if text in {"podgrok", "pod_grok", "apipod_grok", "grok", "grok_imagine"}:
        return "podgrok"
    if text in {"veo_omni", "veo-omni", "veoomni"}:
        return "veo_omni"
    if text in {"wuyin_omni", "wuyin-omni", "google_omni", "google-omni", "video_google_omni", "wuyin_google_omni"}:
        return "wuyin_omni"
    return text


def provider_is_retired(value: str | None) -> bool:
    return normalize_provider_name(value) in RETIRED_PROVIDERS


def model_id_for_seconds(provider_key: ProviderKey, seconds: int) -> str:
    if normalize_provider_name(provider_key.provider_name) == "wuyin_omni":
        return "wuyin-omni" if int(seconds) == 10 else ""
    field_value = getattr(provider_key, f"model_id_{int(seconds)}s", None)
    model_id = str(field_value or "").strip()
    if model_id:
        return model_id
    return ""


def provider_supports_seconds(provider_name: str | None, seconds: int) -> bool:
    provider = normalize_provider_name(provider_name)
    return int(seconds) in PROVIDER_SECONDS.get(provider, ())


def list_active_provider_keys(db: Session) -> list[ProviderKey]:
    return db.query(ProviderKey).filter(ProviderKey.status == 'active').order_by(ProviderKey.id.asc()).all()


def _is_in_cooldown(key: ProviderKey, now: datetime) -> bool:
    if key.consecutive_failures < settings.provider_key_failure_threshold:
        return False
    if not key.last_error_at:
        return False
    return (now - key.last_error_at).total_seconds() < settings.provider_key_cooldown_seconds


def select_provider_key(db: Session, provider_name: str | None = None, seconds: int | None = None) -> ProviderKey | None:
    keys = list_active_provider_keys(db)
    provider_filter = normalize_provider_name(provider_name) if provider_name else None
    if not keys:
        return None
    now = datetime.now(UTC)
    eligible: list[ProviderKey] = []
    cooldown_fallback: list[ProviderKey] = []
    weights: list[int] = []
    cooldown_weights: list[int] = []
    for key in keys:
        if provider_is_retired(key.provider_name):
            continue
        if provider_filter and normalize_provider_name(key.provider_name) != provider_filter:
            continue
        if seconds is not None and not provider_supports_seconds(key.provider_name, int(seconds)):
            continue
        if seconds is not None and not model_id_for_seconds(key, int(seconds)):
            continue
        in_cooldown = _is_in_cooldown(key, now)
        if key.daily_limit:
            # Preserve the original /videos accounting for existing providers while
            # counting Wuyin Omni's separate task-creation endpoint independently.
            day_start, _day_end = date_bounds_utc(shanghai_now().date())
            calls_query = (
                db.query(func.count(APICallLog.id))
                .filter(
                    APICallLog.provider_key_id == key.id,
                    APICallLog.created_at >= day_start,
                    APICallLog.method == 'POST',
                    APICallLog.success.is_(True),
                )
            )
            if normalize_provider_name(key.provider_name) == "wuyin_omni":
                calls_query = calls_query.filter(APICallLog.endpoint.ilike('%/api/async/video_google_omni%'))
            else:
                calls_query = calls_query.filter(APICallLog.endpoint.ilike('%/videos%'))
            today_calls = calls_query.scalar() or 0
            if today_calls >= key.daily_limit:
                continue
        if in_cooldown:
            cooldown_fallback.append(key)
            cooldown_weights.append(max(key.weight or 1, 1))
            continue
        eligible.append(key)
        weights.append(max(key.weight or 1, 1))
    if not eligible:
        if not cooldown_fallback:
            return None
        return random.choices(cooldown_fallback, weights=cooldown_weights, k=1)[0]
    return random.choices(eligible, weights=weights, k=1)[0]


def record_provider_key_success(db: Session, provider_key: ProviderKey) -> None:
    provider_key.consecutive_failures = 0
    provider_key.last_error_at = None
    provider_key.last_used_at = datetime.now(UTC)
    db.add(provider_key)


def record_provider_key_failure(db: Session, provider_key: ProviderKey) -> None:
    provider_key.consecutive_failures = (provider_key.consecutive_failures or 0) + 1
    provider_key.last_error_at = datetime.now(UTC)
    db.add(provider_key)
