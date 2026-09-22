"""Disk-backed single-batch archives with bounded build concurrency and cleanup."""
from pathlib import Path
from threading import BoundedSemaphore
from uuid import uuid4
import shutil
import zipfile
from fastapi import HTTPException
from fastapi.responses import FileResponse
from app.core.config import settings

_build_slot = BoundedSemaphore(1)

class TemporaryArchiveResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            Path(self.path).unlink(missing_ok=True)


def build_batch_zip(files: list[tuple[Path, str]], filename: str):
    if not _build_slot.acquire(blocking=False):
        raise HTTPException(429, '服务器正在打包其他批次，请稍后再试。')
    archive_path = None
    try:
        settings.files_temp_dir.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        if not files:
            raise HTTPException(400, '本批次暂无可下载视频，请刷新后重试。')
        for source, _ in files:
            if not source.is_file():
                raise HTTPException(400, '部分视频已不可用，请刷新批次列表后重试。')
            total_bytes += source.stat().st_size
        if shutil.disk_usage(settings.files_temp_dir).free < total_bytes + 100 * 1024 * 1024:
            raise HTTPException(507, '服务器临时空间不足，请减少所选批次或联系管理员。')
        archive_path = settings.files_temp_dir / f'batch_{uuid4().hex}.zip'
        with zipfile.ZipFile(archive_path, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
            for source, name in files:
                archive.write(source, name)
        return TemporaryArchiveResponse(archive_path, filename=filename, media_type='application/zip', headers={'Cache-Control':'no-store'})
    except HTTPException:
        if archive_path:archive_path.unlink(missing_ok=True)
        raise
    except OSError as exc:
        if archive_path:archive_path.unlink(missing_ok=True)
        raise HTTPException(503, '打包失败，文件可能已变化或临时空间不足，请稍后重试。') from exc
    except Exception:
        if archive_path:archive_path.unlink(missing_ok=True)
        raise
    finally:
        _build_slot.release()
