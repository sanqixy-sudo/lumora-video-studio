import os
import sys

# 设置环境
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(os.path.dirname(__file__))

try:
    from app.db import SessionLocal
    from app.models.tables import Job
    from sqlalchemy import text

    print("正在连接数据库...")

    with SessionLocal() as db:
        # 查询活跃任务
        result = db.execute(text("""
            SELECT id, status, progress, remote_task_id,
                   created_at, updated_at, submitted_at
            FROM jobs
            WHERE status IN ('submitted', 'polling', 'remote_completed', 'download_waiting', 'downloading')
            ORDER BY updated_at ASC
            LIMIT 20
        """))

        jobs = result.fetchall()

        if not jobs:
            print("✓ 没有活跃任务")
        else:
            print(f"\n发现 {len(jobs)} 个活跃任务:\n")
            for job in jobs:
                print(f"ID={job.id:4d} | 状态={job.status:16s} | 进度={job.progress:3d}% | 更新时间={job.updated_at}")

            # 查询最近的事件
            print("\n最近的任务事件:")
            events = db.execute(text("""
                SELECT job_id, event_type, message, created_at
                FROM job_events
                WHERE job_id IN (
                    SELECT id FROM jobs
                    WHERE status IN ('submitted', 'polling', 'remote_completed', 'download_waiting', 'downloading')
                )
                ORDER BY created_at DESC
                LIMIT 10
            """))

            for evt in events:
                print(f"  任务{evt.job_id} [{evt.created_at}] {evt.event_type}: {evt.message[:60]}")

except Exception as e:
    print(f"错误: {e}")
    import traceback
    traceback.print_exc()
