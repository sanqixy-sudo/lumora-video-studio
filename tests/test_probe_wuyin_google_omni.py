import json
import hashlib
import sys
import tempfile
import unittest
from argparse import Namespace
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import probe_wuyin_google_omni as probe  # noqa: E402


class FakeResponse:
    def __init__(self, body: bytes, status: int = 200, headers: dict | None = None):
        self._body = body
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def getcode(self):
        return self.status

    def read(self, _size=-1):
        body, self._body = self._body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class ResponseParsingTests(unittest.TestCase):
    def test_extract_task_id(self):
        payload = {"code": 200, "data": {"id": "video_123", "count": 10}}
        self.assertEqual(probe.extract_task_id(payload), "video_123")

    def test_extract_numeric_statuses(self):
        for status in (0, 1, 2, 3):
            with self.subTest(status=status):
                self.assertEqual(probe.extract_status({"data": {"status": str(status)}}), status)

    def test_unknown_status_is_preserved(self):
        self.assertEqual(probe.extract_status({"data": {"status": "queued"}}), "queued")

    def test_extracts_nested_urls_with_paths(self):
        entries = probe.extract_url_entries({"data": {"result": [{"video_url": "https://cdn.example/v.mp4"}]}})
        self.assertEqual(entries, [{"path": "$.data.result[0].video_url", "url": "https://cdn.example/v.mp4"}])

    def test_extracts_url_from_non_json_capture(self):
        capture = {"json_body": None, "raw_text": "result: https://cdn.example/v.mp4"}
        self.assertEqual(
            probe.extract_capture_url_entries(capture),
            [{"path": "$raw", "url": "https://cdn.example/v.mp4"}],
        )


class InputValidationTests(unittest.TestCase):
    def test_only_one_image_and_video_are_allowed(self):
        with self.assertRaises(ValueError):
            probe.normalize_single_url(["https://a.example/1.png", "https://a.example/2.png"], "reference image")
        with self.assertRaises(ValueError):
            probe.normalize_single_url(["https://a.example/1.mp4", "https://a.example/2.mp4"], "reference video")

    def test_non_http_url_is_rejected(self):
        with self.assertRaises(ValueError):
            probe.validate_web_url("file:///tmp/a.mp4", "reference video")

    def test_default_output_directory_is_inside_project(self):
        args = probe.build_parser().parse_args(["--prompt", "test"])
        self.assertEqual(Path(args.output_root), probe.PROJECT_ROOT / "probe_results" / "wuyin_google_omni")


class RedactionTests(unittest.TestCase):
    def test_secret_and_key_query_are_removed_recursively(self):
        secret = "super-secret-key"
        value = {
            "Authorization": secret,
            "url": f"https://api.example/detail?key={secret}&id=task",
            "nested": [f"Bearer {secret}"],
        }
        text = json.dumps(probe.sanitize_value(value, secret))
        self.assertNotIn(secret, text)
        self.assertIn(probe.REDACTED, text)

    def test_url_encoded_secret_is_removed(self):
        secret = "abc+/=secret"
        sanitized = probe.sanitize_text("token=abc%2B%2F%3Dsecret", secret)
        self.assertNotIn("abc%2B%2F%3Dsecret", sanitized)


class PaidRequestGuardTests(unittest.TestCase):
    @patch.object(probe, "run_paid_probe")
    @patch("builtins.print")
    def test_preview_does_not_start_paid_probe(self, _mocked_print, mocked_paid_probe):
        code = probe.main(["--prompt", "preview only"])
        self.assertEqual(code, 0)
        mocked_paid_probe.assert_not_called()


class HttpCaptureTests(unittest.TestCase):
    @patch.object(probe, "urlopen")
    def test_json_response_is_preserved(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(b'{"code":200,"data":{"status":1}}')
        captured = probe.capture_http("GET", "https://example.test/detail")
        self.assertEqual(captured["status_code"], 200)
        self.assertEqual(captured["json_body"]["data"]["status"], 1)
        self.assertEqual(captured["raw_text"], '{"code":200,"data":{"status":1}}')

    @patch.object(probe, "urlopen")
    def test_non_json_response_is_preserved(self, mocked_urlopen):
        mocked_urlopen.return_value = FakeResponse(b"gateway unavailable", headers={"Content-Type": "text/plain"})
        captured = probe.capture_http("GET", "https://example.test/detail")
        self.assertIsNone(captured["json_body"])
        self.assertIn("JSONDecodeError", captured["json_error"])
        self.assertEqual(captured["raw_text"], "gateway unavailable")

    @patch.object(probe, "urlopen")
    def test_http_error_body_is_preserved(self, mocked_urlopen):
        mocked_urlopen.side_effect = HTTPError(
            "https://example.test/detail",
            401,
            "Unauthorized",
            {"Content-Type": "application/json"},
            BytesIO(b'{"code":401,"msg":"bad key"}'),
        )
        captured = probe.capture_http("GET", "https://example.test/detail")
        self.assertEqual(captured["status_code"], 401)
        self.assertEqual(captured["json_body"]["msg"], "bad key")
        self.assertIn("HTTPError", captured["error"])


class DownloadTests(unittest.TestCase):
    @patch.object(probe, "urlopen")
    def test_video_download_records_file_size_and_hash(self, mocked_urlopen):
        content = b"fake-video-bytes"
        mocked_urlopen.return_value = FakeResponse(content, headers={"Content-Type": "video/mp4"})
        with tempfile.TemporaryDirectory() as temp_dir:
            results = probe.download_video_candidates(
                [{"path": "$.data.result.url", "url": "https://cdn.example/generated.mp4"}],
                Path(temp_dir),
                timeout=1,
                secret="secret",
            )
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["file_size"], len(content))
            self.assertEqual(results[0]["sha256"], hashlib.sha256(content).hexdigest())
            self.assertEqual((Path(temp_dir) / results[0]["file_name"]).read_bytes(), content)


