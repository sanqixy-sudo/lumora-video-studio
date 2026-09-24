"""OAIREGBOX Omni Fast contract and local creation routes; no paid calls."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

from test_flow_omni_integration import FlowEnvironment
from app.api.admin.routes import _provider_base_url
from app.models.tables import ProviderKey, Job, JobFile, QuotaWallet
from app.services import oaire_omni, sora_api
from app.services.crypto import encrypt_secret
from app.services.provider_keys import model_id_for_seconds, provider_supports_seconds

BASE = "https://api.oairegbox.cc"
IMAGES = [f"https://cdn.example/{i}.png" for i in range(6)]
VIDEO = "https://cdn.example/result.mp4"


class OaireOmniContractTests(unittest.TestCase):
    def client(self, status=None):
        client = MagicMock()
        client.__enter__.return_value = client
        client.post.return_value = httpx.Response(200, json={"task_id": "task_omni", "status": "queued"})
        client.get.return_value = httpx.Response(200, json=status or {"task_id": "task_omni", "status": "completed", "video_url": VIDEO})
        return client

    def test_text_and_one_to_five_images_wire_contract(self):
        for size, ratio in [("720x1280", "9:16"), ("1280x720", "16:9")]:
            for images in [[], IMAGES[:1], IMAGES[:5]]:
                for model in oaire_omni.MODELS:
                    with self.subTest(size=size, count=len(images), model=model):
                        client = self.client()
                        with patch.object(sora_api.httpx, "Client", return_value=client):
                            data, code, _ = sora_api.create_video(
                                "test-key", "scene", 10, size, provider_name="oaire_omni",
                                reference_image_urls=images, model_id=model)
                        expected = {"model": model, "prompt": "scene", "aspect_ratio": ratio}
                        if images:
                            expected["images"] = images
                        args, kwargs = client.post.call_args
                        self.assertEqual(args[0], BASE + "/v1/videos")
                        self.assertEqual(kwargs["json"], expected)
                        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test-key")
                        self.assertEqual((data["id"], code), ("task_omni", 200))

    def test_bad_mode_count_duration_size_and_model_fail_before_http(self):
        cases = [{"reference_video_url": VIDEO}, {"reference_image_urls": IMAGES},
                 {"seconds": 8}, {"size": "1080x1920"}, {"model_id": "omni-fast-v2v"}]
        with patch.object(sora_api.httpx, "Client") as client:
            for changes in cases:
                args = dict(api_key="test-key", prompt="scene", seconds=10, size="720x1280", provider_name="oaire_omni")
                with self.subTest(changes=changes), self.assertRaises(sora_api.UpstreamError):
                    sora_api.create_video(**{**args, **changes})
            client.assert_not_called()

    def test_poll_and_download_use_same_task_and_documented_url(self):
        for output in [{"video_url": VIDEO}, {"data": [{"url": VIDEO}]}]:
            client = self.client({"task_id": "task_omni", "status": "completed", **output})
            with patch.object(sora_api.httpx, "Client", return_value=client):
                data, _, _ = sora_api.fetch_video_status("test-key", "task_omni", provider_name="oaire_omni")
            self.assertEqual(data["video_url"], VIDEO)
            client.get.assert_called_once_with(BASE + "/v1/videos/task_omni", headers={"Authorization": "Bearer test-key"})
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "result.mp4"
            client = self.client()
            with patch.object(sora_api.httpx, "Client", return_value=client), patch.object(sora_api, "_download_url", return_value=({}, 200, 1)) as download:
                sora_api.download_video("test-key", "task_omni", path, provider_name="oaire_omni", download_proxy="")
            self.assertEqual(download.call_args.args[:2], (VIDEO, path))
        self.assertEqual(sora_api.remote_content_url("task_omni", provider_name="oaire_omni"), BASE + "/v1/videos/task_omni")


class OaireOmniCreationTests(unittest.TestCase):
    def setUp(self):
        self.env = FlowEnvironment()
        self.addCleanup(self.env.close)
        with self.env.Session() as db:
            db.add(ProviderKey(id=4, name="Omni test", provider_name="oaire_omni",
                               api_base_url=BASE, key_masked="***", key_encrypted=encrypt_secret("test-key")))
            db.commit()
        self.client = TestClient(self.env.app)
        self.login("creator")

    def login(self, name):
        response = self.client.post("/auth/login-browser", json={"username": name, "password": " old-password "})
        self.assertEqual(response.status_code, 200)

    def payload(self, **changes):
        return {"prompt": "scene", "prompts": ["scene one", "scene two"], "product_name": "APP",
                "region_name": "CN", "model_choice": "key:4:10", "seconds": "10", "size": "720x1280",
                "batch_request_id": str(uuid4()), **changes}

    def test_channel_names_default_and_no_water_model(self):
        self.assertEqual(_provider_base_url("oaire_omni", ""), BASE)
        self.assertTrue(provider_supports_seconds("oaire_omni", 10))
        self.assertFalse(provider_supports_seconds("oaire_omni", 8))
        with self.env.Session() as db:
            key = db.get(ProviderKey, 4)
            self.assertEqual(model_id_for_seconds(key, 10), "omni-fast")
            key.model_id_10s = "omni-fast-no-water"
            db.commit()
            self.assertEqual(model_id_for_seconds(key, 10), "omni-fast-no-water")
        self.login("admin")
        page = self.client.get("/admin/provider-keys/page")
        self.assertEqual(page.status_code, 200)
        self.assertIn('value="oaire_omni"', page.text)
        self.assertIn("oaire-flow omni", page.text)
        self.assertIn("oaire omni", page.text)
        self.login("creator")
        page = self.client.get("/app")
        self.assertIn('data-provider="oaire_omni"', page.text)
        self.assertIn("omni-fast-no-water", page.text)

    def test_all_creation_routes_accept_text_and_five_square_images(self):
        count = 0
        for endpoint in ["/app/jobs", "/app/jobs/batch", "/app/jobs/form", "/app/jobs/batch/form"]:
            for images in [[], IMAGES[:5]]:
                with self.subTest(endpoint=endpoint, count=len(images)), patch("app.api.user.routes.fetch_image_dimensions", return_value=(512, 512, "image/png", 100)):
                    response = self.client.post(endpoint, data=self.payload(omni_reference_image_urls=images), follow_redirects=False)
                self.assertIn(response.status_code, [200, 303], response.text)
                count += 2 if "/batch" in endpoint else 1
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), count)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, count)
            self.assertEqual(db.query(JobFile).filter_by(file_type="reference_image_url").count(), count // 2 * 5)

    def test_six_images_and_unreadable_confirmed_url_create_no_job(self):
        for endpoint in ["/app/jobs", "/app/jobs/batch", "/app/jobs/form", "/app/jobs/batch/form"]:
            with self.subTest(endpoint=endpoint):
                response = self.client.post(endpoint, data=self.payload(omni_reference_image_urls=IMAGES), follow_redirects=False)
                self.assertEqual(response.status_code, 400, response.text)
                with patch("app.api.user.routes.fetch_image_dimensions", side_effect=ValueError("图片不可读取")):
                    response = self.client.post(endpoint, data=self.payload(
                        omni_reference_image_urls=[IMAGES[0]], confirmed_reference_image_urls=[IMAGES[0]]), follow_redirects=False)
                    self.assertEqual(response.status_code, 400, response.text)
        with self.env.Session() as db:
            self.assertEqual(db.query(Job).count(), 0)
            self.assertEqual(db.query(QuotaWallet).filter_by(user_id=1).one().reserved_quota, 0)


if __name__ == "__main__":
    unittest.main()
