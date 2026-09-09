"""诊断工具：检查卡住的任务和轮询状态"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timezone
from app.db import SessionLocal
from app.models.tables import Job, JobEvent, APICallLog
from app.services.worker_common import (
    _remote_poll_interval_seconds,
    _latest_event_at,
    _as_aware_utc,
    _remote_elapsed_seconds,
    utcnow
)

def diagnose_stuck_jobs():
    """诊断卡住的任务"""
    print("=" * 80)
    print("任务诊断工具")
    print("=" * 80)

    with SessionLocal() as db:
        # 查找所有活跃任务
        active_jobs = db.query(Job).filter(
            Job.status.in_({"submitted", "polling", "remote_completed", "download_waiting", "downloading"})
        ).order_by(Job.updated_at.asc()).all()

        if not active_jobs:
            print("\n✓ 没有发现活跃任务")
            return

        print(f"\n发现 {len(active_jobs)} 个活跃任务\n")

        for job in active_jobs:
            print(f"\n{'=' * 80}")
            print(f"任务 ID: {job.id}")
            print(f"状态: {job.status}")
            print(f"进度: {job.progress}%")
            print(f"远程任务 ID: {job.remote_task_id}")
            print(f"创建时间: {job.created_at}")
            print(f"更新时间: {job.updated_at}")
            print(f"已运行时长: {_remote_elapsed_seconds(job)} 秒")

            if job.status in {"submitted", "polling"}:
                # 检查轮询状态
                interval = _remote_poll_interval_seconds(job)
                print(f"\n当前轮询间隔: {interval} 秒")

                # 检查最后一次轮询时间
                last_poll_events = _latest_event_at(db, int(job.id), {
                    "poll_request_started", "poll_response_received",
                    "poll_heartbeat", "poll_progress", "poll_error"
                })

                if last_poll_events:
                    last_poll_events = _as_aware_utc(last_poll_events)
                    now = utcnow()
                    elapsed = (now - last_poll_events).total_seconds()
                    print(f"最后轮询时间: {last_poll_events} ({elapsed:.0f} 秒前)")

                    if elapsed > interval * 3:
                        print(f"⚠️  WARNING: 超过 {interval * 3} 秒未轮询！可能卡住了")
                else:
                    print("⚠️  WARNING: 没有找到任何轮询事件记录")

                # 检查最后的 API 调用
                last_api_call = db.query(APICallLog).filter(
                    APICallLog.job_id == job.id,
                    APICallLog.method == "GET"
                ).order_by(APICallLog.created_at.desc()).first()

                if last_api_call:
                    print(f"\n最后 API 调用:")
                    print(f"  时间: {last_api_call.created_at}")
                    print(f"  状态码: {last_api_call.status_code}")
                    print(f"  成功: {last_api_call.success}")
                    print(f"  延迟: {last_api_call.latency_ms}ms")
                    if last_api_call.error_text:
                        print(f"  错误: {last_api_call.error_text[:200]}")

                # 检查 watchdog 事件
                watchdog = _latest_event_at(db, int(job.id), {"poll_watchdog", "process_watchdog_released"})
                if watchdog:
                    watchdog = _as_aware_utc(watchdog)
                    print(f"\n最后 watchdog 事件: {watchdog}")

            # 显示最近的事件
            recent_events = db.query(JobEvent).filter(
                JobEvent.job_id == job.id
            ).order_by(JobEvent.created_at.desc()).limit(5).all()

            if recent_events:
                print(f"\n最近 5 个事件:")
                for evt in recent_events:
                    print(f"  [{evt.created_at}] {evt.event_type}: {evt.message[:80]}")

            # 检查是否卡在特定进度
            if job.progress and job.progress >= 35 and job.progress < 100:
                print(f"\n⚠️  任务卡在 {job.progress}% 进度")

                # 检查进度是否长时间未变
                progress_events = db.query(JobEvent).filter(
                    JobEvent.job_id == job.id,
                    JobEvent.event_type.in_({"poll_progress", "poll_heartbeat"})
                ).order_by(JobEvent.created_at.desc()).limit(10).all()

                if progress_events:
                    latest_progress_time = progress_events[0].created_at
                    now = utcnow()
                    elapsed = (now - _as_aware_utc(latest_progress_time)).total_seconds()
                    print(f"  进度最后更新: {latest_progress_time} ({elapsed:.0f} 秒前)")

                    if elapsed > 300:  # 5分钟
                        print(f"  ⚠️  进度超过 5 分钟未更新，可能真正卡住了")

        print(f"\n{'=' * 80}")
        print("\n诊断建议:")
        print("1. 如果任务长时间未轮询，检查 worker 进程是否正常运行")
        print("2. 如果 API 调用失败，检查上游服务是否正常")
        print("3. 如果进度卡在某个值长时间不动，可能是上游任务真正卡住了")
        print("4. 可以尝试重启 worker 进程让任务重新调度")

if __name__ == "__main__":
    diagnose_stuck_jobs()
