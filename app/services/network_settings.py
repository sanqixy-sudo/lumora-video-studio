"""Database-backed proxy choices, resolved using the caller's existing session."""
from __future__ import annotations

import base64
import hashlib
import re
from urllib.parse import urlsplit, unquote

from cryptography.fernet import Fernet
from app.core.config import settings
from app.models.tables import AppSetting
from app.services.crypto import _secret_bytes

PROXY_KEYS = {"request_proxy_url", "download_proxy_url"}
_PREFIX = "proxy:v1:"


def proxy_default(kind: str) -> str:
    return (settings.upstream_request_proxy if kind == "request" else settings.video_download_proxy).strip()


def validate_proxy_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (len(value) > 2048 or re.search(r"[\x00-\x20\x7f]", unquote(value))
                or parsed.scheme not in {"http", "https", "socks5", "socks5h"}
                or not parsed.hostname or not parsed.port or parsed.path not in {"", "/"}
                or parsed.query or parsed.fragment
                or any(c in parsed.hostname for c in '<>\\"')):
            raise ValueError
    except ValueError:
        raise ValueError("代理地址须为 http、https 或 socks5/socks5h 地址，包含主机和有效端口，不能包含路径或查询参数。") from None
    return value.rstrip("/")


def _fernet() -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(_secret_bytes()).digest()))


def encode_proxy_url(value: str) -> str:
    return _PREFIX + _fernet().encrypt(value.encode()).decode() if value else ""


def decode_proxy_url(value: str | None) -> str:
    if not value:
        return ""
    return _fernet().decrypt(value[len(_PREFIX):].encode()).decode() if value.startswith(_PREFIX) else value


def redact_proxy_url(value: str) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    if parsed.username is None and parsed.password is None:
        return value
    host = parsed.hostname or ""
    if ":" in host:
        host = "[" + host + "]"
    return f"{parsed.scheme}://***:***@{host}:{parsed.port}"


def stored_proxy_url(db, kind: str) -> str:
    row = db.query(AppSetting).filter(AppSetting.key == kind + "_proxy_url").first()
    return decode_proxy_url(row.value) if row else proxy_default(kind)


def get_proxy_url(db, kind: str) -> str:
    keys = {kind + "_proxy_enabled", kind + "_proxy_url"}
    values = {row.key: row.value for row in db.query(AppSetting).filter(AppSetting.key.in_(keys)).all()}
    url = decode_proxy_url(values[kind + "_proxy_url"]) if kind + "_proxy_url" in values else proxy_default(kind)
    enabled = values.get(kind + "_proxy_enabled")
    if enabled is None:
        enabled = "1" if proxy_default(kind) else "0"
    return url if enabled == "1" else ""


def proxy_options(db) -> dict[str, str]:
    return {"request_proxy": get_proxy_url(db, "request"), "download_proxy": get_proxy_url(db, "download")}
