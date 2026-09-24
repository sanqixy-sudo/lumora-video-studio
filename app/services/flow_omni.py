"""OAIREGBOX Flow Omni: text/image generation only.

Contract: https://docs.oairegbox.cc/#flow-omni
"""
DEFAULT_BASE_URL = "https://api.oairegbox.cc"
MODEL = "flow-omni-1.1-flash"
SECONDS = 8  # Approximate output length; the upstream request has no duration field.
MAX_IMAGES = 6


def build_payload(prompt, seconds, size, image_urls, reference_video_url=None):
    if reference_video_url:
        raise ValueError("Flow Omni 仅支持文生视频和图生视频，不支持视频编辑")
    if int(seconds) != SECONDS:
        raise ValueError("Flow Omni 仅支持约 8 秒视频")
    if size not in {"720x1280", "1280x720"}:
        raise ValueError("Flow Omni 仅支持 720p 横屏或竖屏")
    if len(image_urls) > MAX_IMAGES:
        raise ValueError("Flow Omni 最多支持 6 张参考图")
    payload = {"model": MODEL, "prompt": prompt, "resolution": "720p",
               "aspect_ratio": "9:16" if size == "720x1280" else "16:9"}
    if image_urls:
        payload["images"] = list(image_urls)
    return payload


def normalize_response(data):
    # Only documented output fields are eligible. Never treat echoed reference
    # images, request URLs, or an in-progress preview as the finished video.
    out = {key: value for key, value in data.items() if key not in {"url", "video_url", "download_url", "result"}}
    task_id = data.get("task_id") or data.get("id")
    if task_id:
        out["id"] = out["task_id"] = str(task_id)
    status = str(data.get("status") or "").strip().lower()
    out["status"] = status
    if status in {"queued", "in_progress"}:
        # Shared workers treat 100% as complete; this API uses status as truth.
        try:
            out["progress"] = min(99, max(0, int(data.get("progress") or 0)))
        except (TypeError, ValueError):
            out.pop("progress", None)
    if status == "completed":
        items = data.get("data")
        first = items[0] if isinstance(items, list) and items and isinstance(items[0], dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        for value in (data.get("video_url"), first.get("url"), metadata.get("url")):
            if isinstance(value, str) and value.startswith(("https://", "http://")):
                out.update(video_url=value, url=value, result=[value], progress=100)
                break
    out["_raw"] = data
    return out
