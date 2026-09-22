"""Regenerate failed attempts without overwriting their accounting or history."""
from pathlib import Path
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.tables import Job, JobBatch, JobFile, ProviderKey, User
from app.services.jobs import add_event, enforce_user_rate_limits, utcnow
from app.services.provider_keys import provider_is_retired, model_id_for_seconds
from app.services.quota_plans import reserve_quota_for_job
from app.services.risk_control import match_risk_message
from app.services.audit import write_audit

REFERENCE_TYPES = ('reference_image', 'reference_image_url', 'reference_video_url')


def latest_attempt_filter():
    return Job.id.not_in(select(Job.retry_of_job_id).where(Job.retry_of_job_id.is_not(None)))


def regeneration_block_reason(db: Session, job: Job) -> str | None:
    if job.status != 'failed':
        return '仅生成失败的任务可以重新生成。'
    if db.query(Job.id).filter(Job.retry_of_job_id == job.id).first():
        return '此任务已有重做记录，请查看最新任务。'
    provider = db.get(ProviderKey, job.provider_key_id) if job.provider_key_id else None
    if not provider or provider.status != 'active' or provider_is_retired(provider.provider_name):
        return '原通道已停用，请在创作页重新选择模型。'
    if model_id_for_seconds(provider, job.seconds) != job.model:
        return '原模型配置已变化，请在创作页重新选择模型。'
    risk = match_risk_message(db, [job.prompt])
    if risk:
        return '提示词未通过当前校验，请修改后重新创建。'
    for ref in db.query(JobFile).filter(JobFile.job_id == job.id, JobFile.file_type.in_(REFERENCE_TYPES)).all():
        if ref.file_type == 'reference_image' and not Path(ref.file_path).is_file():
            return '原参考图文件已不存在，请重新上传素材。'
    return None


def regeneration_info(db: Session, jobs: list[Job]) -> dict[int, dict]:
    info = {}
    for job in jobs:
        reason = regeneration_block_reason(db, job) if job.status == 'failed' else None
        info[job.id] = {'can_regenerate': job.status == 'failed' and reason is None,
                        'regeneration_reason': reason or '', 'retry_of_job_id': job.retry_of_job_id,
                        'can_retry_download': job.status == 'download_failed' and bool(job.remote_task_id)}
    return info


def regenerate_failed_jobs(db: Session, user: User, batch_id: int, job_ids: list[int]) -> list[Job]:
    # Serialize same-account submissions, then lock the batch and source attempts.
    # Unique retry_of_job_id is a second guard against replay or parallel clicks.
    db.query(User).filter(User.id == user.id).with_for_update().one()
    batch = db.query(JobBatch).filter(JobBatch.id == batch_id, JobBatch.user_id == user.id).with_for_update().first()
    if not batch:
        raise LookupError('批次不存在')
    sources = db.query(Job).filter(Job.id.in_(job_ids), Job.batch_id == batch_id, Job.user_id == user.id).order_by(Job.id).with_for_update().all()
    if len(sources) != len(set(job_ids)):
        raise LookupError('任务不存在或不属于当前批次')
    existing = {j.retry_of_job_id:j for j in db.query(Job).filter(Job.retry_of_job_id.in_(job_ids)).all()}
    pending = [j for j in sources if j.id not in existing]
    for job in pending:
        reason = regeneration_block_reason(db, job)
        if reason:
            raise ValueError(f'任务 #{job.id}：{reason}')
    if pending:
        enforce_user_rate_limits(db, user, additional_jobs=len(pending))
    results = []
    for source in sources:
        if source.id in existing:
            results.append(existing[source.id]); continue
        job = Job(user_id=user.id, batch_id=batch.id, batch_index=source.batch_index,
                  retry_of_job_id=source.id, provider_key_id=source.provider_key_id, request_id=uuid4(),
                  product_name=source.product_name, region_name=source.region_name, prompt=source.prompt,
                  seconds=source.seconds, size=source.size, model=source.model,
                  status='queued', progress=0, queued_at=utcnow(), submit_attempts=0, download_attempts=0)
        db.add(job); db.flush()
        refs = db.query(JobFile).filter(JobFile.job_id == source.id, JobFile.file_type.in_(REFERENCE_TYPES)).order_by(JobFile.id).all()
        for ref in refs:
            db.add(JobFile(job_id=job.id, **{name:getattr(ref,name) for name in
                ('file_type','file_path','file_name','file_size','mime_type','duration_seconds','width','height','playable')}))
        reserve_quota_for_job(db, job)
        add_event(db, source.id, 'info', 'regenerated', f'已创建重做任务 #{job.id}，原失败记录保留。', {'new_job_id':job.id})
        add_event(db, job.id, 'info', 'queued', f'由失败任务 #{source.id} 重新生成，已加入原批次队列。', {'source_job_id':source.id})
        write_audit(db, user.id, 'regenerate_failed_job', 'job', job.id, {'source_job_id':source.id,'batch_id':batch.id})
        results.append(job)
    db.commit()
    return results
