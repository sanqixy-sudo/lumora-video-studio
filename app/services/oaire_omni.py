"""OAIREGBOX Omni Fast: text and up to five reference images.

Contract: https://docs.oairegbox.cc/#omni
"""
from app.services.flow_omni import normalize_response

DEFAULT_BASE_URL = "https://api.oairegbox.cc"
DEFAULT_MODEL = "omni-fast"
MODELS = frozenset({"omni-fast", "omni-fast-no-water"})
SECONDS = 10  # The upstream currently produces roughly ten seconds regardless of input.
MAX_IMAGES = 5


def build_payload(prompt, seconds, size, image_urls, model=DEFAULT_MODEL, reference_video_url=None):
    if reference_video_url:
        raise ValueError("oaire omni 仅支持文生视频和图生视频，不支持视频编辑")
    if int(seconds) != SECONDS:
        raise ValueError("oaire omni 仅支持约 10 秒视频")
    if size not in {"720x1280", "1280x720"}:
        raise ValueError("oaire omni 仅支持横屏或竖屏")
    if model not in MODELS:
        raise ValueError("oaire omni 仅支持 omni-fast 或 omni-fast-no-water")
    if len(image_urls) > MAX_IMAGES:
        raise ValueError("oaire omni 最多支持 5 张参考图")
    payload = {"model": model, "prompt": prompt,
               "aspect_ratio": "9:16" if size == "720x1280" else "16:9"}
    if image_urls:
        payload["images"] = list(image_urls)
    return payload
