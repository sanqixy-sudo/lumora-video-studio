from __future__ import annotations

from sqlalchemy.orm import Session

from app.services.model_choices import model_options
from app.core.config import settings
from app.models.tables import AppSetting
from app.services.network_settings import (PROXY_KEYS, decode_proxy_url, encode_proxy_url, proxy_default, redact_proxy_url, stored_proxy_url, validate_proxy_url)

SYSTEM_SETTING_DEFS = [
    {"key": "default_model_choice", "label": "默认生成模型", "default": "", "type": "model", "restart": False},
    {"key": "default_resolution", "label": "默认清晰度", "default": "", "type": "generation", "restart": False},
    {"key": "default_aspect_ratio", "label": "默认画幅比例", "default": "", "type": "generation", "restart": False},
    {"key": "default_seconds", "label": "默认时长", "default": "", "type": "generation", "restart": False},
    {"key": "request_proxy_enabled", "label": "上游请求连接方式", "default": "1" if settings.upstream_request_proxy else "0", "type": "bool", "restart": False},
    {"key": "request_proxy_url", "label": "请求代理地址", "default": settings.upstream_request_proxy, "type": "proxy", "restart": False},
    {"key": "download_proxy_enabled", "label": "视频下载连接方式", "default": "1" if settings.video_download_proxy else "0", "type": "bool", "restart": False},
    {"key": "download_proxy_url", "label": "下载代理地址", "default": settings.video_download_proxy, "type": "proxy", "restart": False},
    {"key": "video_download_concurrency", "label": "视频下载并发", "default": str(settings.video_download_concurrency), "type": "int", "min": 1, "max": 32, "restart": False},
    {
        "key": "max_running_jobs",
        "label": "全站生成并发",
        "min": 1,
        "max": 256,
        "default": str(settings.max_running_jobs),
        "type": "int",
        "restart": False,
    },
    {
        "key": "submit_max_attempts",
        "label": "提交上游最大重试",
        "default": str(settings.submit_max_attempts),
        "type": "int",
        "restart": False,
    },
    {
        "key": "download_retry_delays_seconds",
        "label": "下载重试间隔秒",
        "default": str(settings.download_retry_delays_seconds),
        "type": "text",
        "restart": False,
    },
    {
        "key": "public_download_token_ttl_seconds",
        "label": "临时下载链接有效期秒",
        "default": str(settings.public_download_token_ttl_seconds),
        "type": "int",
        "restart": False,
    },
    {
        "key": "content_fallback_after_seconds",
        "label": "远端处理中最短轮询秒数（至少 6000）",
        "default": str(settings.content_fallback_after_seconds),
        "type": "int",
        "restart": False,
    },
    {
        "key": "registration_enabled",
        "label": "开放用户注册",
        "default": "0",
        "type": "bool",
        "restart": False,
    },
    {
        "key": "default_daily_job_limit",
        "label": "默认每日提交上限",
        "default": "",
        "type": "int_optional",
        "restart": False,
    },
    {
        "key": "default_concurrent_job_limit",
        "label": "默认用户同时生成数",
        "default": "",
        "type": "int_optional",
        "restart": False,
    },
    {
        "key": "default_min_submit_interval_seconds",
        "label": "默认提交间隔秒",
        "default": "",
        "type": "int_optional",
        "restart": False,
    },
]


