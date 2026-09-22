from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from app.core.config import settings


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
    source_origin = _origin(source)
    target_origin = _origin(str(request.base_url))
    public_origin = _origin(settings.public_origin)
    # Trust only the explicitly configured public origin, for this same Host.
    # Do not accept arbitrary Forwarded/X-Forwarded-* headers from clients.
    public_match = (
        public_origin is not None
        and source_origin == public_origin
        and urlsplit(str(request.base_url)).netloc.lower() == urlsplit(settings.public_origin).netloc.lower()
    )
    if (request.headers.get("sec-fetch-site") == "cross-site"
            or source_origin is None
            or (source_origin != target_origin and not public_match)):
        raise HTTPException(status_code=403, detail="请求来源无效，请刷新页面后重试")

