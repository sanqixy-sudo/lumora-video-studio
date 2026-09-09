import logging
import time
from app.core.config import settings
from app.services.bootstrap import ensure_dirs
from app.services.worker_runtime import mark_inflight_jobs_interrupted, process_once

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def main() -> None:
    ensure_dirs()
    loop_interval = min(max(int(settings.worker_poll_interval or 2), 1), 5)
    logger.info('Worker started. Configured poll interval=%ss; loop interval=%ss', settings.worker_poll_interval, loop_interval)
    mark_inflight_jobs_interrupted()
    while True:
        process_once()
        time.sleep(loop_interval)


if __name__ == '__main__':
    main()
