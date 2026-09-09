import json
import mimetypes
import subprocess
from decimal import Decimal
from pathlib import Path


def guess_mime(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def probe_media(path: Path) -> dict:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
    except Exception:
        return {
            "mime_type": guess_mime(path),
            "file_size": path.stat().st_size if path.exists() else None,
            "duration_seconds": None,
            "width": None,
            "height": None,
            "playable": False,
        }

    duration = None
    width = None
    height = None
    playable = False
    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            width = stream.get("width")
            height = stream.get("height")
            playable = True
        if duration is None and stream.get("duration"):
            try:
                duration = Decimal(str(stream.get("duration"))).quantize(Decimal("0.01"))
            except Exception:
                pass
    if duration is None:
        fmt = data.get("format", {})
        if fmt.get("duration"):
            try:
                duration = Decimal(str(fmt.get("duration"))).quantize(Decimal("0.01"))
            except Exception:
                pass
    return {
        "mime_type": guess_mime(path),
        "file_size": path.stat().st_size if path.exists() else None,
        "duration_seconds": duration,
        "width": width,
        "height": height,
        "playable": playable,
    }


def poster_path_for(video_path: Path) -> Path:
    return video_path.with_name(f"{video_path.stem}_poster.jpg")


def create_video_poster(video_path: Path) -> Path | None:
    if not video_path.exists():
        return None
    poster_path = poster_path_for(video_path)
    if poster_path.exists() and poster_path.stat().st_mtime >= video_path.stat().st_mtime:
        return poster_path
    try:
        poster_path.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss",
                "0.1",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(poster_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except Exception:
        return None
    return poster_path if poster_path.exists() else None
