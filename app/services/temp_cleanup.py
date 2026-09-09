from __future__ import annotations

import logging
import time

from app.core.config import settings

logger = logging.getLogger(__name__)


def cleanup_library_bulk_zips(max_age_seconds: int = 86400) -> int:
    temp_dir = settings.files_temp_dir
    if not temp_dir.exists():
        return 0
    cutoff = time.time() - max(int(max_age_seconds or 86400), 3600)
    removed = 0
    for pattern in ("library_bulk_*.zip", "batch_bulk_*.zip"):
        for path in temp_dir.glob(pattern):
            try:
                if path.is_file() and path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                logger.warning("Failed to remove stale bulk zip: %s", path)
    return removed