def probe_args(output_root: str, *, timeout: float = 1.0, skip_download: bool = True) -> Namespace:
    return Namespace(
        output_root=output_root,
        request_timeout=1.0,
        timeout=timeout,
        poll_interval=0.001,
        skip_download=skip_download,
    )


class CaptureLifecycleTests(unittest.TestCase):
    @patch.object(probe.time, "sleep", return_value=None)
    @patch.object(probe, "download_video_candidates")
    @patch.object(probe, "capture_http")
    def test_success_flow_writes_all_artifacts_and_excludes_input_video(
        self, mocked_capture, mocked_download, _mocked_sleep
    ):
        input_video = "https://input.example/reference.mp4"
        result_video = "https://cdn.example/generated.mp4"
        mocked_capture.side_effect = [
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"id": "video_success"}},
                "raw_text": "",
                "error": None,
            },
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"status": 1, "video": input_video}},
                "raw_text": "",
                "error": None,
            },
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"status": 2, "result": {"url": result_video}}},
                "raw_text": "",
                "error": None,
            },
        ]
        mocked_download.return_value = [
            {"source_url": result_video, "file_name": "result_01.mp4", "file_size": 3, "sha256": "abc"}
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            code = probe.run_paid_probe(
                probe_args(temp_dir, skip_download=False),
                "secret",
                {"prompt": "test", "size": "1280x720", "duration": "10", "video": input_video},
            )
            run_dir = next(path for path in Path(temp_dir).iterdir() if path.is_dir())
            summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
            download_entries = mocked_download.call_args.args[0]
            self.assertEqual(code, 0)
            self.assertEqual(summary["outcome"], "success")
            self.assertEqual([item["status"] for item in summary["status_history"]], [1, 2])
            self.assertTrue((run_dir / "request.json").exists())
            self.assertTrue((run_dir / "create_response.json").exists())
            self.assertTrue((run_dir / "poll_0001.json").exists())
            self.assertTrue((run_dir / "poll_0002.json").exists())
            self.assertTrue((run_dir / "final_response.json").exists())
            self.assertNotIn(input_video, [entry["url"] for entry in download_entries])
            self.assertIn(result_video, [entry["url"] for entry in download_entries])

    @patch.object(probe.time, "sleep", return_value=None)
    @patch.object(probe, "download_video_candidates", side_effect=RuntimeError("download crashed"))
    @patch.object(probe, "capture_http")
    def test_download_exception_does_not_prevent_summary(self, mocked_capture, _mocked_download, _mocked_sleep):
        mocked_capture.side_effect = [
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"id": "video_success"}},
                "raw_text": "",
                "error": None,
            },
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"status": 2, "url": "https://cdn.example/out.mp4"}},
                "raw_text": "",
                "error": None,
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            code = probe.run_paid_probe(
                probe_args(temp_dir, skip_download=False),
                "secret",
                {"prompt": "test", "size": "1280x720", "duration": "10"},
            )
            summary_path = next(Path(temp_dir).glob("*/summary.json"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 0)
            self.assertEqual(summary["outcome"], "success")
            self.assertTrue(any("download crashed" in error for error in summary["errors"]))

    @patch.object(probe.time, "sleep", return_value=None)
    @patch.object(probe, "capture_http")
    def test_timeout_still_writes_summary(self, mocked_capture, _mocked_sleep):
        mocked_capture.return_value = {
            "status_code": 200,
            "json_body": {"code": 200, "data": {"id": "video_timeout"}},
            "raw_text": "",
            "error": None,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            code = probe.run_paid_probe(
                probe_args(temp_dir, timeout=0.0),
                "secret",
                {"prompt": "test", "size": "1280x720", "duration": "10"},
            )
            summaries = list(Path(temp_dir).glob("*/summary.json"))
            self.assertEqual(code, 3)
            self.assertEqual(len(summaries), 1)
            self.assertEqual(json.loads(summaries[0].read_text(encoding="utf-8"))["outcome"], "timeout")

    @patch.object(probe.time, "sleep", return_value=None)
    @patch.object(probe, "capture_http")
    def test_interrupt_still_writes_summary(self, mocked_capture, _mocked_sleep):
        mocked_capture.side_effect = [
            {
                "status_code": 200,
                "json_body": {"code": 200, "data": {"id": "video_interrupt"}},
                "raw_text": "",
                "error": None,
            },
            KeyboardInterrupt(),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            code = probe.run_paid_probe(
                probe_args(temp_dir),
                "secret",
                {"prompt": "test", "size": "1280x720", "duration": "10"},
            )
            summary_path = next(Path(temp_dir).glob("*/summary.json"))
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertEqual(code, 130)
            self.assertEqual(summary["outcome"], "interrupted")
            self.assertNotIn("secret", summary_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
