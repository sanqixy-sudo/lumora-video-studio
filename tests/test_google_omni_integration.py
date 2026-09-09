import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.user.routes import _model_options, _resolve_job_reference_materials, _resolve_reference_video_url
from app.db import Base
from app.models import tables as _tables  # noqa: F401
from app.models.tables import JobFile, ProviderKey
from app.services.jobs import (
    create_reference_url_record,
    create_reference_video_url_record,
    get_reference_urls,
    get_reference_video_url,
)
from app.services.provider_keys import model_id_for_seconds, normalize_provider_name, provider_supports_seconds
from app.services.sora_api import (
    _normalize_task_response,
    create_video,
    create_video_endpoint,
    extract_upstream_error,
    fetch_video_status,
    is_upstream_failure,
    normalize_api_base_url,
    remote_content_url,
)


class GoogleOmniAdapterTests(unittest.TestCase):
    def _client(self):
        client = MagicMock()
        client.__enter__.return_value = client
        client.__exit__.return_value = False
        return client

    def test_create_uses_exact_endpoint_auth_query_and_payload(self):
        client = self._client()
        client.post.return_value = httpx.Response(
            200,
            json={"code": 200, "msg": "成功", "data": {"id": "video_123"}},
            request=httpx.Request("POST", "https://api.wuyinkeji.com/api/async/video_google_omni"),
        )
        with patch("app.services.sora_api.httpx.Client", return_value=client):
            data, status_code, _latency_ms = create_video(
                "secret-key",
                "prompt",
                10,
                "1280x720",
                reference_image_url="https://cdn.example/image.png",
                reference_video_url="https://cdn.example/video.mp4",
                api_base_url="https://api.wuyinkeji.com/api/async/video_google_omni",
                provider_name="wuyin_omni",
                idempotency_key="local-request-id",
            )

        self.assertEqual(data["task_id"], "video_123")
        self.assertEqual(status_code, 200)
        args, kwargs = client.post.call_args
        self.assertEqual(args[0], "https://api.wuyinkeji.com/api/async/video_google_omni")
        self.assertEqual(kwargs["headers"], {"Authorization": "secret-key", "Content-Type": "application/json"})
        self.assertEqual(kwargs["params"], {"key": "secret-key"})
        self.assertEqual(
            kwargs["json"],
            {
                "prompt": "prompt",
                "duration": "10",
                "size": "1280x720",
                "images": "https://cdn.example/image.png",
                "video": "https://cdn.example/video.mp4",
            },
        )

    def test_status_uses_detail_endpoint_and_exact_query(self):
        client = self._client()
        client.get.return_value = httpx.Response(
            200,
            json={"code": 200, "data": {"task_id": "video_123", "status": 2, "result": ["https://cdn.example/result.mp4"]}},
            request=httpx.Request("GET", "https://api.wuyinkeji.com/api/async/detail"),
        )
        with patch("app.services.sora_api.httpx.Client", return_value=client):
            data, status_code, _latency_ms = fetch_video_status(
                "secret-key", "video_123", "https://api.wuyinkeji.com/api/async/detail", "wuyin_omni"
            )

        self.assertEqual(status_code, 200)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["progress"], 100)
        self.assertEqual(data["video_url"], "https://cdn.example/result.mp4")
        args, kwargs = client.get.call_args
        self.assertEqual(args[0], "https://api.wuyinkeji.com/api/async/detail")
        self.assertEqual(kwargs["headers"], {"Authorization": "secret-key"})
        self.assertEqual(kwargs["params"], {"key": "secret-key", "id": "video_123"})

    def test_numeric_status_mapping_and_result_safety(self):
        image_url = "https://cdn.example/reference.png"
        for raw_status, expected in ((0, "processing"), (1, "processing"), (2, "completed"), (3, "failed")):
            with self.subTest(raw_status=raw_status):
                payload = {
                    "code": 200,
                    "data": {
                        "task_id": "video_123",
                        "status": raw_status,
                        "request": {"images": image_url},
                        "result": ["https://cdn.example/result.mp4"] if raw_status == 2 else None,
                        "message": "generation failed" if raw_status == 3 else "",
                    },
                }
                normalized = _normalize_task_response(payload)
                self.assertEqual(normalized["status"], expected)
                if raw_status == 2:
                    self.assertEqual(normalized["video_url"], "https://cdn.example/result.mp4")
                else:
                    self.assertNotIn("video_url", normalized)
        failed = _normalize_task_response(payload)
        self.assertTrue(is_upstream_failure(failed))
        self.assertEqual(extract_upstream_error(failed["_raw"])[0], "generation failed")

    def test_endpoint_normalization(self):
        expected_base = "https://api.wuyinkeji.com"
        self.assertEqual(normalize_api_base_url("https://api.wuyinkeji.com/api/async/detail?id=x"), expected_base)
        self.assertEqual(create_video_endpoint(expected_base, "wuyin-omni"), f"{expected_base}/api/async/video_google_omni")
        self.assertEqual(remote_content_url("video_123", expected_base, "wuyin_omni"), f"{expected_base}/api/async/detail")

    def test_duration_and_fixed_model(self):
        key = ProviderKey(provider_name="video_google_omni")
        self.assertEqual(normalize_provider_name(key.provider_name), "wuyin_omni")
        self.assertTrue(provider_supports_seconds(key.provider_name, 10))
        self.assertFalse(provider_supports_seconds(key.provider_name, 8))
        self.assertEqual(model_id_for_seconds(key, 10), "wuyin-omni")
        self.assertEqual(model_id_for_seconds(key, 8), "")

    def test_non_ten_second_create_is_rejected(self):
        with self.assertRaisesRegex(Exception, "only supports 10-second"):
            create_video("secret", "prompt", 8, "1280x720", provider_name="wuyin_omni")

    def test_existing_veo_omni_provider_remains_selectable(self):
        key = ProviderKey(id=6, name="omni", provider_name="veo_omni", model_id_10s="veo-omni-flash-1080p")
        self.assertEqual(normalize_provider_name(key.provider_name), "veo_omni")
        self.assertTrue(provider_supports_seconds(key.provider_name, 10))
        self.assertFalse(provider_supports_seconds(key.provider_name, 8))
        self.assertEqual(model_id_for_seconds(key, 10), "veo-omni-flash-1080p")
        self.assertEqual(
            create_video_endpoint("https://nb.373766.xyz", "veo_omni"),
            "https://nb.373766.xyz/v1/videos",
        )
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [key]
        options = _model_options(db)
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["value"], "key:6:10")
        self.assertEqual(options[0]["provider_name"], "veo_omni")
        self.assertEqual(options[0]["model_id"], "veo-omni-flash-1080p")

    def test_veo_and_wuyin_omni_are_separate_model_options(self):
        veo_key = ProviderKey(id=6, name="old omni", provider_name="veo_omni", model_id_10s="veo-omni-flash-1080p")
        wuyin_key = ProviderKey(id=8, name="wuyin", provider_name="wuyin_omni")
        db = MagicMock()
        db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [veo_key, wuyin_key]

        options = _model_options(db)

        self.assertEqual([item["value"] for item in options], ["key:6:10", "key:8:10"])
        self.assertEqual([item["provider_name"] for item in options], ["veo_omni", "wuyin_omni"])
        self.assertEqual([item["model_id"] for item in options], ["veo-omni-flash-1080p", "wuyin-omni"])
        self.assertEqual(create_video_endpoint("https://nb.373766.xyz", "veo_omni"), "https://nb.373766.xyz/v1/videos")
        self.assertEqual(
            create_video_endpoint("https://api.wuyinkeji.com", "wuyin_omni"),
            "https://api.wuyinkeji.com/api/async/video_google_omni",
        )

    def test_veo_multi_image_uses_documented_array_field_and_model(self):
        client = self._client()
        client.post.return_value = httpx.Response(
            200,
            json={"id": "veo_multi_1", "status": "queued"},
            request=httpx.Request("POST", "https://nb.373766.xyz/v1/videos"),
        )
        images = ["https://cdn.example/one.jpg", "https://cdn.example/two.jpg"]
        with patch("app.services.sora_api.httpx.Client", return_value=client):
            create_video(
                "old-secret",
                "prompt",
                10,
                "1280x720",
                api_base_url="https://nb.373766.xyz",
                model_id="veo-omni-flash-1080p",
                provider_name="veo_omni",
                reference_image_urls=images,
            )
        _args, kwargs = client.post.call_args
        self.assertEqual(
            kwargs["json"],
            {
                "model": "veo-omni-flash",
                "prompt": "prompt",
                "duration": 10,
                "aspect_ratio": "16:9",
                "Ingredients_images": images,
            },
        )
        self.assertNotIn("images", kwargs["json"])

    def test_veo_video_edit_uses_documented_video_model_and_fields(self):
        client = self._client()
        client.post.return_value = httpx.Response(
            200,
            json={"id": "veo_edit_1", "status": "queued"},
            request=httpx.Request("POST", "https://nb.373766.xyz/v1/videos"),
        )
        with patch("app.services.sora_api.httpx.Client", return_value=client):
            create_video(
                "old-secret",
                "prompt",
                10,
                "720x1280",
                api_base_url="https://nb.373766.xyz",
                provider_name="veo_omni",
                reference_image_urls=["https://cdn.example/product.jpg"],
                reference_video_url="https://cdn.example/reference.mp4",
            )
        _args, kwargs = client.post.call_args
        self.assertEqual(kwargs["json"]["model"], "veo-omni-flash-video-edit")
        self.assertEqual(kwargs["json"]["video_url"], "https://cdn.example/reference.mp4")
        self.assertEqual(kwargs["json"]["Ingredients_images"], ["https://cdn.example/product.jpg"])
        self.assertEqual(kwargs["json"]["aspect_ratio"], "9:16")

    def test_provider_image_limits_are_separate(self):
        with self.assertRaisesRegex(Exception, "at most one"):
            create_video(
                "secret",
                "prompt",
                10,
                "1280x720",
                provider_name="wuyin_omni",
                reference_image_urls=["https://cdn.example/1.jpg", "https://cdn.example/2.jpg"],
            )
        with self.assertRaisesRegex(Exception, "at most six"):
            create_video(
                "secret",
                "prompt",
                10,
                "1280x720",
                provider_name="veo_omni",
                reference_image_urls=[f"https://cdn.example/{index}.jpg" for index in range(7)],
            )


