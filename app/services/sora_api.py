from __future__ import annotations

import json
import mimetypes
import time
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse, urlunparse

import httpx
import requests
from PIL import Image

from app.core.config import settings
from app.services.reference_images import aspect_ratio_for_size

DEFAULT_BASE_URL = "https://niubi.zeabur.app"
VALID_MODELS = {"sora-2-8s", "sora-2-12s"}
COMPLETED_STATUSES = {"completed", "complete", "succeeded", "success", "done"}
SEEDANCE_DEFAULT_MODELS = {
    5: "seedance-1.5-pro",
    10: "seedance-1.5-pro-10s",
    12: "seedance-1.5-pro-12s",
}


class UpstreamError(RuntimeError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        payload: str | None = None,
        latency_ms: int | None = None,
        endpoint: str | None = None,
        request_summary: str | None = None,
        error_code: str | None = None,
        upstream_response: object | None = None,
    ):
        super().__init__(message)
        self.error_message = message
        self.error_code = str(error_code) if error_code is not None else None
        self.upstream_response = upstream_response
        self.status_code = status_code
        self.payload = payload
        self.latency_ms = latency_ms
        self.endpoint = endpoint
        self.request_summary = request_summary


def _nonempty_value(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value if value.strip() else None
    if isinstance(value, (dict, list)):
        return value if value else None
    return value


def _nested_value(data: dict, *path: str):
    current = data
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current.get(key)
    return _nonempty_value(current)


def _message_text(value) -> str | None:
    value = _nonempty_value(value)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def extract_upstream_error(data: dict) -> tuple[str | None, str | None]:
    if not isinstance(data, dict):
        return None, None
    message_candidates = (
        _nested_value(data, "error", "message"),
        _nested_value(data, "data", "error", "message"),
        _nested_value(data, "data", "message"),
        _nested_value(data, "detail", "message"),
        _nested_value(data, "fail_reason"),
        _nested_value(data, "failure_reason"),
        _nested_value(data, "reason"),
        _nested_value(data, "message"),
        _nested_value(data, "detail"),
    )
    message = next((_message_text(value) for value in message_candidates if _nonempty_value(value) is not None), None)
    code_candidates = (
        _nested_value(data, "error", "code"),
        _nested_value(data, "data", "error", "code"),
        _nested_value(data, "error_code"),
        _nested_value(data, "code"),
    )
    code_value = next((value for value in code_candidates if _nonempty_value(value) is not None), None)
    error_code = str(code_value) if code_value is not None else None
    if message is None:
        message = _message_text(_nested_value(data, "status"))
    return message, error_code


def raw_task_response(data: dict) -> dict:
    raw = data.get("_raw") if isinstance(data, dict) else None
    return raw if isinstance(raw, dict) else data


def is_upstream_failure(data: dict) -> bool:
    raw = raw_task_response(data)
    status = str((data.get("status") if isinstance(data, dict) else None) or (raw.get("status") if isinstance(raw, dict) else None) or "").strip().lower()
    if status in {"failed", "error", "stopped", "cancelled", "canceled"}:
        return True
    error_value = raw.get("error") if isinstance(raw, dict) else None
    data_error = raw.get("data", {}).get("error") if isinstance(raw.get("data"), dict) else None
    if _nonempty_value(error_value) is not None or _nonempty_value(data_error) is not None:
        return True
    return any(
        _nested_value(raw, *path) is not None
        for path in (("fail_reason",), ("failure_reason",), ("reason",), ("detail", "message"), ("error_code",))
    )


def _raise_response_error(response: httpx.Response, fallback_message: str, data: dict | None = None) -> None:
    text = response.text
    upstream_response: object = data if isinstance(data, dict) else text
    error_message, error_code = extract_upstream_error(data or {})
    message = error_message or (text if text.strip() else fallback_message)
    raise UpstreamError(
        message,
        status_code=response.status_code,
        payload=text,
        error_code=error_code,
        upstream_response=upstream_response,
    )

def _headers(api_key: str, provider_name: str | None = None) -> dict[str, str]:
    if _provider_name(provider_name) == "wuyin_omni":
        return {"Authorization": api_key}
    return {"Authorization": f"Bearer {api_key}"}


def _timeout() -> httpx.Timeout:
    base = int(settings.sora_api_http_timeout or 120)
    return httpx.Timeout(connect=20, read=max(base, 30), write=30, pool=20)


def _status_timeout() -> httpx.Timeout:
    base = int(getattr(settings, "sora_api_status_http_timeout", 30) or 30)
    read_timeout = min(max(base, 10), max(int(settings.sora_api_http_timeout or 120), 10))
    return httpx.Timeout(connect=10, read=read_timeout, write=15, pool=10)


def normalize_api_base_url(value: str | None) -> str:
    raw = str(value or settings.sora_api_base_url or DEFAULT_BASE_URL).strip() or DEFAULT_BASE_URL
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    parsed = urlparse(raw)
    path = parsed.path.rstrip("/")
    for marker in (
        "/api/async/video_google_omni",
        "/api/async/detail",
        "/v1/videos/generations",
        "/videos/generations",
        "/v1/videos/status",
        "/videos/status",
        "/v1/videos",
        "/videos",
    ):
        index = path.find(marker)
        if index >= 0:
            path = path[:index].rstrip("/")
            break
    if path.endswith("/v1"):
        path = path[:-3].rstrip("/")
    return urlunparse((parsed.scheme, parsed.netloc, path, "", "", "")).rstrip("/")


def _api_url(api_base_url: str | None, path: str) -> str:
    return f"{normalize_api_base_url(api_base_url)}/v1{path}"


def _provider_name(value: str | None) -> str:
    text = str(value or "sora_api").strip().lower()
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
    return "sora_api"


def _model_for(seconds: int, model_id: str | None = None, provider_name: str | None = None) -> str:
    provider = _provider_name(provider_name)
    requested = str(model_id or "").strip()
    if requested:
        return requested
    if provider == "wuyin_omni":
        return "wuyin-omni"
    if provider == "seedance":
        return SEEDANCE_DEFAULT_MODELS.get(int(seconds), SEEDANCE_DEFAULT_MODELS[5])
    requested = str(settings.default_video_model or "").strip()
    expected = "sora-2-12s" if int(seconds) == 12 else "sora-2-8s"
    if requested in VALID_MODELS and requested == expected:
        return requested
    return expected


def _podsora_base_url(api_base_url: str | None) -> str:
    base = normalize_api_base_url(api_base_url)
    parsed = urlparse(base)
    netloc = "api.apipod.ai" if parsed.netloc.lower() == "www.apipod.ai" else parsed.netloc
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", "")).rstrip("/")


def _podsora_create_url(api_base_url: str | None) -> str:
    return f"{_podsora_base_url(api_base_url)}/v1/videos/generations"


def _podsora_status_url(api_base_url: str | None, remote_task_id: str) -> str:
    return f"{_podsora_base_url(api_base_url)}/v1/videos/status/{remote_task_id}"


def _wuyin_omni_create_url(api_base_url: str | None) -> str:
    return f"{normalize_api_base_url(api_base_url)}/api/async/video_google_omni"


def _wuyin_omni_status_url(api_base_url: str | None) -> str:
    return f"{normalize_api_base_url(api_base_url)}/api/async/detail"


def _first_url_from_value(value) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            found = _first_url_from_value(item)
            if found:
                return found
    if isinstance(value, dict):
        for key in ("video_url", "url", "download_url", "source_url"):
            found = _first_url_from_value(value.get(key))
            if found:
                return found
        for item in value.values():
            found = _first_url_from_value(item)
            if found:
                return found
    return None


def _normalize_task_response(data: dict) -> dict:
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    inner = inner if isinstance(inner, dict) else data
    task_id = inner.get("task_id") or inner.get("id") or data.get("task_id") or data.get("id")
    raw_status = inner.get("status") if inner.get("status") is not None else data.get("status")
    numeric_statuses = {0: "processing", 1: "processing", 2: "completed", 3: "failed"}
    try:
        numeric_status = int(raw_status) if str(raw_status).strip() in {"0", "1", "2", "3"} else None
    except (TypeError, ValueError):
        numeric_status = None
    status = numeric_statuses.get(numeric_status, str(raw_status or "").lower())
    progress = inner.get("progress") if inner.get("progress") is not None else data.get("progress")
    if numeric_status is not None:
        video_url = _first_url_from_value(inner.get("result"))
    else:
        video_url = _first_url_from_value(inner) or _first_url_from_value(data)
    if isinstance(inner.get("data"), list):
        video_url = _first_url_from_value(inner.get("data")) or video_url
    if isinstance(data.get("data"), list):
        video_url = _first_url_from_value(data.get("data")) or video_url
    if not status and video_url:
        status = "completed"
    if video_url and progress is None:
        progress = 100
    if numeric_status == 2:
        progress = 100
    if video_url and (not status or status == "processing") and int(progress or 0) >= 100:
        status = "completed"
    out = dict(inner)
    if task_id:
        out["id"] = str(task_id)
        out["task_id"] = str(task_id)
    if status:
        out["status"] = status
    if progress is not None:
        try:
            out["progress"] = int(progress)
        except (TypeError, ValueError):
            out["progress"] = progress
    if video_url:
        out["video_url"] = video_url
        out["url"] = video_url
        out["result"] = [video_url]
    out["_raw"] = data
    return out


def extract_task_id_from_payload(payload: str | None) -> str | None:
    if not payload:
        return None
    try:
        data = json.loads(payload)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    normalized = _normalize_task_response(data)
    task_id = normalized.get("task_id") or normalized.get("id")
    return str(task_id).strip() if task_id else None


def _request_json_or_raise(response: httpx.Response, message: str) -> dict:
    text = response.text
    try:
        data = response.json()
    except Exception as exc:
        if response.status_code >= 400:
            _raise_response_error(response, message)
        raise UpstreamError(message, status_code=response.status_code, payload=text, upstream_response=text) from exc
    if not isinstance(data, dict):
        raise UpstreamError("Upstream returned unexpected response", status_code=response.status_code, payload=text, upstream_response=data)
    if response.status_code >= 400:
        _raise_response_error(response, message, data)
    body_code = data.get("code")
    if body_code is not None:
        try:
            parsed_code = int(body_code)
        except (TypeError, ValueError):
            parsed_code = 200
        if parsed_code >= 400 and not extract_task_id_from_payload(text) and not _first_url_from_value(data):
            error_message, error_code = extract_upstream_error(data)
            raise UpstreamError(
                error_message or message,
                status_code=parsed_code,
                payload=text,
                error_code=error_code,
                upstream_response=data,
            )
    return data

def _is_invalid_url_payload(payload: str | None) -> bool:
    text = str(payload or "").lower()
    return "invalid url" in text or "not found" in text or "404" in text


def create_video_endpoint(api_base_url: str | None = None, provider_name: str | None = None) -> str:
    provider = _provider_name(provider_name)
    if provider == "wuyin_omni":
        return _wuyin_omni_create_url(api_base_url)
    if provider in {"podsora", "podgrok"}:
        return _podsora_create_url(api_base_url)
    return _api_url(api_base_url, "/videos")


def create_video_request_summary(
    prompt: str,
    seconds: int,
    size: str,
    reference_image_url: str | None = None,
    api_base_url: str | None = None,
    model_id: str | None = None,
    provider_name: str | None = None,
    reference_video_url: str | None = None,
    reference_image_urls: list[str] | tuple[str, ...] | None = None,
) -> str:
    provider = _provider_name(provider_name)
    model = _model_for(int(seconds), model_id, provider)
    image_urls = _reference_image_urls(reference_image_url, reference_image_urls)
    if provider == "veo_omni":
        model = "veo-omni-flash-video-edit" if reference_video_url else "veo-omni-flash"
    aspect_ratio = aspect_ratio_for_size(size)
    ref_host = ""
    if image_urls:
        try:
            ref_host = f", ref_host={urlparse(image_urls[0]).netloc}"
        except Exception:
            ref_host = ""
    return (
        f"provider={provider}, model={model}, duration={int(seconds)}, "
        f"size={size}, aspect_ratio={aspect_ratio}, image_count={len(image_urls)}, "
        f"video={'yes' if reference_video_url else 'no'}"
        f"{ref_host}, prompt_chars={len(prompt or '')}"
    )


def _reference_image_urls(
    reference_image_url: str | None,
    reference_image_urls: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    values = list(reference_image_urls or [])
    if reference_image_url:
        values.insert(0, reference_image_url)
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            cleaned.append(text)
            seen.add(text)
    return cleaned


def _reference_image_file(reference_image_url: str | None, input_reference_path: Path | None = None) -> tuple[str, bytes, str] | None:
    if input_reference_path:
        content_type = mimetypes.guess_type(str(input_reference_path))[0] or "application/octet-stream"
        return input_reference_path.name, input_reference_path.read_bytes(), content_type
    if not reference_image_url:
        return None
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=httpx.Timeout(connect=10, read=30, write=10, pool=10), follow_redirects=True) as client:
            response = client.get(reference_image_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*;q=0.8"})
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        raise UpstreamError(f"Fetch reference image request error after {latency_ms}ms", payload=str(exc), latency_ms=latency_ms) from exc
    if response.status_code >= 400:
        raise UpstreamError("Fetch reference image failed", status_code=response.status_code, payload=response.text[:1000])
    content = response.content
    if not content:
        raise UpstreamError("Fetch reference image failed: empty file", status_code=502)
    if len(content) > int(settings.reference_image_max_bytes):
        limit_mb = max(1, int(settings.reference_image_max_bytes) // (1024 * 1024))
        raise UpstreamError(f"Reference image exceeds {limit_mb}MB")
    parsed = urlparse(reference_image_url)
    filename = Path(parsed.path or "reference.png").name or "reference.png"
    content_type = response.headers.get("content-type", "").split(";", 1)[0].strip()
    if not content_type or not content_type.startswith("image/"):
        content_type = mimetypes.guess_type(filename)[0] or "image/png"
    if content_type not in {"image/png", "image/jpeg"}:
        try:
            with Image.open(BytesIO(content)) as image:
                output = BytesIO()
                image.convert("RGB").save(output, format="PNG")
                content = output.getvalue()
                filename = f"{Path(filename).stem or 'reference'}.png"
                content_type = "image/png"
        except Exception as exc:
            raise UpstreamError("Reference image cannot be converted for upload", payload=str(exc)) from exc
    return filename, content, content_type


def create_video(
    api_key: str,
    prompt: str,
    seconds: int,
    size: str,
    input_reference_path: Path | None = None,
    reference_image_url: str | None = None,
    api_base_url: str | None = None,
    model_id: str | None = None,
    provider_name: str | None = None,
    idempotency_key: str | None = None,
    reference_video_url: str | None = None,
    reference_image_urls: list[str] | tuple[str, ...] | None = None,
) -> tuple[dict, int, int]:
    url = create_video_endpoint(api_base_url, provider_name)
    provider = _provider_name(provider_name)
    image_urls = _reference_image_urls(reference_image_url, reference_image_urls)
    if provider not in {"seedance"} and input_reference_path and not image_urls:
        raise UpstreamError("Reference images must be public URLs and sent as image_url")
    model = _model_for(int(seconds), model_id, provider)
    if provider == "wuyin_omni":
        if int(seconds) != 10:
            raise UpstreamError("Wuyin Omni only supports 10-second videos")
        if len(image_urls) > 1:
            raise UpstreamError("Wuyin Omni supports at most one reference image")
        payload: dict = {"prompt": prompt, "duration": "10", "size": size}
        if image_urls:
            payload["images"] = image_urls[0]
        if reference_video_url:
            payload["video"] = reference_video_url
    else:
        if provider != "veo_omni" and len(image_urls) > 1:
            raise UpstreamError("This provider supports at most one reference image")
        if provider != "veo_omni" and reference_video_url:
            raise UpstreamError("Reference video is not supported by this provider")
        if provider == "veo_omni":
            if int(seconds) != 10:
                raise UpstreamError("VEO Omni only supports 10-second videos")
            if len(image_urls) > 6:
                raise UpstreamError("VEO Omni supports at most six reference images")
            if not reference_video_url and not image_urls:
                raise UpstreamError("VEO Omni multi-image mode requires at least one reference image")
            model = "veo-omni-flash-video-edit" if reference_video_url else "veo-omni-flash"
        payload = {
            "model": model,
            "prompt": prompt,
            "duration": int(seconds),
            "aspect_ratio": aspect_ratio_for_size(size),
        }
        if provider == "veo_omni":
            if image_urls:
                payload["Ingredients_images"] = image_urls
            if reference_video_url:
                payload["video_url"] = reference_video_url
    if provider == "podgrok":
        payload["resolution"] = "720p"
    if image_urls and provider not in {"wuyin_omni", "veo_omni"}:
        payload["image_url"] = image_urls[0]

    request_summary = create_video_request_summary(
        prompt,
        seconds,
        size,
        image_urls[0] if image_urls else None,
        api_base_url,
        model,
        provider,
        reference_video_url,
        reference_image_urls=image_urls,
    )
    headers = _headers(api_key, provider)
    if idempotency_key and provider != "wuyin_omni":
        headers["Idempotency-Key"] = str(idempotency_key)
        headers["X-Request-ID"] = str(idempotency_key)
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=_timeout()) as client:
            if provider == "wuyin_omni":
                response = client.post(
                    url,
                    headers={**headers, "Content-Type": "application/json"},
                    params={"key": api_key},
                    json=payload,
                )
            elif provider == "seedance":
                files: list[tuple[str, tuple]] = [
                    ("model", (None, model)),
                    ("prompt", (None, prompt)),
                    ("size", (None, size)),
                    ("seconds", (None, str(int(seconds)))),
                ]
                image_file = _reference_image_file(image_urls[0] if image_urls else None, input_reference_path)
                if image_file:
                    files.append(("image", image_file))
                response = client.post(url, headers=headers, files=files)
            elif provider in {"podsora", "podgrok"}:
                response = client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
            else:
                response = client.post(url, headers={**headers, "Content-Type": "application/json"}, json=payload)
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        raise UpstreamError(
            f"Create video request error after {latency_ms}ms",
            payload=str(exc),
            latency_ms=latency_ms,
            endpoint=url,
            request_summary=request_summary,
        ) from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        data = _request_json_or_raise(response, "Create video failed")
    except UpstreamError as exc:
        exc.latency_ms = latency_ms
        exc.endpoint = url
        exc.request_summary = request_summary
        raise
    normalized = _normalize_task_response(data)
    normalized["model"] = str(normalized.get("model") or model)
    return normalized, response.status_code, latency_ms


def fetch_video_status(api_key: str, remote_task_id: str, api_base_url: str | None = None, provider_name: str | None = None) -> tuple[dict, int, int]:
    provider = _provider_name(provider_name)
    if provider == "wuyin_omni":
        url = _wuyin_omni_status_url(api_base_url)
    elif provider in {"podsora", "podgrok"}:
        url = _podsora_status_url(api_base_url, remote_task_id)
    else:
        url = _api_url(api_base_url, f"/videos/{remote_task_id}")
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=_status_timeout()) as client:
            if provider == "wuyin_omni":
                response = client.get(url, headers=_headers(api_key, provider), params={"key": api_key, "id": remote_task_id})
            else:
                response = client.get(url, headers=_headers(api_key, provider))
    except httpx.HTTPError as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        raise UpstreamError(f"Fetch status request error after {latency_ms}ms", payload=str(exc), latency_ms=latency_ms, endpoint=url) from exc
    latency_ms = int((time.perf_counter() - started) * 1000)
    try:
        data = _request_json_or_raise(response, "Fetch status failed")
    except UpstreamError as exc:
        exc.latency_ms = latency_ms
        exc.endpoint = url
        raise
    return _normalize_task_response(data), response.status_code, latency_ms


def _download_url(video_url: str, dest_path: Path, started: float) -> tuple[dict, int, int]:
    temp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if temp_path.exists():
            temp_path.unlink()
    except Exception:
        pass
    try:
        with requests.get(video_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"}, stream=True, timeout=(20, 90), allow_redirects=True) as response:
            latency_ms = int((time.perf_counter() - started) * 1000)
            if response.status_code >= 400:
                raise UpstreamError("Download video failed", status_code=response.status_code, payload=response.text[:2000], latency_ms=latency_ms)
            bytes_written = 0
            with temp_path.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        fh.write(chunk)
                        bytes_written += len(chunk)
            if bytes_written <= 0:
                raise UpstreamError("Download video failed: empty file", status_code=502, payload=f"source_url={video_url}", latency_ms=latency_ms)
            temp_path.replace(dest_path)
            return {
                "content_type": response.headers.get("content-type") or "video/mp4",
                "content_length": response.headers.get("content-length"),
                "bytes_written": bytes_written,
                "source_url": video_url,
                "resolver": "status_video_url",
            }, response.status_code, latency_ms
    except requests.RequestException as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        raise UpstreamError(f"Download video request error after {latency_ms}ms", payload=str(exc), latency_ms=latency_ms) from exc


def download_video(
    api_key: str,
    remote_task_id: str,
    dest_path: Path,
    api_base_url: str | None = None,
    provider_name: str | None = None,
    known_video_url: str | None = None,
) -> tuple[dict, int, int]:
    started = time.perf_counter()
    video_url = known_video_url
    status_data: dict | None = None
    if not video_url:
        status_data, _status_code, _latency_ms = fetch_video_status(api_key, remote_task_id, api_base_url, provider_name)
        video_url = status_data.get("video_url") or status_data.get("url")
    if not video_url:
        if status_data and is_upstream_failure(status_data):
            raw_response = raw_task_response(status_data)
            error_message, error_code = extract_upstream_error(raw_response)
            raise UpstreamError(
                error_message or "Upstream task failed",
                status_code=_status_code,
                payload=json.dumps(raw_response, ensure_ascii=False),
                error_code=error_code,
                upstream_response=status_data,
            )
        payload = compact_json(status_data or {"task_id": remote_task_id, "status": "processing"})
        raise UpstreamError("Remote result url not ready", status_code=425, payload=payload, upstream_response=status_data)
    return _download_url(video_url, dest_path, started)


def compact_json(data: dict) -> str:
    keep_keys = ["id", "task_id", "status", "progress", "error", "seconds", "duration", "size", "model", "object", "url", "video_url", "result"]
    keep = {key: data.get(key) for key in keep_keys if isinstance(data, dict) and key in data}
    return json.dumps(keep, ensure_ascii=False)


def remote_content_url(remote_task_id: str, api_base_url: str | None = None, provider_name: str | None = None) -> str:
    provider = _provider_name(provider_name)
    if provider == "wuyin_omni":
        return _wuyin_omni_status_url(api_base_url)
    if provider in {"podsora", "podgrok"}:
        return _podsora_status_url(api_base_url, remote_task_id)
    return _api_url(api_base_url, f"/videos/{remote_task_id}")


def open_video_stream(api_key: str, remote_task_id: str, api_base_url: str | None = None, provider_name: str | None = None):
    status_data, _status_code, _latency_ms = fetch_video_status(api_key, remote_task_id, api_base_url, provider_name)
    video_url = status_data.get("video_url") or status_data.get("url")
    if not video_url:
        raise UpstreamError("Remote download failed: result url not ready", status_code=404, payload=compact_json(status_data))
    client = httpx.Client(timeout=_timeout(), follow_redirects=True)
    try:
        request = client.build_request("GET", video_url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        response = client.send(request, stream=True)
    except Exception:
        client.close()
        raise
    if response.status_code >= 400:
        body = response.read().decode("utf-8", errors="ignore")
        response.close()
        client.close()
        raise UpstreamError("Remote download failed", status_code=response.status_code, payload=body)
    return response, client


def iter_video_stream(response, client):
    try:
        for chunk in response.iter_bytes():
            if chunk:
                yield chunk
    finally:
        response.close()
        client.close()
