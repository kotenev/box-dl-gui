# AGENTS.md

Modern CustomTkinter + Playwright + httpx app (Python ≥ 3.10, macOS-first). Legacy
Tkinter/Selenium files (`gui.py`, `gui.pyw`, `main.py`, `scraper.py`, `downloader.py`,
`*.cmd`) are kept for reference only — do not extend them.

## Entrypoints
- `app.py` → `box_dl/app.py:main` (`App`, CustomTkinter). Also `python -m box_dl`, or installed `box-dl-gui`.
- `box_dl/cli.py:main` (`box-dl`): `URL [URL ...] [--out DIR] [--wait-time 10] [--use-chrome] [--open] [-v]`; exit 1 if any URL failed.
- `box_dl/scraper.py:BoxScraper.fetch(url)`; `box_dl/worker.py:run_job(job, events, stop)`; `box_dl/downloader.py:download_file(url, dest)`; `box_dl/urls.py:is_box_url()`; `box_dl/store.py` (persistence, sanitize, `unique_path`).

## Setup
- `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt` (or `pip install -e .` for `box-dl-gui` / `box-dl` shims).
- `python -m playwright install chromium` — bundled browser, no chromedriver. `--use-chrome` / GUI switch drives installed Google Chrome via `channel="chrome"` instead.
- Tests: `python -m unittest discover -s tests` (stdlib only, stubbed I/O, no network/browser).

## Gotchas
- `wait_time` (default 10 s) is load-bearing: the Box preview fetch (`*.boxcloud.com/...content?preview=true` or `internal_files…pdf`) fires async after page load. `BoxScraper` collects live `response` URLs plus a `window.performance.getEntries()` fallback and returns the last match, or `download_url=None`.
- `is_box_url()` returns a real `bool` (old `url_checker` returned `True`/`None`; never test `is False` on legacy code). `clean_title()` strips only the final extension (`my.report.pdf` → `my.report`); `unique_path()` handles multi-digit suffixes (`r(9).pdf` → `r(10).pdf`) without recursion.
- Never touch Tk widgets from the worker thread: `run_job()` only puts `JobEvent`s on a queue; `App._poll()` (`after(150)`) applies them on the main thread.
- Save dir via `platformdirs` (`~/Library/Application Support/box-dl-gui/lastsavepath.txt` on macOS), legacy `~/.lastsavepath` read as fallback. `download_file()` raises `httpx.HTTPError`/`OSError` — `run_job()` converts to `file_error` events so one bad URL never aborts the queue.
