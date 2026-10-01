"""Unit tests for the box_dl package (stdlib only: `python -m unittest`)."""

from __future__ import annotations

import queue
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from box_dl.scraper import _is_preview_url, clean_title
from box_dl.store import sanitize_filename, unique_path
from box_dl.urls import is_box_url


class TestUrls(unittest.TestCase):
    def test_valid(self) -> None:
        self.assertTrue(is_box_url("https://acme.box.com/s/abc123"))
        self.assertTrue(is_box_url("https://box.com/s/abc"))
        self.assertTrue(is_box_url("  https://a.b.box.com/s/x  "))

    def test_invalid(self) -> None:
        for bad in ["", None, "not a url", "http://acme.box.com/s/x",
                    "https://evilbox.com/s/x", "https://box.com.evil.com/s/x"]:
            self.assertFalse(is_box_url(bad), bad)  # type: ignore[arg-type]
        # must be a real bool, not None (old url_checker returned None)
        self.assertIs(is_box_url("junk"), False)


class TestTitles(unittest.TestCase):
    def test_strips_only_last_extension(self) -> None:
        self.assertEqual(clean_title("My.report.final.pdf | Box"), "My.report.final")
        self.assertEqual(clean_title("Report.docx | Box"), "Report")

    def test_fallbacks(self) -> None:
        self.assertEqual(clean_title(""), "download")
        self.assertEqual(clean_title("NoExtension | Box"), "NoExtension")
        self.assertNotIn("/", clean_title("a/b.pdf | Box"))

    def test_preview_url_matcher(self) -> None:
        self.assertTrue(_is_preview_url(
            "https://public.boxcloud.com/api/2.0/files/1/content?preview=true"))
        self.assertTrue(_is_preview_url(
            "https://dl.boxcloud.com/api/2.0/files/1/content?preview=true"))
        self.assertTrue(_is_preview_url("https://x/internal_files/1.pdf?x=1"))
        self.assertFalse(_is_preview_url(""))
        self.assertFalse(_is_preview_url("https://example.com/file.pdf"))


class TestStore(unittest.TestCase):
    def test_sanitize(self) -> None:
        self.assertEqual(sanitize_filename(""), "download")
        self.assertNotIn("/", sanitize_filename('a/b:c*d?e"f<g>h|i'))

    def test_unique_path(self) -> None:
        with TemporaryDirectory() as td:
            d = Path(td)
            self.assertEqual(unique_path(d / "new.pdf"), d / "new.pdf")
            (d / "r.pdf").touch()
            self.assertEqual(unique_path(d / "r.pdf").name, "r(1).pdf")
            (d / "r(1).pdf").touch()
            (d / "r(9).pdf").touch()
            self.assertEqual(unique_path(d / "r.pdf").name, "r(2).pdf")
            self.assertEqual(unique_path(d / "r(9).pdf").name, "r(10).pdf")


class TestWorker(unittest.TestCase):
    def test_run_job_with_stubbed_io(self) -> None:
        import box_dl.worker as worker
        from box_dl.scraper import ScrapedFile

        class FakeScraper:
            def __init__(self, *a: object, **k: object) -> None:
                pass

            def fetch(self, url: str) -> ScrapedFile:
                if "bad" in url:
                    return ScrapedFile(title="x", download_url=None)
                return ScrapedFile(title="Doc", download_url="http://x/f.pdf")

        saved: list[Path] = []

        def fake_download(url: str, dest: Path) -> Path:
            Path(dest).write_bytes(b"pdf")
            saved.append(Path(dest))
            return Path(dest)

        orig_scraper, orig_dl = worker.BoxScraper, worker.download_file
        worker.BoxScraper, worker.download_file = FakeScraper, fake_download  # type: ignore[assignment]
        try:
            with TemporaryDirectory() as td:
                job = worker.DownloadJob(
                    urls=["https://a.box.com/s/1", "junk",
                          "https://a.box.com/s/bad"],
                    out_dir=Path(td), wait_time=0.1)
                events: queue.Queue = queue.Queue()
                worker.run_job(job, events, threading.Event())
                kinds = []
                while not events.empty():
                    kinds.append(events.get().kind)
        finally:
            worker.BoxScraper, worker.download_file = orig_scraper, orig_dl
        self.assertIn("file_done", kinds)
        self.assertEqual(kinds.count("file_error"), 2)  # invalid URL + no preview
        self.assertEqual(kinds[-1], "finished")
        self.assertEqual(len(saved), 1)


if __name__ == "__main__":
    unittest.main()
