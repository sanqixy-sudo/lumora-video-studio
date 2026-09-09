"""Compatibility entrypoints for the background worker.

The implementation lives in worker_engine so routes and app.workers.main can keep
their stable imports while the worker internals are split into smaller pieces.
"""

from app.services.worker_engine import mark_inflight_jobs_interrupted, process_once, schedule_job_now

__all__ = ["mark_inflight_jobs_interrupted", "process_once", "schedule_job_now"]
