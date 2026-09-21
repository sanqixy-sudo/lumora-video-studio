from urllib.parse import urlsplit
from fastapi import HTTPException, Request


def _origin(value: str) -> tuple[str, str, int] | None:
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return None
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def require_same_origin(request: Request) -> None:
    source = request.headers.get("origin")
    if source is None:
        source = request.headers.get("referer", "")
    if (request.headers.get("sec-fetch-site") == "cross-site"
            or _origin(source) is None
            or _origin(source) != _origin(str(request.base_url))):
        raise HTTPException(status_code=403, detail="请求来源无效，请刷新页面后重试")

