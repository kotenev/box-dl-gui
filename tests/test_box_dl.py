"""Unit tests for the box_dl package (stdlib only: `python -m unittest`)."""

import queue
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import List

from box_dl.scraper import _is_preview_url, clean_title
from box_dl.store import sanitize_filename, unique_path
from box_dl.urls import is_box_url


class TestClean(unittest.TestCase):
    def _make_bg_pdf(self, with_bg: bool):
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        if with_bg:
            pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 595, 842), 0)
            pix.clear_with(210)
            page.insert_image(page.rect, pixmap=pix)
        page.insert_text((72, 100), "Hello watermark test", fontsize=14)
        raw = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        return raw

    def test_removes_full_page_background(self) -> None:
        from box_dl.clean import clean_bytes, find_background_images
        import pymupdf

        raw = self._make_bg_pdf(with_bg=True)
        doc = pymupdf.open(stream=raw, filetype="pdf")
        self.assertEqual(len(find_background_images(doc[0])), 1)
        doc.close()
        out, result = clean_bytes(raw)
        self.assertEqual(result.pages_total, 1)
        self.assertEqual(result.pages_cleaned, 1)
        self.assertLess(result.bytes_after, result.bytes_before)
        doc = pymupdf.open(stream=out, filetype="pdf")
        self.assertEqual(find_background_images(doc[0]), [])
        self.assertIn("Hello watermark test", doc[0].get_text())
        doc.close()

    def test_leaves_small_figures_alone(self) -> None:
        from box_dl.clean import clean_bytes
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=595, height=842)
        pix = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.IRect(0, 0, 100, 100), 0)
        pix.clear_with(210)
        page.insert_image(pymupdf.Rect(72, 72, 172, 172), pixmap=pix)
        page.insert_text((72, 250), "Small figure stays", fontsize=14)
        raw = doc.tobytes()
        doc.close()
        out, result = clean_bytes(raw)
        self.assertEqual(result.pages_cleaned, 0)
        doc = pymupdf.open(stream=out, filetype="pdf")
        self.assertEqual(len(doc[0].get_images(full=True)), 1)
        doc.close()

    def test_rejects_non_pdf(self) -> None:
        from box_dl.clean import clean_bytes

        with self.assertRaises(ValueError):
            clean_bytes(b"definitely not a pdf")

    def test_clean_file_roundtrip(self) -> None:
        from box_dl.clean import clean_file

        with TemporaryDirectory() as td:
            src = Path(td) / "wm.pdf"
            src.write_bytes(self._make_bg_pdf(with_bg=True))
            dst, result = clean_file(src)
            self.assertTrue(dst.is_file())
            self.assertEqual(result.pages_cleaned, 1)
            with self.assertRaises(FileNotFoundError):
                clean_file(Path(td) / "missing.pdf")


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
            def __init__(self, *args: object, **kwargs: object):
                pass

            def fetch(self, url: str) -> ScrapedFile:
                if "bad" in url:
                    return ScrapedFile(title="x", download_url=None)
                return ScrapedFile(title="Doc", download_url="http://x/f.pdf",
                                   auth_headers={"authorization": "Bearer test"},
                                   cookies=[{"name": "z", "value": "abc"}])

        saved: List[Path] = []
        seen_kwargs: List[dict] = []

        def fake_download(url: str, dest: Path, **kwargs) -> Path:
            seen_kwargs.append(kwargs)
            Path(dest).write_bytes(b"pdf")
            saved.append(Path(dest))
            return Path(dest)

        orig_scraper, orig_dl = worker.BoxScraper, worker.download_file
        worker.BoxScraper = FakeScraper  # type: ignore[assignment,misc]
        worker.download_file = fake_download  # type: ignore[assignment,misc]
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
            worker.BoxScraper = orig_scraper  # type: ignore[assignment,misc]
            worker.download_file = orig_dl  # type: ignore[assignment,misc]
        self.assertIn("file_done", kinds)
        self.assertEqual(kinds.count("file_error"), 2)  # invalid URL + no preview
        self.assertEqual(kinds[-1], "finished")
        self.assertEqual(len(saved), 1)
        # auth from the scrape must reach the download call
        self.assertEqual(seen_kwargs[0].get("headers"),
                         {"authorization": "Bearer test"})
        self.assertEqual(seen_kwargs[0].get("cookies"),
                         [{"name": "z", "value": "abc"}])


if __name__ == "__main__":
    unittest.main()
