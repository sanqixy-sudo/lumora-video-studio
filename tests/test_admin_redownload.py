import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import BigInteger, Integer, JSON, MetaData, create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.admin.routes import _download_failure_rows, router
from app.deps import get_current_user, get_db
from app.models.tables import APICallLog, Job, JobEvent, JobFile, User


class AdminRedownloadTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        metadata = MetaData()
        for table in Job.metadata.tables.values():
            table.to_metadata(metadata)
        for model in [Job, JobFile, JobEvent, APICallLog, User]:
            table = metadata.tables[model.__tablename__]
            for column in table.columns:
                if isinstance(column.type, JSONB):
                    column.type = JSON()
                if column.primary_key and isinstance(column.type, BigInteger):
                    column.type = Integer()
            table.create(self.engine)
        self.db = Session(self.engine)
        self.user = User(id=9, role='admin')
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: self.db
        app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(app)
        self.kick = patch('app.services.worker_runtime.schedule_job_now', return_value=True).start()
        self.addCleanup(patch.stopall)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def job(self, status='download_failed', remote='existing-remote'):
        job = Job(user_id=7, batch_id=8, prompt='original prompt', status=status,
                  remote_task_id=remote, download_attempts=10, error_text='network error',
                  model='omni-fast', progress=100)
        self.db.add(job)
        self.db.commit()
        return job

    def post(self, job, origin='http://testserver'):
        return self.client.post(f'/admin/jobs/{job.id}/redownload', headers={'Origin': origin})

    def test_failed_and_waiting_retry_original_result_without_creating_jobs(self):
        for status in ['download_failed', 'download_waiting']:
            with self.subTest(status=status):
                job = self.job(status)
                before = self.db.query(Job).count()
                response = self.post(job)
                self.assertEqual(response.status_code, 200, response.text)
                self.db.refresh(job)
                self.assertEqual(job.status, 'remote_completed')
                self.assertEqual(job.download_attempts, 0)
                self.assertIsNone(job.error_text)
                self.assertEqual((job.remote_task_id, job.user_id, job.batch_id, job.prompt, job.model),
                                 ('existing-remote', 7, 8, 'original prompt', 'omni-fast'))
                self.assertEqual(self.db.query(Job).count(), before)
                self.kick.assert_called_with(job.id)
                self.assertEqual(self.db.query(JobEvent).filter_by(job_id=job.id, event_type='redownload_requested').count(), 1)

    def test_double_click_and_active_download_do_not_reset_attempts_or_kick_again(self):
        job = self.job()
        self.assertEqual(self.post(job).status_code, 200)
        self.assertTrue(self.post(job).json()['already_pending'])
        self.assertEqual(self.kick.call_count, 1)
        job.status = 'downloading'
        job.download_attempts = 3
        self.db.commit()
        self.assertTrue(self.post(job).json()['already_pending'])
        self.db.refresh(job)
        self.assertEqual((job.status, job.download_attempts), ('downloading', 3))
        self.assertEqual(self.kick.call_count, 1)

    def test_invalid_state_or_missing_remote_does_not_mutate(self):
        for status, remote in [('failed', 'remote'), ('polling', 'remote'), ('completed', None), ('download_failed', '')]:
            job = self.job(status, remote)
            self.assertEqual(self.post(job).status_code, 400)
            self.db.refresh(job)
            self.assertEqual((job.status, job.download_attempts, job.error_text), (status, 10, 'network error'))
        self.kick.assert_not_called()

    def test_admin_only_and_same_origin(self):
        job = self.job()
        for role in ['user', 'sub_admin']:
            self.user.role = role
            self.assertEqual(self.post(job).status_code, 403)
        self.user.role = 'admin'
        self.assertEqual(self.post(job, 'https://untrusted.example').status_code, 403)
        self.kick.assert_not_called()

    def test_exception_page_includes_waiting_but_not_active_or_completed(self):
        jobs = [self.job(status) for status in ['download_failed', 'download_waiting', 'downloading', 'completed', 'failed']]
        with patch('app.api.admin.routes.queue_text', return_value='test'), patch('app.api.admin.routes.attach_display_names'):
            paged, rows = _download_failure_rows(self.db, 1, 20)
        self.assertEqual(paged['total_items'], 2)
        self.assertEqual({row['job'].id for row in rows}, {jobs[0].id, jobs[1].id})

    def test_button_only_shows_for_admin_and_retryable_results(self):
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'app/templates'), autoescape=True)
        template = env.get_template('admin/partials/redownload_button.html')
        job = self.job('download_waiting')
        self.assertIn('立即重试下载', template.render(job=job, can_manage=True))
        self.assertNotIn('<button', template.render(job=job, can_manage=False))
        for status in ['downloading', 'remote_completed', 'completed', 'failed']:
            job.status = status
            self.assertNotIn('<button', template.render(job=job, can_manage=True))
        job.status = 'download_failed'
        self.assertIn('重新下载', template.render(job=job, can_manage=True))
        job.remote_task_id = None
        self.assertNotIn('<button', template.render(job=job, can_manage=True))


if __name__ == '__main__':
    unittest.main()
