from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from app.deps import get_current_user, get_db
from app.models.tables import Job, JobFile, User
from app.services.download_names import job_video_download_filename
from app.services.media import create_video_poster

router = APIRouter(prefix="/app/files", tags=["files"])
CHUNK_SIZE = 1024 * 1024


@router.get("/{file_id}/download")
def download_file(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    row = _load_authorized_file(file_id, current_user, db)
    path = Path(row.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="磁盘文件不存在")
    filename = row.file_name
    if row.file_type == "output_video":
        job = db.query(Job).filter(Job.id == row.job_id).first()
        if job:
            filename = job_video_download_filename(db, job)
    return FileResponse(path=path, filename=filename, media_type=row.mime_type or "application/octet-stream")


@router.get("/{file_id}/stream")
def stream_file(
    file_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    range_header: str | None = Header(default=None, alias="Range"),
):
    row = _load_authorized_file(file_id, current_user, db)
    path = Path(row.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="磁盘文件不存在")
    file_size = path.stat().st_size
    media_type = row.mime_type or "application/octet-stream"
    if not range_header:
        return FileResponse(path=path, media_type=media_type, filename=row.file_name, headers={"Accept-Ranges": "bytes"})
    start, end = _parse_range(range_header, file_size)
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Content-Length": str(end - start + 1),
    }
    return StreamingResponse(
        _range_file_iterator(path, start, end),
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


@router.get("/{file_id}/poster")
def file_poster(file_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> FileResponse:
    row = _load_authorized_file(file_id, current_user, db)
    if row.file_type != "output_video":
        raise HTTPException(status_code=404, detail="封面不存在")
    video_path = Path(row.file_path)
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="视频文件不存在")
    poster_path = create_video_poster(video_path)
    if not poster_path or not poster_path.exists():
        raise HTTPException(status_code=404, detail="封面生成失败")
    return FileResponse(path=poster_path, media_type="image/jpeg", filename=poster_path.name)


def _load_authorized_file(file_id: int, current_user: User, db: Session) -> JobFile:
    row = db.query(JobFile).join(Job, Job.id == JobFile.job_id).filter(JobFile.id == file_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="文件不存在")
    job = db.query(Job).filter(Job.id == row.job_id).first()
    if current_user.role in {"admin", "sub_admin"}:
        return row
    if job and job.user_id == current_user.id:
        return row
    owner = db.query(User).filter(User.id == (job.user_id if job else None)).first()
    if job and owner and owner.showcase_enabled and job.status == "completed" and row.file_type == "output_video":
        return row
    raise HTTPException(status_code=403, detail="无权访问该文件")


def _parse_range(range_header: str, file_size: int) -> tuple[int, int]:
    try:
        units, _, value = range_header.partition("=")
        if units != "bytes":
            raise ValueError
        start_str, _, end_str = value.partition("-")
        if not start_str and not end_str:
            raise ValueError
        if start_str:
            start = int(start_str)
            end = int(end_str) if end_str else file_size - 1
        else:
            suffix_length = int(end_str)
            if suffix_length <= 0:
                raise ValueError
            start = max(file_size - suffix_length, 0)
            end = file_size - 1
        if start < 0 or end >= file_size or start > end:
            raise ValueError
        return start, end
    except ValueError as exc:
        raise HTTPException(status_code=416, detail="Range 头无效") from exc


def _range_file_iterator(path: Path, start: int, end: int):
    with path.open("rb") as file_handle:
        file_handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = file_handle.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
