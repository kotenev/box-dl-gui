"""Background download orchestration (thread-based, Tk-safe via queue).

Old ``gui.pyw`` spawned a bare ``threading.Thread`` and updated Tk widgets
directly from it (``lbl_status.config`` from a worker thread), which is
undefined behaviour in Tk. Here the worker only puts :class:`JobEvent`
messages on a queue; the GUI polls it with ``after()`` on the main thread.
"""

import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import httpx

from .downloader import download_file
from .scraper import BoxScraper
from .store import load_last_dir, unique_path
from .urls import is_box_url

log = logging.getLogger(__name__)


@dataclass
class JobEvent:
    """One status update for the GUI queue."""

    kind: str  # status | file_done | file_error | finished
    message: str = ""
    done: int = 0
    total: int = 0
    path: str = ""


@dataclass
class DownloadJob:
    urls: List[str] = field(default_factory=list)
    out_dir: Path = field(default_factory=load_last_dir)
    wait_time: float = 10.0
    browser_channel: Optional[str] = None
    clean_watermark: bool = False


def run_job(job: DownloadJob, events: queue.Queue, stop: threading.Event) -> None:
    """Process every URL, streaming progress into ``events``. Never raises."""
    scraper = BoxScraper(wait_time=job.wait_time, browser_channel=job.browser_channel)
    total = len(job.urls)
    for index, url in enumerate(job.urls, start=1):
        if stop.is_set():
            events.put(JobEvent(kind="status", message="Cancelled."))
            break
        prefix = f"[{index}/{total}]"
        if not is_box_url(url):
            events.put(
                JobEvent(kind="file_error", message=f"{prefix} Invalid Box URL, skipped.",
                         done=index, total=total)
            )
            continue
        events.put(JobEvent(kind="status", message=f"{prefix} Loading preview…"))
        try:
            scraped = scraper.fetch(url)
        except Exception as exc:  # keep going through the rest of the queue
            log.warning("scrape failed for %s: %s", url, exc)
            events.put(
                JobEvent(kind="file_error",
                         message=f"{prefix} Could not read preview: {exc}",
                         done=index, total=total)
            )
            continue
        if not scraped.download_url:
            events.put(
                JobEvent(kind="file_error",
                         message=f"{prefix} No preview file found on this page.",
                         done=index, total=total)
            )
            continue
        dest = unique_path(job.out_dir / f"{scraped.title}.pdf")
        events.put(JobEvent(kind="status", message=f"{prefix} Downloading {dest.name}…"))
        try:
            # Replay the browser session: the bare preview URL 401s elsewhere.
            download_file(scraped.download_url, dest,
                          headers=scraped.auth_headers or None,
                          cookies=scraped.cookies or None)
        except (httpx.HTTPError, OSError) as exc:
            log.warning("download failed for %s: %s", url, exc)
            events.put(
                JobEvent(kind="file_error", message=f"{prefix} Download failed: {exc}",
                         done=index, total=total)
            )
            continue
        events.put(
            JobEvent(kind="file_done", message=f"{prefix} Saved {dest.name}",
                     done=index, total=total, path=str(dest))
        )
        if job.clean_watermark:
            events.put(JobEvent(kind="status",
                                message=f"{prefix} Removing watermark background…"))
            try:
                from .clean import clean_file
                _cleaned_dst, _clean_result = clean_file(
                    dest, dest, overwrite=True)
                events.put(JobEvent(
                    kind="file_done",
                    message=(f"{prefix} Watermark removed "
                             f"({_clean_result.pages_cleaned}/"
                             f"{_clean_result.pages_total} pages)"),
                    done=index, total=total, path=str(dest)))
            except ImportError:
                events.put(JobEvent(
                    kind="file_error",
                    message=(f"{prefix} Watermark removal needs PyMuPDF: "
                             "pip install pymupdf"),
                    done=index, total=total))
            except (ValueError, OSError) as exc:
                log.warning("watermark removal failed for %s: %s", dest, exc)
                events.put(JobEvent(
                    kind="file_error",
                    message=f"{prefix} Watermark removal failed: {exc}",
                    done=index, total=total))
    events.put(JobEvent(kind="finished", message="Ready", done=total, total=total))
