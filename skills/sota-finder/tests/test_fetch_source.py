import importlib.util
import io
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "fetch_source.py"
SPEC = importlib.util.spec_from_file_location("sota_finder_fetch_source", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, body: bytes, *, content_type: str, url: str = "https://example.org/results"):
        self._stream = io.BytesIO(body)
        self._url = url
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeOpener:
    def __init__(self, response: FakeResponse):
        self.response = response

    def open(self, request, timeout):
        return self.response


class FetchSourceTests(unittest.TestCase):
    def config(self, root: Path, *, max_bytes: int = 4096):
        return MODULE.FetchConfig(
            timeout_seconds=5,
            max_bytes=max_bytes,
            output_dir=root / "sources",
        )

    def test_rejects_non_http_and_private_hosts(self):
        with self.assertRaisesRegex(MODULE.FetchSourceError, "http"):
            MODULE.validate_public_url("file:///tmp/result.txt")
        with self.assertRaisesRegex(MODULE.FetchSourceError, "public"):
            MODULE.validate_public_url("http://127.0.0.1/private")

    def test_fetches_html_as_readable_text_and_records_metadata(self):
        body = b"<html><head><title>Board</title><script>ignore()</script></head><body><table><tr><th>Method</th><th>Score</th></tr><tr><td>Leader</td><td>87.20</td></tr></table></body></html>"
        response = FakeResponse(body, content_type="text/html; charset=utf-8")
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            MODULE, "validate_public_url"
        ), mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=FakeOpener(response)
        ):
            result = MODULE.fetch_source("https://example.org/results", self.config(Path(temp_dir)))
            output = Path(result["output_path"])
            text = output.read_text(encoding="utf-8")
            self.assertIn("Method\tScore", text)
            self.assertIn("Leader\t87.20", text)
            self.assertNotIn("ignore()", text)
            self.assertEqual(result["source_url"], "https://example.org/results")

    def test_repeated_fetches_are_not_subject_to_an_aggregate_call_quota(self):
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            MODULE, "validate_public_url"
        ), mock.patch.object(
            MODULE.urllib.request,
            "build_opener",
            side_effect=[
                FakeOpener(FakeResponse(b"first", content_type="text/plain")),
                FakeOpener(FakeResponse(b"second", content_type="text/plain")),
            ],
        ):
            config = self.config(Path(temp_dir))
            first = MODULE.fetch_source("https://example.org/first", config)
            second = MODULE.fetch_source("https://example.org/second", config)
            self.assertNotEqual(first["output_path"], second["output_path"])
            self.assertIn("first", Path(first["output_path"]).read_text())
            self.assertIn("second", Path(second["output_path"]).read_text())

    def test_rejects_pdf_without_writing_a_source_file(self):
        response = FakeResponse(b"%PDF-1.7", content_type="application/pdf")
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            MODULE, "validate_public_url"
        ), mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=FakeOpener(response)
        ):
            config = self.config(Path(temp_dir))
            with self.assertRaisesRegex(MODULE.FetchSourceError, "PDF"):
                MODULE.fetch_source("https://example.org/paper.pdf", config)
            self.assertFalse(config.output_dir.exists())

    def test_rejects_responses_above_the_byte_limit(self):
        response = FakeResponse(b"x" * 33, content_type="text/plain")
        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            MODULE, "validate_public_url"
        ), mock.patch.object(
            MODULE.urllib.request, "build_opener", return_value=FakeOpener(response)
        ):
            with self.assertRaisesRegex(MODULE.FetchSourceError, "byte limit"):
                MODULE.fetch_source(
                    "https://example.org/large.txt",
                    self.config(Path(temp_dir), max_bytes=32),
                )


if __name__ == "__main__":
    unittest.main()
