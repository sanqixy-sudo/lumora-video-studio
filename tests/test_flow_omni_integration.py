"""Flow Omni contract and real local creation/polling routes; no paid requests."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import Integer, JSON, MetaData
from sqlalchemy.dialects.postgresql import JSONB

from creation_features_support import CreationFeaturesEnvironment
from app.api.admin.routes import _provider_base_url
from app.models.tables import (Base, ProviderKey, Job, JobBatch, JobFile, JobEvent, ReferenceImagePreset,
                              RiskControlRule, JobQuotaReservation, PackageQuotaLedger,
                              QuotaLedger, QuotaWallet, APICallLog)
from app.services import flow_omni, sora_api
from app.services.crypto import encrypt_secret
from app.services.provider_keys import model_id_for_seconds, provider_supports_seconds
from app.services.worker_poller import poll_remote

BASE = "https://api.oairegbox.cc"
IMAGES = [f"https://cdn.example/{i}.png" for i in range(6)]
VIDEO = "https://cdn.example/result.mp4"


class FlowEnvironment(CreationFeaturesEnvironment):
    def __init__(self):
        super().__init__()
        # Keep users/wallets/presets but give generated IDs SQLite-compatible types.
        meta = MetaData()
        for table in Base.metadata.tables.values():
            clone = table.to_metadata(meta)
            for column in clone.columns:
                if column.primary_key and column.name == "id":
                    column.type = Integer()
                if isinstance(column.type, JSONB):
                    column.type = JSON()
        for model in (ProviderKey, JobBatch, Job, JobFile, JobEvent, RiskControlRule,
                      JobQuotaReservation, PackageQuotaLedger, QuotaLedger, APICallLog):
            model.__table__.drop(self.engine, checkfirst=True)
            meta.tables[model.__tablename__].create(self.engine)
        with self.Session() as db:
            db.add(ProviderKey(id=3, name="Flow test", provider_name="flow_omni",
                               api_base_url=BASE, key_masked="***", key_encrypted=encrypt_secret("test-key")))
            db.commit()


class FlowContractTests(unittest.TestCase):
    def client(self, responses):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = httpx.Response(200, json={"task_id": "task_flow", "status": "queued"})
        client.get.side_effect = [httpx.Response(200, json=value) for value in responses]
        return client

    def test_text_and_images_exact_wire_fields_and_orientation(self):
        for size, ratio in [("720x1280", "9:16"), ("1280x720", "16:9")]:
            for images in [[], IMAGES[:1], IMAGES, IMAGES + ["https://cdn.example/seven.png"]]:
                with self.subTest(size=size, count=len(images)):
                    client = self.client([])
                    with patch.object(sora_api.httpx, "Client", return_value=client):
                        data, code, _ = sora_api.create_video(
                            "test-key", "scene", 8, size, provider_name="flow_omni",
                            reference_image_urls=images, api_base_url=BASE + "/v1/videos",
                            model_id="stale-other-model")
                    expected = {"model": flow_omni.MODEL, "prompt": "scene", "resolution": "720p", "aspect_ratio": ratio}
                    if images:
                        expected["images"] = images
                    args, kwargs = client.post.call_args
                    self.assertEqual(args[0], BASE + "/v1/videos")
                    self.assertEqual(kwargs["json"], expected)
                    self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
                    self.assertNotIn("params", kwargs)
                    self.assertEqual((data["id"], code), ("task_flow", 200))

    def test_default_base_aliases_and_fixed_model(self):
        for provider in ["flow_omni", "flow-omni", "oairegbox_omni"]:
            self.assertEqual(sora_api.create_video_endpoint(provider_name=provider), BASE + "/v1/videos")
            self.assertEqual(sora_api.remote_content_url("task_flow", provider_name=provider), BASE + "/v1/videos/task_flow")
            self.assertEqual(_provider_base_url(provider, ""), BASE)
            self.assertTrue(provider_supports_seconds(provider, 8))
            self.assertFalse(provider_supports_seconds(provider, 10))
            key = ProviderKey(provider_name=provider, model_id_8s="stale-model")
            self.assertEqual(model_id_for_seconds(key, 8), flow_omni.MODEL)
            self.assertEqual(model_id_for_seconds(key, 10), "")
        self.assertEqual(_provider_base_url("flow_omni", "https://custom.example/v1"), "https://custom.example")

    def test_reject_edit_invalid_duration_and_size_before_http(self):
        cases = [{"reference_video_url": VIDEO}, {"seconds": 10}, {"size": "1080x1920"}]
        with patch.object(sora_api.httpx, "Client") as http:
            for changes in cases:
                args = dict(api_key="test-key", prompt="scene", seconds=8, size="720x1280", provider_name="flow_omni")
                with self.subTest(changes=changes), self.assertRaises(sora_api.UpstreamError):
                    sora_api.create_video(**{**args, **changes})
            http.assert_not_called()

    def test_poll_same_id_and_all_documented_output_locations(self):
        for output in [{"video_url": VIDEO}, {"data": [{"url": VIDEO}]}, {"metadata": {"url": VIDEO}},
                       {"video_url": VIDEO, "data": [{"url": "https://cdn.example/other.mp4"}]}]:
            client = self.client([{"id": "task_flow", "status": "completed", **output}])
            with patch.object(sora_api.httpx, "Client", return_value=client):
                data, _, _ = sora_api.fetch_video_status("test-key", "task_flow", provider_name="flow_omni")
            self.assertEqual(data["video_url"], VIDEO)
            self.assertEqual(data["id"], "task_flow")
            client.get.assert_called_once_with(BASE + "/v1/videos/task_flow", headers={"Authorization": "Bearer test-key"})
            client.post.assert_not_called()

    def test_nonfinal_response_cannot_promote_reference_or_progress_to_video(self):
        for status in ["queued", "in_progress", "failed", "completed"]:
            data = flow_omni.normalize_response({"task_id": "t", "status": status, "progress": 100,
                "request": {"images": IMAGES}, "url": IMAGES[0], "download_url": IMAGES[0], "result": IMAGES})
            for field in ["video_url", "url", "result", "download_url"]:
                self.assertNotIn(field, data)
            if status in ["queued", "in_progress"]:
                self.assertLess(data["progress"], 100)
        pending = flow_omni.normalize_response({"status": "in_progress", "video_url": VIDEO})
        self.assertNotIn("video_url", pending)

    def test_string_and_object_errors_are_preserved(self):
        for error in ["generation failed", {"message": "generation failed", "code": "blocked"}]:
            data = flow_omni.normalize_response({"status": "failed", "error": error})
            self.assertTrue(sora_api.is_upstream_failure(data))
            self.assertEqual(sora_api.extract_upstream_error(sora_api.raw_task_response(data))[0], "generation failed")

    def test_download_uses_polled_result_and_keeps_existing_download_pipeline(self):
        client = self.client([{"task_id": "task_flow", "status": "completed", "video_url": VIDEO}])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.mp4"
            with patch.object(sora_api.httpx, "Client", return_value=client), patch.object(sora_api, "_download_url", return_value=({}, 200, 1)) as download:
                sora_api.download_video("test-key", "task_flow", path, provider_name="flow_omni", download_proxy="")
            self.assertEqual(download.call_args.args[:2], (VIDEO, path))
            client.post.assert_not_called()
        client = self.client([{"status": "in_progress", "request": {"images": IMAGES}}])
        with patch.object(sora_api.httpx, "Client", return_value=client), patch.object(sora_api, "_download_url") as download:
            with self.assertRaises(sora_api.UpstreamError) as caught:
                sora_api.download_video("test-key", "task_flow", Path("unused.mp4"), provider_name="flow_omni")
            self.assertEqual(caught.exception.status_code, 425)
            download.assert_not_called()


class FlowCreationTests(unittest.TestCase):
    def setUp(self):
        self.env = FlowEnvironment()
        self.addCleanup(self.env.close)
        self.client = TestClient(self.env.app)
        self.login("creator")

    def login(self, name):
        response = self.client.post("/auth/login-browser", json={"username": name, "password": " old-password "})
        self.assertEqual(response.status_code, 200)

    def payload(self, **changes):
        return {"prompt": "scene", "prompts": ["scene one", "scene two"], "product_name": "APP", "region_name": "CN",
                "model_choice": "key:3:8", "seconds": "8", "size": "720x1280", "batch_request_id": str(uuid4()), **changes}

    def test_admin_can_add_flow_without_manual_model_and_creator_can_select(self):
        self.login("admin")
        page = self.client.get("/admin/provider-keys/page")
        self.assertEqual(page.status_code, 200)
        self.assertIn('value="flow_omni"', page.text)
        response = self.client.post("/admin/provider-keys/form", data={"name": "New Flow", "raw_key": "test-key", "provider_name": "flow_omni", "api_base_url": ""}, follow_redirects=False)
        self.assertEqual(response.status_code, 303, response.text)
        with self.env.Session() as db:
            key = db.query(ProviderKey).filter_by(name="New Flow").one()
            self.assertEqual(key.api_base_url, BASE)
            self.assertEqual(model_id_for_seconds(key, 8), flow_omni.MODEL)
        self.login("creator")
        page = self.client.get("/app")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertIn('data-provider="flow_omni"', page.text)
        self.assertIn("约 8 秒", page.text)

    def test_all_create_routes_accept_text_or_six_images_and_reserve_per_job(self):
        count = 0
        for endpoint in ["/app/jobs", "/app/jobs/batch", "/app/jobs/form", "/app/jobs/batch/form"]:
            for images in [[], IMAGES]:
                with self.subTest(endpoint=endpoint, images=len(images)), patch("app.api.user.routes.fetch_image_dimensions", return_value=(512, 512, "image/png", 100)):
                    response = self.client.post(endpoint, data=self.payload(omni_reference_image_urls=images), follow_redirects=False)
                self.assertIn(response.status_code, [200, 303], response.text)
                count += 2 if "/batch" in endpoint else 1
        with self.env.Session() as db:
            jobs = db.query(Job).all()
            self.assertEqual(len(jobs), count)
            self.assertTrue(all(job.model == flow_omni.MODEL and job.seconds == 8 and job.status == "queued" for job in jobs))
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, count)
            self.assertEqual(db.query(JobFile).filter_by(file_type="reference_image_url").count(), count // 2 * 6)

    def test_invalid_create_is_rejected_without_jobs_or_reservations(self):
        cases = [{"omni_reference_video_url": VIDEO}, {"reference_video_url": VIDEO}, {"omni_mode": "video_edit"},
                 {"model_choice": "key:3:10", "seconds": "10"}, {"size": "1080x1920"}]
        for endpoint in ["/app/jobs", "/app/jobs/batch", "/app/jobs/form", "/app/jobs/batch/form"]:
            for case in cases:
                response = self.client.post(endpoint, data=self.payload(**case), follow_redirects=False)
                self.assertEqual(response.status_code, 400, response.text)
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), 0)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, 0)

    def test_seven_images_are_allowed_as_advisory_limit(self):
        images = IMAGES + ["https://cdn.example/seven.png"]
        with patch("app.api.user.routes.fetch_image_dimensions", return_value=(512, 512, "image/png", 100)):
            response = self.client.post("/app/jobs", data=self.payload(omni_reference_image_urls=images))
        self.assertEqual(response.status_code, 200, response.text)
        with self.env.Session() as db:
            self.assertEqual(db.query(JobFile).filter_by(job_id=response.json()["job_id"], file_type="reference_image_url").count(), 7)

    def test_direct_image_must_be_readable_even_if_confirmed(self):
        for endpoint in ["/app/jobs", "/app/jobs/batch", "/app/jobs/form", "/app/jobs/batch/form"]:
            with self.subTest(endpoint=endpoint), patch("app.api.user.routes.fetch_image_dimensions", side_effect=ValueError("图片不可读取")) as fetch:
                response = self.client.post(endpoint, data=self.payload(
                    omni_reference_image_urls=[IMAGES[0]], confirmed_reference_image_urls=[IMAGES[0]]),
                    follow_redirects=False)
                self.assertEqual(response.status_code, 400, response.text)
                fetch.assert_called_once_with(IMAGES[0])
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), 0)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, 0)

    def test_preset_uses_current_image_availability_without_ratio_match(self):
        with self.env.Session() as db:
            preset = db.get(ReferenceImagePreset, 1)
            preset.image_url = IMAGES[0]
            preset.width = 720
            preset.height = 1280
            db.commit()
        with patch("app.api.user.routes.fetch_image_dimensions", side_effect=ValueError("图片不可读取")) as fetch:
            response = self.client.post("/app/jobs", data=self.payload(omni_reference_preset_ids=["1"]))
            self.assertEqual(response.status_code, 400, response.text)
            fetch.assert_called_once_with(IMAGES[0])
        # A square image is valid for a vertical video: no material ratio comparison.
        with patch("app.api.user.routes.fetch_image_dimensions", return_value=(512, 512, "image/png", 100)) as fetch:
            response = self.client.post("/app/jobs", data=self.payload(omni_reference_preset_ids=["1"]))
            self.assertEqual(response.status_code, 200, response.text)
            fetch.assert_called_once_with(IMAGES[0])
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), 1)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, 1)

    def test_batch_replay_keeps_original_jobs(self):
        payload = self.payload()
        first = self.client.post("/app/jobs/batch", data=payload)
        second = self.client.post("/app/jobs/batch", data=payload)
        self.assertEqual((first.status_code, second.status_code), (200, 200))
        self.assertEqual(first.json()["batch_id"], second.json()["batch_id"])
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), 2)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, 2)

    def test_worker_poll_completes_existing_id_into_download_queue(self):
        response = self.client.post("/app/jobs", data=self.payload())
        self.assertEqual(response.status_code, 200, response.text)
        client = FlowContractTests().client([
            {"task_id": "task_flow", "status": "in_progress", "progress": 100, "request": {"images": IMAGES}},
            {"task_id": "task_flow", "status": "completed", "video_url": VIDEO}])
        with self.env.Session() as db, patch.object(sora_api.httpx, "Client", return_value=client):
            job = db.get(Job, response.json()["job_id"])
            job.remote_task_id = "task_flow"
            job.status = "submitted"
            db.commit()
            key = db.get(ProviderKey, 3)
            poll_remote(db, job, key, "test-key")
            self.assertIn(job.status, {"submitted", "polling"})
            poll_remote(db, job, key, "test-key")
            self.assertEqual(job.status, "remote_completed")
            self.assertEqual(job.remote_task_id, "task_flow")
            self.assertEqual(job.progress, 100)
            self.assertTrue(db.query(JobEvent).filter_by(job_id=job.id, event_type="remote_completed").count())
        client.post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