SETTING_PRESENTATION = {
    "default_model_choice": ("创作默认", "", "新打开创建页时自动选中，用户仍可自行切换。停用或删除通道后自动回到手动选择。"),
    "default_resolution": ("创作默认", "", "新打开生成页时使用的清晰度，选项随默认模型变化。"),
    "default_aspect_ratio": ("创作默认", "", "新打开生成页时使用的画幅比例，用户仍可自行调整。"),
    "default_seconds": ("创作默认", "", "新打开生成页时使用的时长；固定时长模型仅提供一个选项。"),
    "request_proxy_enabled": ("代理设置", "", "用于向上游提交生成任务和查询任务状态；保存后用于下一次请求。"),
    "request_proxy_url": ("代理设置", "", "支持 HTTP、HTTPS、SOCKS5。留空保留当前地址；选择直连可关闭代理。"),
    "download_proxy_enabled": ("代理设置", "", "仅用于获取视频文件，与上游请求代理独立。正在进行的下载沿用开始时的配置。"),
    "download_proxy_url": ("代理设置", "", "填写应用服务器能够连接的代理地址。留空保留当前地址；选择直连可关闭代理。"),
    "video_download_concurrency": ("并发控制", "个", "允许 1–32 个视频同时下载。保存后自动生效；调低时等待已有下载完成，不中断任务。"),
    "max_running_jobs": ("并发控制", "个", "全站同时执行的生成任务上限。"),
    "submit_max_attempts": ("并发控制", "次", "提交失败时允许的最大尝试次数。"),
    "content_fallback_after_seconds": ("下载与重试", "秒", "上游仍处理中时等待多久再尝试下载探测；运行时至少等待 6000 秒。"),
    "download_retry_delays_seconds": ("下载与重试", "秒", "按顺序设置下载重试间隔，用英文逗号分隔。"),
    "public_download_token_ttl_seconds": ("下载与重试", "秒", "新生成的临时下载链接有效时间。"),
    "registration_enabled": ("用户与额度", "", "是否允许用户自行注册账号。"),
    "default_daily_job_limit": ("用户与额度", "个 / 天", "用户未单独设置时采用此限制；留空表示不限制。"),
    "default_concurrent_job_limit": ("用户与额度", "个", "用户未单独设置时允许的同时生成数量；留空表示不限制。"),
    "default_min_submit_interval_seconds": ("用户与额度", "秒", "两次提交之间的最短间隔；留空表示不限制。"),
}
for _definition in SYSTEM_SETTING_DEFS:
    _group, _unit, _description = SETTING_PRESENTATION[_definition["key"]]
    _definition.update(group=_group, unit=_unit, description=_description)


def setting_defaults() -> dict[str, str]:
    return {item["key"]: str(item.get("default") or "") for item in SYSTEM_SETTING_DEFS}


def get_system_setting_text(db: Session, key: str, default: str | None = None) -> str | None:
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row and row.value not in {None, ""}:
        return str(row.value)
    if default is not None:
        return str(default)
    return setting_defaults().get(key)


def get_system_setting_int(db: Session, key: str, default: int | None = None) -> int | None:
    text = get_system_setting_text(db, key, None)
    if text in {None, ""}:
        return default
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def get_system_setting_bool(db: Session, key: str, default: bool = False) -> bool:
    text = get_system_setting_text(db, key, None)
    if text in {None, ""}:
        return default
    return str(text).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def upsert_system_setting(db: Session, key: str, value: str | None, operator_user_id: int | None = None) -> AppSetting:
    valid_keys = {item["key"] for item in SYSTEM_SETTING_DEFS}
    if key not in valid_keys:
        raise ValueError("未知设置项")
    value = (value or "").strip()
    definition = next(item for item in SYSTEM_SETTING_DEFS if item["key"] == key)
    if definition["type"] in {"int", "int_optional"} and value:
        parsed = int(value)
        minimum, maximum = definition.get("min", 0), definition.get("max")
        if parsed < minimum or (maximum is not None and parsed > maximum):
            raise ValueError(f"{definition['label']}须为 {minimum}–{maximum}。" if maximum is not None else f"{definition['label']}不能小于 {minimum}。")
        value = str(parsed)
    if definition["type"] == "model" and value and value not in {row["value"] for row in model_options(db)}:
        raise ValueError("默认模型已不可用，请选择启用通道中的模型。")
    if definition["type"] == "bool":
        value = "1" if str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"} else "0"
    if definition["type"] == "int" and not value:
        value = definition["default"]
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if not row:
        row = AppSetting(key=key)
        db.add(row)
    if definition["type"] == "proxy":
        if not value:
            value = decode_proxy_url(row.value) if row.value else proxy_default(key.removesuffix("_proxy_url"))
        value = encode_proxy_url(validate_proxy_url(value))
    row.value = value or None
    row.operator_user_id = operator_user_id
    return row


GENERATION_DEFAULT_FIELDS = {
    "default_resolution": "resolutions", "default_aspect_ratio": "ratios", "default_seconds": "seconds",
}


def _spec_default_values(spec: dict) -> dict[str, str]:
    return {"default_resolution": spec["default_resolution"], "default_aspect_ratio": "9:16",
            "default_seconds": str(spec["default_seconds"])}


