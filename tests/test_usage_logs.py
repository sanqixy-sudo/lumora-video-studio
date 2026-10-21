import tempfile
import unittest
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.usage_logs.routes import router
from app.deps import get_current_user, get_db
from app.main import app as main_app
from app.models.tables import Base, Job, JobCost, JobEvent, JobFile, User


class UsageLogsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        now = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
        video_path = Path(self.temp.name) / "result.mp4"
        video_path.write_bytes(b"test video")
        with self.Session() as db:
            db.add_all([
                User(id=1, username="alice", password_hash="x", role="user", status="active"),
                User(id=2, username="bob", password_hash="x", role="user", status="active", hidden_from_subadmin_reports=True),
                User(id=3, username="admin", password_hash="x", role="admin", status="active"),
                User(id=4, username="reporter", password_hash="x", role="sub_admin", status="active"),
            ])
            db.add(Job(id=101, user_id=1, prompt="<script>secret</script> camera move", model="video-model", seconds=15, status="completed", created_at=now, completed_at=now))
            db.add_all([
                Job(id=104, user_id=1, prompt="generating", model="video-model", seconds=15, status="polling", created_at=now),
                Job(id=105, user_id=1, prompt="completed upstream", model="video-model", seconds=15, status="download_failed", created_at=now),
                Job(id=106, user_id=1, prompt="failed upstream", model="video-model", seconds=15, status="failed", created_at=now),
                Job(id=107, user_id=1, prompt="local failure after generation", model="video-model", seconds=15, status="failed", created_at=now),
            ])
            db.add(JobEvent(id=1, job_id=107, event_type="remote_completed", message="upstream finished", created_at=now))
            db.add(JobFile(id=1, job_id=101, file_type="output_video", file_path=str(video_path), file_name="result.mp4", mime_type="video/mp4"))
            db.add_all([
                JobCost(id=1, source_job_id=101, source_user_id=1, username="alice", provider_key_id=1,
                        api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id="task-101",
                        model="video-model", seconds=15, resolution="720p", state="settled",
                        amount=Decimal("3.900000"), currency="USD", usage_date=date(2026, 10, 20),
                        source_logs=[{"request_id": "request-101"}], created_at=now),
                JobCost(id=2, source_job_id=102, source_user_id=2, username="bob", provider_key_id=1,
                        api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id="task-102",
                        model="video-model", seconds=15, state="settled", amount=Decimal("2.000000"),
                        currency="USD", usage_date=date(2026, 10, 20), created_at=now),
                JobCost(id=3, source_job_id=103, source_user_id=1, username="alice", provider_key_id=1,
                        api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id="task-103",
                        model="video-model", seconds=15, state="pending", created_at=now),
                *[
                    JobCost(id=job_id, source_job_id=job_id, source_user_id=1, username="alice", provider_key_id=1,
                            api_base_url="https://example.test", provider_name="oaire_grok", remote_task_id=f"task-{job_id}",
                            model="video-model", seconds=15, state="pending", created_at=now)
                    for job_id in (104, 105, 106, 107)
                ],
            ])
            db.commit()
        self.role = "user"
        self.user_id = 1
        app = FastAPI()
        app.state.templates = main_app.state.templates
        app.include_router(router)

        def database():
            with self.Session() as db:
                yield db

        app.dependency_overrides[get_db] = database
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=self.user_id, role=self.role, username="test")
        self.client = TestClient(app)

    def page(self, **params):
        return self.client.get("/usage-logs/page", params={"start": "2026-10-20", "end": "2026-10-20", **params})

    def test_user_scope_ignores_user_filter_and_rejects_other_detail(self):
        response = self.page(user="bob")
        self.assertEqual(response.status_code, 200)
        self.assertIn("#101", response.text)
        self.assertIn("#103", response.text)
        self.assertNotIn("#102", response.text)
        self.assertNotIn('name="user"', response.text)
        self.assertIn("$3.90", response.text)
        self.assertEqual(self.client.get("/usage-logs/102/detail").status_code, 404)

    def test_admin_all_subadmin_respects_hidden_flag_and_filter(self):
        self.role = "admin"
        response = self.page()
        self.assertIn("#102", response.text)
        self.assertIn("$5.90", response.text)
        self.assertIn('name="user"', response.text)
        filtered = self.page(user="bob")
        self.assertIn("#102", filtered.text)
        self.assertNotIn("#101", filtered.text)
        self.role = "sub_admin"
        response = self.page()
        self.assertNotIn("#102", response.text)
        self.assertEqual(self.client.get("/usage-logs/102/detail").status_code, 404)

    def test_detail_escapes_prompt_and_embeds_authorized_video(self):
        response = self.client.get("/usage-logs/101/detail")
        self.assertEqual(response.status_code, 200)
        self.assertIn("&lt;script&gt;secret&lt;/script&gt;", response.text)
        self.assertNotIn("<script>secret</script>", response.text)
        self.assertIn("request-101", response.text)
        self.assertIn('/app/files/1/stream', response.text)
        self.assertIn("$3.90", response.text)

    def test_quick_ranges_and_task_request_search(self):
        response = self.page(task="request-101")
        self.assertEqual(response.status_code, 200)
        self.assertIn("#101", response.text)
        self.assertNotIn("#103", response.text)
        self.assertIn("&lt;script&gt;secret&lt;/script&gt; camera move", response.text)
        self.assertIn("今天", response.text)
        self.assertIn("近 7 天", response.text)
        self.assertIn("本月", response.text)
        self.assertIn("每日成本", response.text)
        self.assertIn("2026-10-20", response.text)
        self.assertIn("#101", self.page(task="101").text)

    def test_dates_and_invalid_range(self):
        self.assertNotIn("#101", self.page(start="2026-10-19", end="2026-10-19").text)
        self.assertEqual(self.page(start="2026-10-21", end="2026-10-20").status_code, 422)
        self.assertIn("#101", self.page(start="2026-10-20T16:00", end="2026-10-20T16:00").text)
        self.assertNotIn("#101", self.page(start="2026-10-20T16:01", end="2026-10-20T16:59").text)

    def test_pending_states_follow_confirmed_generation_and_exclude_failures(self):
        response = self.page()
        self.assertIn("生成中", response.text)
        self.assertIn("成功待核对", response.text)
        self.assertIn("失败待排除", response.text)
        self.assertIn("#107", response.text)
        self.assertIn("$3.90", response.text)
        self.assertIn("<span>成功待核对</span><strong>2", response.text)
        self.assertIn("成功待核对", self.client.get("/usage-logs/107/detail").text)
        self.assertIn("失败待排除", self.client.get("/usage-logs/106/detail").text)

    def test_only_admin_can_queue_successful_pending_recheck(self):
        url = "/usage-logs/105/recheck"
        headers = {"origin": "http://testserver"}
        self.assertEqual(self.client.post(url, headers=headers).status_code, 403)
        self.role = "sub_admin"
        self.assertEqual(self.client.post(url, headers=headers).status_code, 403)
        self.role = "admin"
        self.assertEqual(self.client.post("/usage-logs/106/recheck", headers=headers).status_code, 409)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(self.client.post(url, headers=headers).status_code, 200)
        with self.Session() as db:
            self.assertIsNotNone(db.query(JobCost).filter(JobCost.source_job_id == 105).one().next_check_at)


if __name__ == "__main__":
    unittest.main()
