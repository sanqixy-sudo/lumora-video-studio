import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

from app.services import sora_api, worker_engine


class DownloadHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/resume":
            content = b"complete-video"
            offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
            self.send_response(206 if offset else 200)
            self.send_header("Content-Length", str(len(content) - offset))
            self.send_header("Content-Type", "video/mp4")
            if offset:
                self.send_header("Content-Range", f"bytes {offset}-{len(content)-1}/{len(content)}")
            self.end_headers()
            self.wfile.write(content[offset:] if offset else content[:4])
            return
        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", "100" if self.path != "/ok" else "5")
        self.end_headers()
        try:
            if self.path == "/ok":
                self.wfile.write(b"video")
            elif self.path == "/partial":
                self.wfile.write(b"short")
            else:
                for _ in range(100):
                    self.wfile.write(b"x")
                    self.wfile.flush()
                    time.sleep(.1)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class DownloadDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), DownloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = "http://127.0.0.1:%s" % cls.server.server_port

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_success_publishes_complete_file_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "video.mp4"
            meta, status, _ = sora_api._download_url(self.url + "/ok", dest, time.perf_counter())
            self.assertEqual(status, 200)
            self.assertEqual(meta["bytes_written"], 5)
            self.assertEqual(dest.read_bytes(), b"video")
            self.assertEqual(list(Path(folder).glob("*.part")), [])

    def test_incomplete_transfer_does_not_replace_existing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "video.mp4"
            dest.write_bytes(b"existing")
            with self.assertRaises(sora_api.UpstreamError):
                sora_api._download_url(self.url + "/partial", dest, time.perf_counter())
            self.assertEqual(dest.read_bytes(), b"existing")
            self.assertEqual(dest.with_suffix(".mp4.download.part").read_bytes(), b"short")

    def test_slow_trickle_obeys_total_deadline(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sora_api, "DOWNLOAD_TOTAL_TIMEOUT_SECONDS", 1):
            dest = Path(folder) / "video.mp4"
            start = time.perf_counter()
            with self.assertRaises(sora_api.UpstreamError):
                sora_api._download_url(self.url + "/slow", dest, start)
            self.assertLess(time.perf_counter() - start, 4)
            self.assertFalse(dest.exists())
            self.assertGreater(dest.with_suffix(".mp4.download.part").stat().st_size, 0)

    def test_interrupted_download_resumes_without_duplicate_or_missing_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "video.mp4"
            with self.assertRaises(sora_api.UpstreamError) as raised:
                sora_api._download_url(self.url + "/resume", dest, time.perf_counter())
            self.assertEqual(raised.exception.error_code, "download_partial_progress")
            self.assertFalse(dest.exists())
            self.assertEqual(dest.with_suffix(".mp4.download.part").read_bytes(), b"comp")
            sora_api._download_url(self.url + "/resume", dest, time.perf_counter())
            self.assertEqual(dest.read_bytes(), b"complete-video")
            self.assertEqual(list(Path(folder).glob("*.part")), [])

    def test_connection_error_preserves_previously_downloaded_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            dest = Path(folder) / "video.mp4"
            with self.assertRaises(sora_api.UpstreamError):
                sora_api._download_url(self.url + "/resume", dest, time.perf_counter())
            result = subprocess.CompletedProcess([], 28, "000\n", "")
            with patch.object(sora_api.subprocess, "run", return_value=result):
                with self.assertRaises(sora_api.UpstreamError):
                    sora_api._download_url(self.url + "/resume", dest, time.perf_counter())
            self.assertEqual(dest.with_suffix(".mp4.download.part").read_bytes(), b"comp")

    def test_concurrent_writer_cannot_touch_partial_file(self):
        entered, release = threading.Event(), threading.Event()
        def transfer(*args, **kwargs):
            entered.set()
            release.wait(3)
            return subprocess.CompletedProcess([], 28, "000\n", "")
        with tempfile.TemporaryDirectory() as folder, ThreadPoolExecutor(max_workers=1) as pool:
            dest = Path(folder) / "video.mp4"
            with patch.object(sora_api.subprocess, "run", side_effect=transfer):
                first = pool.submit(sora_api._download_url, self.url + "/ok", dest, time.perf_counter())
                try:
                    self.assertTrue(entered.wait(1))
                    with self.assertRaisesRegex(sora_api.UpstreamError, "already in progress"):
                        sora_api._download_url(self.url + "/ok", dest, time.perf_counter())
                finally:
                    release.set()
                with self.assertRaises(sora_api.UpstreamError):
                    first.result(timeout=1)

    def test_hung_process_is_bounded_and_signed_url_not_in_error(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sora_api.subprocess, "run", side_effect=subprocess.TimeoutExpired("curl", 125)) as run:
            with self.assertRaises(sora_api.UpstreamError) as raised:
                sora_api._download_url("https://example.test/v?token=secret", Path(folder) / "v.mp4", time.perf_counter())
            self.assertNotIn("secret", str(raised.exception))
            self.assertEqual(run.call_args.kwargs["timeout"], 125)
            self.assertNotIn("secret", " ".join(run.call_args.args[0]))


class WorkerIsolationTests(unittest.TestCase):
    def test_download_saturation_leaves_polling_available_and_queue_bounded(self):
        release = threading.Event()
        with ThreadPoolExecutor(max_workers=3) as downloads, ThreadPoolExecutor(max_workers=1) as polls:
            try:
                with patch.object(worker_engine, "DOWNLOAD_EXECUTOR", downloads), patch.object(worker_engine, "_DOWNLOAD_FUTURES", {}), patch.object(worker_engine, "download_remote_job", lambda _: release.wait(5)):
                    self.assertTrue(worker_engine._schedule_download(1))
                    self.assertFalse(worker_engine._schedule_download(1))
                    self.assertTrue(worker_engine._schedule_download(2))
                    self.assertTrue(worker_engine._schedule_download(3))
                    self.assertFalse(worker_engine._schedule_download(4))
                    db = MagicMock()
                    db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
                        id=4, status="remote_completed", provider_key_id=1)
                    with patch.object(worker_engine, "SessionLocal") as session, patch.object(worker_engine, "_acquire_job_lock", return_value=True), patch.object(worker_engine, "_latest_event_at", return_value=worker_engine.utcnow()):
                        session.return_value.__enter__.return_value = db
                        # A real completed-job handoff must return even with all
                        # download slots occupied, rather than downloading inline.
                        self.assertIsNone(polls.submit(worker_engine.process_job, 4).result(timeout=1))
            finally:
                release.set()

    def test_running_future_is_never_forgotten_or_duplicated(self):
        running, queued = Future(), Future()
        running.set_running_or_notify_cancel()
        entries = {running: (10, worker_engine.utcnow()), queued: (11, worker_engine.utcnow())}
        with patch.object(worker_engine, "_PROCESS_FUTURES", entries):
            self.assertEqual(worker_engine._drop_process_futures_for_job(10), 0)
            self.assertIn(10, worker_engine._processing_job_ids())
            self.assertEqual(worker_engine._drop_process_futures_for_job(11), 1)
            self.assertTrue(queued.cancelled())


if __name__ == "__main__":
    unittest.main()
