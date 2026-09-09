#!/usr/bin/env python3
"""Paid, opt-in probe client for Wuyin Google Omni.

The script deliberately stays independent from the production application. It
captures the create response and every polling response without normalizing the
provider payload, while redacting the API key before anything is written.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, quote_plus, urlencode, urlparse
from urllib.request import Request, urlopen


CREATE_URL = "https://api.wuyinkeji.com/api/async/video_google_omni"
DETAIL_URL = "https://api.wuyinkeji.com/api/async/detail"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "probe_results" / "wuyin_google_omni"
ALLOWED_SIZES = ("1280x720", "720x1280", "1920x1080", "1080x1920")
REDACTED = "***REDACTED***"
URL_PATTERN = re.compile(r"https?://[^\s\"'<>\\]+", re.IGNORECASE)
VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".m4v"}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sanitize_text(value: str, secret: str | None = None) -> str:
    text = str(value)
    if secret:
        for variant in {secret, quote(secret, safe=""), quote_plus(secret)}:
            if variant:
                text = text.replace(variant, REDACTED)
    text = re.sub(
        r"([?&]key=)[^&#\s\"'<>]+",
        lambda match: f"{match.group(1)}{REDACTED}",
        text,
        flags=re.IGNORECASE,
    )
    return text


def sanitize_value(value: Any, secret: str | None = None) -> Any:
    """Recursively redact secrets and credential-shaped fields."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower().replace("-", "_")
            if lowered in {"authorization", "api_key", "apikey", "key"}:
                sanitized[str(key)] = REDACTED
            else:
                sanitized[str(key)] = sanitize_value(item, secret)
        return sanitized
    if isinstance(value, list):
        return [sanitize_value(item, secret) for item in value]
    if isinstance(value, tuple):
        return [sanitize_value(item, secret) for item in value]
    if isinstance(value, str):
        return sanitize_text(value, secret)
    return value


