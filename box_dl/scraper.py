"""Box preview-URL extraction via Playwright.

Replaces the Selenium + manually installed chromedriver setup (which broke
on Selenium 4 and needed per-OS driver paths). Playwright manages its own
bundled Chromium: ``playwright install chromium``. Pass
``browser_channel="chrome"`` to drive the installed Google Chrome instead.

How it works (same idea as the old code, modernised): Box preview pages
fetch the file from ``*.boxcloud.com/...content?preview=true`` (or an
``internal_files...pdf`` URL). We collect those URLs from live responses
plus a ``window.performance.getEntries()`` fallback, then return the last
match. A fixed ``wait_time`` is still needed -- the preview request fires
asynchronously after page load, so don't shorten it blindly.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from .store import sanitize_filename
from .urls import is_box_url

log = logging.getLogger(__name__)

_PREVIEW_HOSTS = (
    "public.boxcloud.com/api/2.0/files",
    "dl.boxcloud.com/api/2.0/files",
)
_PREVIEW_MARKER = "content?preview=true"


def _is_preview_url(url: str) -> bool:
    if not url:
        return False
    if any(host in url for host in _PREVIEW_HOSTS) and _PREVIEW_MARKER in url:
        return True
    return "internal_files" in url and "pdf" in url


def clean_title(raw_title: str) -> str:
    """Turn a Box tab title (``Report.pdf | Box``) into a safe stem.

    Old code did ``split(".")[:-1][0]`` which mangled dotted names
    (``my.report.pdf`` -> ``my``). This strips only the final extension.
    """
    name = (raw_title or "").split("|")[0].strip()
    stem = Path(name).stem if Path(name).suffix and len(Path(name).suffix) <= 6 else name
    return sanitize_filename(stem)


@dataclass(frozen=True)
class ScrapedFile:
    title: str
    download_url: Optional[str]


class BoxScraper:
    """Fetch one Box shared URL and extract its preview-download URL."""

    def __init__(
        self,
        wait_time: float = 10.0,
        headless: bool = True,
        browser_channel: Optional[str] = None,
        navigation_timeout_ms: int = 45_000,
    ) -> None:
        self.wait_time = wait_time
        self.headless = headless
        self.browser_channel = browser_channel
        self.navigation_timeout_ms = navigation_timeout_ms

    def fetch(self, url: str) -> ScrapedFile:
        """Load ``url`` headlessly and return title + preview URL (or None)."""
        if not is_box_url(url):
            raise ValueError(f"Not a Box shared URL: {url!r}")
        from playwright.sync_api import sync_playwright

        seen: List[str] = []
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=self.headless,
                args=["--no-sandbox"],
                channel=self.browser_channel,
            )
            try:
                page = browser.new_page()
                page.on(
                    "response",
                    lambda response: seen.append(response.url)
                    if _is_preview_url(response.url)
                    else None,
                )
                page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=self.navigation_timeout_ms,
                )
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except Exception:  # preview keeps polling; fixed wait covers it
                    log.debug("networkidle not reached, continuing with fixed wait")
                page.wait_for_timeout(int(self.wait_time * 1000))
                raw_title = page.title()
                entries: List[str] = page.evaluate(
                    "() => (window.performance.getEntries() || [])"
                    ".map(e => e.name).filter(n => typeof n === 'string')"
                )
            finally:
                browser.close()

        download_url: Optional[str] = None
        for candidate in list(reversed(seen)) + list(reversed(entries)):
            if _is_preview_url(candidate):
                download_url = candidate
                break
        return ScrapedFile(title=clean_title(raw_title), download_url=download_url)