class GoogleOmniReferenceVideoTests(unittest.TestCase):
    def test_url_validation_is_provider_scoped(self):
        url = "https://cdn.example/reference.mp4"
        self.assertEqual(_resolve_reference_video_url(url, "wuyin_omni"), url)
        self.assertEqual(_resolve_reference_video_url(url, "veo_omni"), url)
        self.assertIsNone(_resolve_reference_video_url("", "wuyin_omni"))
        for provider, value in (("sora_api", url), ("wuyin_omni", "file:///tmp/video.mp4"), ("wuyin_omni", "https://user:pass@example.com/v.mp4")):
            with self.subTest(provider=provider, value=value):
                with self.assertRaises(HTTPException):
                    _resolve_reference_video_url(value, provider)

    def test_reference_video_url_storage(self):
        engine = create_engine("sqlite:///:memory:")
        JobFile.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            row = create_reference_video_url_record(db, 987, "https://cdn.example/reference.mp4")
            row.id = 1  # PostgreSQL BIGSERIAL is assigned by production; SQLite needs it explicitly.
            db.commit()
            self.assertEqual(get_reference_video_url(db, 987), "https://cdn.example/reference.mp4")

    def test_multiple_reference_image_urls_are_stored_in_order(self):
        engine = create_engine("sqlite:///:memory:")
        JobFile.__table__.create(engine)
        Session = sessionmaker(bind=engine)
        with Session() as db:
            first = create_reference_url_record(db, 321, "https://cdn.example/first.jpg")
            second = create_reference_url_record(db, 321, "https://cdn.example/second.jpg")
            first.id = 1
            second.id = 2
            db.commit()
            self.assertEqual(
                get_reference_urls(db, 321),
                ["https://cdn.example/first.jpg", "https://cdn.example/second.jpg"],
            )

    def test_material_resolver_enforces_mode_and_channel_limits(self):
        fake_user = MagicMock(id=10)
        with patch("app.api.user.routes._resolve_reference_image_url") as resolve_image:
            resolve_image.side_effect = lambda _db, _user, _preset, url, _size, _confirmed=None, *, require_matching_size=True: (url, "image", 1280, 720)
            images, video = _resolve_job_reference_materials(
                MagicMock(),
                fake_user,
                "veo_omni",
                "1280x720",
                omni_mode="multi_image",
                omni_reference_image_urls=["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"],
            )
            self.assertEqual([item[0] for item in images], ["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"])
            self.assertIsNone(video)
            with self.assertRaises(HTTPException):
                _resolve_job_reference_materials(
                    MagicMock(), fake_user, "wuyin_omni", "1280x720",
                    omni_reference_image_urls=["https://cdn.example/a.jpg", "https://cdn.example/b.jpg"],
                )

    def test_dashboard_contains_shared_omni_material_card(self):
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        from types import SimpleNamespace
        env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "app" / "templates"), autoescape=select_autoescape(["html"]))
        env.globals.update(role_label=lambda value: value, status_label=lambda value: value)
        env.filters["dt"] = str
        preset = SimpleNamespace(id=1, name="Sample", image_url="https://example.test/image.png", width=720, height=1280, aspect_ratio="9:16", owner_user_id=None)
        template = env.get_template("app/dashboard.html").render(
            request=SimpleNamespace(url=SimpleNamespace(path="/app")),
            current_user=SimpleNamespace(id=2, username="sample", role="user"),
            quota_stats=SimpleNamespace(total_available=10, total_reserved=0),
            reference_presets=[preset], model_options=[], jobs=[], new_request_id="sample-request",
        )
        self.assertIn('id="omni-material-card"', template)
        self.assertIn('name="omni_reference_preset_ids"', template)
        self.assertIn('name="omni_reference_image_urls"', template)
        self.assertIn('name="omni_reference_video_url"', template)


if __name__ == "__main__":
    unittest.main()
