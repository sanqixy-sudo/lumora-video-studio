from __future__ import annotations

import math
from urllib.parse import urlparse, urlunparse

import httpx
from PIL import ImageFile, UnidentifiedImageError

from app.core.config import settings

SUPPORTED_VIDEO_SIZES = {"720x1280", "1280x720"}
SUPPORTED_SECONDS = {4, 5, 8, 10, 12, 15}
IMAGE_FETCH_TIMEOUT = 20
IMAGE_DIMENSION_READ_LIMIT = 2 * 1024 * 1024



def normalize_public_image_url(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme:
        text = "https://" + text
        parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("图片链接必须是 http 或 https 公网地址")
    return urlunparse(parsed._replace(fragment=""))


def parse_video_size(size: str) -> tuple[int, int]:
    try:
        width_text, height_text = str(size or "").lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (TypeError, ValueError) as exc:
        raise ValueError("不支持的分辨率") from exc
    if f"{width}x{height}" not in SUPPORTED_VIDEO_SIZES:
        raise ValueError("不支持的分辨率")
    return width, height


def aspect_ratio_for_size(size: str) -> str:
    width, height = parse_video_size(size)
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height // divisor}"


def aspect_ratio_for_dimensions(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return "-"
    divisor = math.gcd(int(width), int(height))
    return f"{int(width) // divisor}:{int(height) // divisor}"


def dimensions_match_size_ratio(width: int, height: int, size: str) -> bool:
    """Return True only when the reference image exactly matches the selected 720p video resolution."""
    expected_width, expected_height = parse_video_size(size)
    return int(width) == expected_width and int(height) == expected_height


def supported_reference_size_label() -> str:
    return "720x1280（竖屏）或 1280x720（横屏）"


def dimensions_match_any_supported_size(width: int, height: int) -> bool:
    return f"{int(width)}x{int(height)}" in SUPPORTED_VIDEO_SIZES


def validate_seconds(seconds: int | str | None) -> int:
    try:
        value = int(seconds)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError("请选择视频秒数") from exc
    if value not in SUPPORTED_SECONDS:
        raise ValueError("视频秒数仅支持 4、5、8、10 或 12 秒")
    return value


def fetch_image_dimensions(url: str) -> tuple[int, int, str | None, int]:
    normalized = normalize_public_image_url(url)
    if not normalized:
        raise ValueError("请填写图片链接")
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; SoraDispatch/1.0)",
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=IMAGE_FETCH_TIMEOUT, follow_redirects=True) as client:
            with client.stream("GET", normalized, headers=headers) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type")
                if content_type and ("svg" in content_type.lower() or not content_type.lower().startswith("image/")):
                    raise ValueError("图片链接不是有效的 PNG/JPG/WebP 直链")
                parser = ImageFile.Parser()
                total = 0
                limit = int(settings.reference_image_max_bytes or 20 * 1024 * 1024)
                for chunk in response.iter_bytes():
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > limit:
                        limit_mb = max(1, limit // (1024 * 1024))
                        raise ValueError(f"参考图大小不能超过 {limit_mb}MB")
                    parser.feed(chunk)
                    if parser.image:
                        width, height = parser.image.size
                        response.close()
                        return int(width), int(height), content_type, total
                    if total >= IMAGE_DIMENSION_READ_LIMIT:
                        raise ValueError("图片尺寸无法快速读取，请换直链图片")
        raise ValueError("图片链接无法读取或不是有效图片")
    except ValueError:
        raise
    except httpx.HTTPStatusError as exc:
        raise ValueError(f"图片服务器返回 HTTP {exc.response.status_code}，请检查链接访问权限或稍后重试") from exc
    except httpx.TimeoutException as exc:
        raise ValueError("本机读取图片超时，请检查链接或稍后重试") from exc
    except httpx.RequestError as exc:
        raise ValueError("本机无法连接图片服务器，请检查链接或稍后重试") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("图片内容无法解析，请检查是否为 PNG/JPG/WebP 图片直链") from exc
