"""Background download orchestration (thread-based, Tk-safe via queue).

Old ``gui.pyw`` spawned a bare ``threading.Thread`` and updated Tk widgets
directly from it (``lbl_status.config`` from a worker thread), which is
undefined behaviour in Tk. Here the worker only puts :class:`JobEvent`
messages on a queue; the GUI polls it with ``after()`` on the main thread.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from pathlib import Path

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
    urls: list[str] = field(default_factory=list)
    out_dir: Path = field(default_factory=load_last_dir)
    wait_time: float = 10.0
    browser_channel: str | None = None


def run_job(job: DownloadJob, events: queue.Queue[JobEvent], stop: threading.Event) -> None:
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
            download_file(scraped.download_url, dest)
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
    events.put(JobEvent(kind="finished", message="Ready", done=total, total=total))
