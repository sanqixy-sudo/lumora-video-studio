from __future__ import annotations

import re
from urllib.parse import quote

from sqlalchemy.orm import Session

from app.models.tables import Job, User, UserProfile


INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _clean_part(value: object, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        text = fallback
    text = INVALID_FILENAME_CHARS.sub("-", text).strip(" .-_")
    return text[:80] or fallback


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if value is None:
        return False
    return False


def job_video_download_filename(db: Session, job: Job) -> str:
    owner = db.query(User).filter(User.id == job.user_id).first()
    profile = db.query(UserProfile).filter(UserProfile.user_id == job.user_id).first()
    product = _clean_part(getattr(job, "product_name", None), "APP")
    region = _clean_part(getattr(job, "region_name", None), "地区")
    account_name = _clean_part((profile.display_name if profile else None) or (owner.username if owner else None), f"user{job.user_id}")
    sequence = _clean_part(getattr(job, "batch_index", None) or job.id, str(job.id))
    prefix = "不共用-" if _is_enabled(getattr(job, "is_private_protected", False)) else ""
    return f"{prefix}{product}-{region}-{account_name}-{sequence}.mp4"


def attachment_disposition(filename: str) -> str:
    ascii_fallback = INVALID_FILENAME_CHARS.sub("-", filename).encode("ascii", "ignore").decode("ascii").strip(" .-_")
    if not ascii_fallback:
        ascii_fallback = "video.mp4"
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{quote(filename)}'