def get_creation_defaults(db: Session, choices: list[dict] | None = None) -> dict[str, str]:
    choices = model_options(db) if choices is None else choices
    preferred = get_system_setting_text(db, "default_model_choice", "")
    choice = next((row for row in choices if row["value"] == preferred), None)
    if not choice:
        return {"default_model_choice": "", **{key: "" for key in GENERATION_DEFAULT_FIELDS}}
    spec = choice["capabilities"]
    defaults = _spec_default_values(spec)
    for key, capability in GENERATION_DEFAULT_FIELDS.items():
        stored = get_system_setting_text(db, key, "")
        if stored in {str(value) for value in spec[capability]}:
            defaults[key] = stored
    return {"default_model_choice": preferred, **defaults}


def normalize_creation_defaults(db: Session, submitted: dict) -> dict[str, str]:
    """Validate the complete model/spec selection before any settings are written."""
    keys = {"default_model_choice", *GENERATION_DEFAULT_FIELDS}
    if not keys.intersection(submitted):
        return {}
    current = get_creation_defaults(db)
    model = str(submitted.get("default_model_choice", current["default_model_choice"]) or "").strip()
    if not model:
        return {key: "" for key in keys}
    choice = next((row for row in model_options(db) if row["value"] == model), None)
    if not choice:
        raise ValueError("默认模型已不可用，请重新选择。")
    spec = choice["capabilities"]
    defaults = _spec_default_values(spec)
    labels = {"default_resolution": "默认清晰度", "default_aspect_ratio": "默认画幅比例", "default_seconds": "默认时长"}
    for key, capability in GENERATION_DEFAULT_FIELDS.items():
        previous = current[key] if current["default_model_choice"] == model else defaults[key]
        value = str(submitted.get(key, previous) or defaults[key]).strip()
        if value not in {str(item) for item in spec[capability]}:
            raise ValueError(f"所选模型不支持{labels[key]}，请重新选择。")
        defaults[key] = value
    return {"default_model_choice": model, **defaults}


def get_system_settings_view(db: Session) -> list[dict]:
    rows = {row.key: row for row in db.query(AppSetting).all()}
    data = []
    choices = model_options(db)
    defaults = get_creation_defaults(db, choices)
    choice = next((row for row in choices if row["value"] == defaults["default_model_choice"]), None)
    for definition in SYSTEM_SETTING_DEFS:
        row = rows.get(definition["key"])
        value = row.value if row and row.value is not None else definition["default"]
        entry = {**definition, "value": value, "updated_at": row.updated_at if row else None}
        if definition["type"] == "model":
            entry["options"] = choices
            entry["unavailable"] = bool(value and value not in {option["value"] for option in entry["options"]})
            if entry["unavailable"]:
                entry["value"] = ""
        if definition["type"] == "generation":
            key = definition["key"]
            entry["value"] = defaults[key]
            values = choice["capabilities"][GENERATION_DEFAULT_FIELDS[key]] if choice else []
            entry["options"] = [{"value": str(item), "label":
                ({"9:16": "竖屏 9:16", "16:9": "横屏 16:9", "1:1": "方形 1:1"}.get(str(item), str(item))
                 if key == "default_aspect_ratio" else f"{item} 秒" if key == "default_seconds" else str(item))}
                for item in values]
        if definition["type"] == "proxy":
            current = decode_proxy_url(value)
            masked = redact_proxy_url(current)
            # A blank field preserves the stored address. Do not resubmit internal
            # proxy URLs when saving unrelated settings through a public WAF.
            entry.update(value="", current_proxy=masked,
                         default=redact_proxy_url(definition["default"]))
        data.append(entry)
    return data


def validate_proxy_choices(db: Session) -> None:
    # Flush once after all fields have been validated so enable/address changes
    # are checked together. The route rolls the entire transaction back on error.
    db.flush()
    for kind, label in (("request", "请求"), ("download", "下载")):
        if get_system_setting_bool(db, kind + "_proxy_enabled") and not stored_proxy_url(db, kind):
            raise ValueError(label + "代理已开启，请填写代理地址。")


def settings_audit_values(db: Session, values: dict) -> dict:
    return {key: redact_proxy_url(stored_proxy_url(db, key.removesuffix("_proxy_url")))
            if key in PROXY_KEYS else value for key, value in values.items()}