def write_json(path: Path, value: Any, secret: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(sanitize_value(value, secret), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def validate_web_url(value: str, label: str) -> str:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} must be a public HTTP/HTTPS URL")
    return text


def normalize_single_url(values: list[str] | None, label: str) -> str | None:
    if not values:
        return None
    if len(values) > 1:
        raise ValueError(f"Only one {label} URL is supported")
    return validate_web_url(values[0], label)


def build_payload(args: argparse.Namespace) -> dict[str, str]:
    payload = {
        "prompt": str(args.prompt).strip(),
        "size": args.size,
        "duration": "10",
    }
    if not payload["prompt"]:
        raise ValueError("prompt cannot be empty")
    image_url = normalize_single_url(args.image_url, "reference image")
    video_url = normalize_single_url(args.video_url, "reference video")
    if image_url:
        payload["images"] = image_url
    if video_url:
        payload["video"] = video_url
    return payload


def _decode_body(body: bytes) -> str:
    return body.decode("utf-8", errors="replace")


def _parse_json(text: str) -> tuple[Any | None, str | None]:
    if not text.strip():
        return None, "empty response body"
    try:
        return json.loads(text), None
    except json.JSONDecodeError as exc:
        return None, f"JSONDecodeError: {exc}"


def capture_headers(headers: Any) -> tuple[dict[str, str], list[dict[str, str]]]:
    """Keep a convenient mapping and a lossless ordered list of header pairs."""
    items = [(str(name), str(value)) for name, value in headers.items()] if headers else []
    return dict(items), [{"name": name, "value": value} for name, value in items]


def capture_http(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    """Make one request and return a lossless, serializable capture."""
    query_url = url
    if params:
        query_url = f"{url}{'&' if '?' in url else '?'}{urlencode(params)}"
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = Request(query_url, data=body, headers=request_headers, method=method.upper())
    started_at = utc_now()
    started = time.perf_counter()
    status_code: int | None = None
    response_headers: dict[str, str] = {}
    response_header_items: list[dict[str, str]] = []
    raw_body = b""
    error: str | None = None
    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = int(getattr(response, "status", response.getcode()))
            response_headers, response_header_items = capture_headers(response.headers)
            raw_body = response.read()
    except HTTPError as exc:
        status_code = int(exc.code)
        response_headers, response_header_items = capture_headers(exc.headers)
        raw_body = exc.read()
        error = f"HTTPError: {exc.reason}"
    except (URLError, TimeoutError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    raw_text = _decode_body(raw_body)
    json_body, json_error = _parse_json(raw_text)
    return {
        "requested_at": started_at,
        "method": method.upper(),
        "request_url": query_url,
        "request_headers": request_headers,
        "request_body": payload,
        "status_code": status_code,
        "response_headers": response_headers,
        "response_header_items": response_header_items,
        "raw_text": raw_text,
        "json_body": json_body,
        "json_error": json_error,
        "elapsed_ms": elapsed_ms,
        "error": error,
    }


def is_http_success(capture: dict[str, Any]) -> bool:
    status = capture.get("status_code")
    return isinstance(status, int) and 200 <= status < 300


def business_code(data: Any) -> int | str | None:
    if not isinstance(data, dict) or "code" not in data:
        return None
    value = data.get("code")
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value) if value is not None else None


def business_message(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    nested = data.get("data")
    candidates = [
        nested.get("message") if isinstance(nested, dict) else None,
        data.get("msg"),
        data.get("message"),
    ]
    for item in candidates:
        if item is None or item == "":
            continue
        if isinstance(item, (dict, list)):
            return json.dumps(item, ensure_ascii=False)
        return str(item)
    return None


def extract_task_id(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    nested = data.get("data")
    if isinstance(nested, dict):
        value = nested.get("id") or nested.get("task_id")
        if value:
            return str(value)
    value = data.get("id") or data.get("task_id")
    return str(value) if value else None


def extract_status(data: Any) -> int | str | None:
    if not isinstance(data, dict):
        return None
    nested = data.get("data")
    value = nested.get("status") if isinstance(nested, dict) else None
    if value is None:
        value = data.get("status")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def extract_url_entries(value: Any, path: str = "$") -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            entries.extend(extract_url_entries(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            entries.extend(extract_url_entries(item, f"{path}[{index}]"))
    elif isinstance(value, str):
        for match in URL_PATTERN.findall(value):
            entries.append({"path": path, "url": match.rstrip(",.;)]}")})
    return entries


def extract_capture_url_entries(capture: dict[str, Any]) -> list[dict[str, str]]:
    """Extract URLs from parsed JSON and from an unparseable raw response."""
    parsed = capture.get("json_body")
    if parsed is not None:
        return extract_url_entries(parsed)
    return extract_url_entries(str(capture.get("raw_text") or ""), "$raw")


def deduplicate_url_entries(entries: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        marker = (entry.get("path", ""), entry.get("url", ""))
        if marker in seen:
            continue
        seen.add(marker)
        unique.append(entry)
    return unique


def _is_video_candidate(entry: dict[str, str]) -> bool:
    url = entry.get("url", "")
    parsed = urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    response_path = entry.get("path", "").lower()
    path_hint = any(hint in response_path for hint in ("video", "result", "output", "file", "url"))
    return suffix in VIDEO_SUFFIXES or path_hint


def _download_extension(url: str, content_type: str) -> str:
    suffix = Path(urlparse(url).path).suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return suffix
    if "quicktime" in content_type:
        return ".mov"
    if "webm" in content_type:
        return ".webm"
    return ".mp4"


def download_video_candidates(
    entries: list[dict[str, str]],
    output_dir: Path,
    *,
    timeout: float,
    secret: str,
) -> list[dict[str, Any]]:
    """Download response URLs that identify themselves as video content."""
    results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    output_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        url = entry.get("url", "")
        if not url or url in seen_urls or not _is_video_candidate(entry):
            continue
        seen_urls.add(url)
        started = time.perf_counter()
        metadata: dict[str, Any] = {
            "source_path": entry.get("path"),
            "source_url": url,
            "requested_at": utc_now(),
        }
        try:
            request = Request(url, headers={"User-Agent": "WuyinGoogleOmniProbe/1.0", "Accept": "video/*,*/*"})
            with urlopen(request, timeout=timeout) as response:
                status = int(getattr(response, "status", response.getcode()))
                headers, header_items = capture_headers(response.headers)
                content_type = str(headers.get("Content-Type") or headers.get("content-type") or "").lower()
                suffix = Path(urlparse(url).path).suffix.lower()
                downloadable = content_type.startswith("video/") or "octet-stream" in content_type or suffix in VIDEO_SUFFIXES
                metadata.update(
                    {
                        "status_code": status,
                        "response_headers": headers,
                        "response_header_items": header_items,
                        "content_type": content_type,
                    }
                )
                if not downloadable:
                    metadata["skipped"] = "response is not video content"
                    results.append(sanitize_value(metadata, secret))
                    continue
                extension = _download_extension(url, content_type)
                destination = output_dir / f"result_{len([r for r in results if r.get('file_name')]) + 1:02d}{extension}"
                digest = hashlib.sha256()
                size = 0
                with destination.open("wb") as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                metadata.update(
                    {
                        "file_name": destination.name,
                        "file_size": size,
                        "sha256": digest.hexdigest(),
                    }
                )
        except HTTPError as exc:
            metadata.update({"status_code": exc.code, "error": f"HTTPError: {exc.reason}"})
        except (URLError, TimeoutError, OSError) as exc:
            metadata["error"] = f"{type(exc).__name__}: {exc}"
        metadata["elapsed_ms"] = int((time.perf_counter() - started) * 1000)
        results.append(sanitize_value(metadata, secret))
    return results


def create_run_directory(root: Path) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S_%fZ")
    run_dir = root / stamp
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _preview(payload: dict[str, str]) -> dict[str, Any]:
    return {
        "paid_request": False,
        "message": "Preview only. Re-run with --confirm-paid-request to call the provider.",
        "method": "POST",
        "url": f"{CREATE_URL}?key={REDACTED}",
        "headers": {"Authorization": REDACTED, "Content-Type": "application/json"},
        "payload": payload,
    }


def run_paid_probe(args: argparse.Namespace, api_key: str, payload: dict[str, str]) -> int:
    run_dir = create_run_directory(Path(args.output_root))
    started_at = utc_now()
    started = time.monotonic()
    summary: dict[str, Any] = {
        "started_at": started_at,
        "outcome": "running",
        "task_id": None,
        "poll_count": 0,
        "status_history": [],
        "errors": [],
        "output_directory": str(run_dir.resolve()),
    }
    all_urls: list[dict[str, str]] = []
    final_capture: dict[str, Any] | None = None
    exit_code = 1
    print(f"Capture directory: {run_dir.resolve()}")
    write_json(
        run_dir / "request.json",
        {
            "method": "POST",
            "url": f"{CREATE_URL}?key={api_key}",
            "headers": {"Authorization": api_key, "Content-Type": "application/json"},
            "payload": payload,
        },
        api_key,
    )

    try:
        create_capture = capture_http(
            "POST",
            CREATE_URL,
            headers={"Authorization": api_key, "Content-Type": "application/json", "Accept": "application/json"},
            params={"key": api_key},
            payload=payload,
            timeout=args.request_timeout,
        )
        write_json(run_dir / "create_response.json", create_capture, api_key)
        create_data = create_capture.get("json_body")
        all_urls.extend(extract_capture_url_entries(create_capture))
        if not is_http_success(create_capture):
            summary["outcome"] = "create_http_error"
            summary["errors"].append(create_capture.get("error") or f"HTTP {create_capture.get('status_code')}")
            return 2
        code = business_code(create_data)
        if code not in {None, 200}:
            summary["outcome"] = "create_business_error"
            summary["errors"].append(business_message(create_data) or f"business code {code}")
            return 2
        task_id = extract_task_id(create_data)
        if not task_id:
            summary["outcome"] = "missing_task_id"
            summary["errors"].append("Create response did not contain data.id")
            return 2
        summary["task_id"] = task_id
        print(f"Created remote task: {task_id}")

        previous_status: int | str | None = object()  # type: ignore[assignment]
        deadline = started + args.timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                summary["outcome"] = "timeout"
                summary["errors"].append(f"Polling exceeded {args.timeout:g} seconds")
                exit_code = 3
                break
            time.sleep(min(args.poll_interval, remaining))
            summary["poll_count"] += 1
            poll_capture = capture_http(
                "GET",
                DETAIL_URL,
                headers={"Authorization": api_key, "Accept": "application/json"},
                params={"key": api_key, "id": task_id},
                timeout=min(args.request_timeout, max(remaining, 1)),
            )
            poll_path = run_dir / f"poll_{summary['poll_count']:04d}.json"
            write_json(poll_path, poll_capture, api_key)
            poll_data = poll_capture.get("json_body")
            all_urls.extend(extract_capture_url_entries(poll_capture))

            if not is_http_success(poll_capture):
                message = poll_capture.get("error") or f"HTTP {poll_capture.get('status_code')}"
                summary["errors"].append(message)
                status_code = poll_capture.get("status_code")
                if isinstance(status_code, int) and 400 <= status_code < 500:
                    summary["outcome"] = "poll_http_error"
                    final_capture = poll_capture
                    exit_code = 2
                    break
                continue
            poll_code = business_code(poll_data)
            if poll_code not in {None, 200}:
                summary["outcome"] = "poll_business_error"
                summary["errors"].append(business_message(poll_data) or f"business code {poll_code}")
                final_capture = poll_capture
                exit_code = 2
                break
            status = extract_status(poll_data)
            if status != previous_status:
                summary["status_history"].append({"status": status, "observed_at": utc_now()})
                previous_status = status
                print(f"Remote status: {status!r}")
            if status == 2:
                summary["outcome"] = "success"
                final_capture = poll_capture
                exit_code = 0
                break
            if status == 3:
                summary["outcome"] = "remote_failed"
                summary["errors"].append(business_message(poll_data) or "Remote task failed")
                final_capture = poll_capture
                exit_code = 2
                break
    except KeyboardInterrupt:
        summary["outcome"] = "interrupted"
        summary["errors"].append("Interrupted by user")
        exit_code = 130
    except Exception as exc:  # The raw exception is part of the diagnostic result.
        summary["outcome"] = "client_error"
        summary["errors"].append(f"{type(exc).__name__}: {exc}")
        exit_code = 1
    finally:
        if final_capture is not None:
            write_json(run_dir / "final_response.json", final_capture, api_key)
        all_urls = deduplicate_url_entries(all_urls)
        write_json(run_dir / "urls.json", all_urls, api_key)
        downloads: list[dict[str, Any]] = []
        if summary.get("outcome") == "success" and not args.skip_download:
            try:
                input_urls = {value for value in (payload.get("images"), payload.get("video")) if value}
                result_urls = [entry for entry in all_urls if entry.get("url") not in input_urls]
                downloads = download_video_candidates(
                    result_urls,
                    run_dir / "downloads",
                    timeout=args.request_timeout,
                    secret=api_key,
                )
            except KeyboardInterrupt:
                summary["errors"].append("Interrupted while downloading result video")
            except Exception as exc:
                summary["errors"].append(f"Result download error: {type(exc).__name__}: {exc}")
        write_json(run_dir / "downloads.json", downloads, api_key)
        summary["discovered_url_count"] = len(all_urls)
        summary["downloaded_video_count"] = sum(1 for item in downloads if item.get("file_name"))
        summary["finished_at"] = utc_now()
        summary["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(run_dir / "summary.json", summary, api_key)
        print(f"Outcome: {summary['outcome']}")
        print(f"Saved capture: {run_dir.resolve()}")
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a real Wuyin Google Omni async task end-to-end.")
    parser.add_argument("--prompt", required=True, help="Video generation prompt (required).")
    parser.add_argument("--size", choices=ALLOWED_SIZES, default="1280x720")
    parser.add_argument("--image-url", action="append", help="One public reference image URL.")
    parser.add_argument("--video-url", action="append", help="One public reference video URL.")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Seconds between status requests.")
    parser.add_argument("--timeout", type=float, default=3600.0, help="Overall polling timeout in seconds.")
    parser.add_argument("--request-timeout", type=float, default=120.0, help="Timeout for each HTTP request.")
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Root directory for timestamped captures.",
    )
    parser.add_argument("--skip-download", action="store_true", help="Do not download discovered result videos.")
    parser.add_argument(
        "--confirm-paid-request",
        action="store_true",
        help="Required opt-in flag. Without it, only a redacted request preview is printed.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.poll_interval <= 0 or args.timeout <= 0 or args.request_timeout <= 0:
        parser.error("poll interval and timeout values must be positive")
    try:
        payload = build_payload(args)
    except ValueError as exc:
        parser.error(str(exc))
    if not args.confirm_paid_request:
        print(json.dumps(_preview(payload), ensure_ascii=False, indent=2))
        return 0
    api_key = str(os.getenv("WUYIN_API_KEY") or "").strip()
    if not api_key:
        api_key = getpass.getpass("WUYIN_API_KEY: ").strip()
    if not api_key:
        parser.error("WUYIN_API_KEY is required for a paid request")
    return run_paid_probe(args, api_key, payload)


if __name__ == "__main__":
    raise SystemExit(main())
