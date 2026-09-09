"""手动触发卡住任务的重新轮询"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app.db import SessionLocal
from app.models.tables import Job
from app.services.jobs import add_event
from app.services.worker_common import utcnow
from sqlalchemy import text

def force_repoll_stuck_jobs():
    """强制重新轮询卡住的任务"""

    with SessionLocal() as db:
        # 查找可能卡住的任务
        result = db.execute(text("""
            SELECT id, status, progress, remote_task_id, updated_at
            FROM jobs
            WHERE status IN ('submitted', 'polling')
              AND remote_task_id IS NOT NULL
              AND updated_at < NOW() - INTERVAL '5 minutes'
            ORDER BY updated_at ASC
            LIMIT 20
        """))

        jobs = result.fetchall()

        if not jobs:
            print("没有发现卡住的任务")
            return

        print(f"\n发现 {len(jobs)} 个可能卡住的任务\n")

        for job_row in jobs:
            job_id = job_row.id
            print(f"处理任务 {job_id} (状态={job_row.status}, 进度={job_row.progress}%)")

            # 添加 poll_watchdog 事件触发重新轮询
            add_event(
                db,
                job_id,
                "info",
                "poll_watchdog",
                f"手动触发重新轮询 (任务可能卡住)",
                {"manual_trigger": True}
            )

        db.commit()
        print(f"\n✓ 已触发 {len(jobs)} 个任务的重新轮询")
        print("请等待 worker 处理(2-5秒)")

if __name__ == "__main__":
    force_repoll_stuck_jobs()
