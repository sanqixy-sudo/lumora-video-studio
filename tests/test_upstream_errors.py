import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from sqlalchemy import create_engine
from sqlalchemy.dialects import sqlite

from app.db import Base
from app.models import tables as _tables  # noqa: F401
from app.services.sora_api import (
    UpstreamError,
    _normalize_task_response,
    _request_json_or_raise,
    download_video,
    extract_upstream_error,
    is_upstream_failure,
)


class UpstreamErrorExtractionTests(unittest.TestCase):
    def test_error_message_priority_and_code(self):
        payload = {
            "error": {"message": "top error", "code": "E_TOP"},
            "data": {"error": {"message": "nested error", "code": "E_NESTED"}},
            "detail": {"message": "detail error"},
            "message": "generic message",
            "status": "failed",
        }
        self.assertEqual(extract_upstream_error(payload), ("top error", "E_TOP"))

    def test_data_error_message_and_code(self):
        payload = {"data": {"error": {"message": "nested error", "code": 402}}, "status": "failed"}
        self.assertEqual(extract_upstream_error(payload), ("nested error", "402"))

    def test_each_message_field(self):
        cases = [
            ({"detail": {"message": "detail message"}}, "detail message"),
            ({"fail_reason": "fail reason"}, "fail reason"),
            ({"failure_reason": "failure reason"}, "failure reason"),
            ({"reason": "reason text"}, "reason text"),
            ({"message": "message text"}, "message text"),
            ({"detail": "detail string"}, "detail string"),
        ]
        for payload, expected in cases:
            with self.subTest(payload=payload):
                self.assertEqual(extract_upstream_error(payload)[0], expected)

    def test_detail_object_is_preserved_as_json_text(self):
        detail = {"type": "validation_error", "field": "prompt"}
        message, code = extract_upstream_error({"detail": detail})
        self.assertEqual(json.loads(message), detail)
        self.assertIsNone(code)

    def test_error_code_priority(self):
        payload = {
            "error": {"code": "E1"},
            "data": {"error": {"code": "E2"}},
            "error_code": "E3",
            "code": "E4",
            "status": "failed",
        }
        self.assertEqual(extract_upstream_error(payload)[1], "E1")

    def test_status_is_only_fallback(self):
        self.assertEqual(extract_upstream_error({"status": "cancelled"}), ("cancelled", None))
        self.assertEqual(
            extract_upstream_error({"status": "failed", "message": "actual upstream message"})[0],
            "actual upstream message",
        )

    def test_cancelled_and_canceled_are_failures(self):
        self.assertTrue(is_upstream_failure({"status": "cancelled"}))
        self.assertTrue(is_upstream_failure({"status": "canceled"}))

    def test_http_200_status_failed_is_logical_failure(self):
        response = httpx.Response(200, json={"status": "failed", "failure_reason": "model unavailable"})
        data = _request_json_or_raise(response, "fallback")
        normalized = _normalize_task_response(data)
        self.assertTrue(is_upstream_failure(normalized))
        self.assertEqual(extract_upstream_error(normalized["_raw"])[0], "model unavailable")

    def test_http_non_2xx_uses_upstream_json(self):
        payload = {"error": {"message": "Insufficient balance", "code": "insufficient_balance"}, "status": "failed"}
        response = httpx.Response(402, json=payload)
        with self.assertRaises(UpstreamError) as raised:
            _request_json_or_raise(response, "Create video failed")
        exc = raised.exception
        self.assertEqual(exc.error_message, "Insufficient balance")
        self.assertEqual(exc.error_code, "insufficient_balance")
        self.assertEqual(exc.upstream_response, payload)
        self.assertEqual(str(exc), "Insufficient balance")

    def test_download_video_propagates_terminal_upstream_failure(self):
        status_data = _normalize_task_response(
            {
                "id": "task_failed",
                "status": "failed",
                "error": {"message": "Failed to fetch image_url: 404", "code": "200"},
            }
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            with patch("app.services.sora_api.fetch_video_status", return_value=(status_data, 200, 5)):
                with self.assertRaises(UpstreamError) as raised:
                    download_video("key", "task_failed", Path(temp_dir) / "video.mp4")
        exc = raised.exception
        self.assertEqual(str(exc), "Failed to fetch image_url: 404")
        self.assertEqual(exc.status_code, 200)
        self.assertEqual(exc.error_code, "200")
        self.assertTrue(is_upstream_failure(exc.upstream_response))


class SQLiteCompatibilityTests(unittest.TestCase):
    def test_upstream_response_type_compiles_for_sqlite(self):
        from app.models.tables import Job

        compiled = Job.__table__.c.upstream_response.type.compile(dialect=sqlite.dialect())
        self.assertEqual(compiled.upper(), "JSON")


if __name__ == "__main__":
    unittest.main()
