# Box.com PDF Downloader (modern, macOS-first)

Downloads protected box.com shared files as PDF. Rewritten from the legacy
Tkinter + Selenium stack to **CustomTkinter + Playwright + httpx** (Python ≥ 3.10).

![Screenshot](screenshot.png)

## Quick start (macOS)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -e .
python -m playwright install chromium  # bundled browser (no chromedriver!)
python app.py                          # GUI  — or: python -m box_dl
```

Prefer your installed Google Chrome over the bundled Chromium? Either install
it normally, or tick **"Use installed Chrome"** in the GUI / pass `--use-chrome` to the CLI.

## Usage

GUI: paste box.com links (space or newline separated) → **Download**.
Per-file progress, cancellable, log at the bottom; save folder is remembered.

```bash
python -m box_dl.cli URL [URL ...] [--out ~/Downloads] [--wait-time 10] [--use-chrome] [--clean] [--open] [-v]
```

Installed (`pip install -e .`) shortcuts: `box-dl-gui` (GUI), `box-dl` (CLI),
`box-dl-clean` (watermark removal).

## Watermark removal

Box preview PDFs bake a diagonal watermark pattern into one full-page raster
image behind the real content. Strip it without touching text or figures:

```bash
python -m box_dl.clean doc.pdf                  # -> doc_clean.pdf
python -m box_dl.clean a.pdf b.pdf --out clean/ # several files
python -m box_dl.clean doc.pdf --in-place        # overwrite
```

Or tick **"Remove watermark"** in the GUI / pass `--clean` to `box-dl` to
clean right after download (in place, logged per file). Heuristic: an image
covering ≥85% of a page with a ≥400 px raster side counts as background
(`--min-coverage`, `--min-size` tune it); `--max-pages-share 0.9` protects
images reused on >90% of pages (template chrome, not watermark).

## Layout

- `app.py` — GUI launcher (`python app.py`).
- `box_dl/app.py` — CustomTkinter GUI, follows macOS light/dark mode.
- `box_dl/cli.py` — `box-dl` CLI, multiple URLs, exit 1 on any failure.
- `box_dl/scraper.py` — `BoxScraper.fetch(url)` via Playwright: watches live
  responses for `*.boxcloud.com/...content?preview=true` (or `internal_files…pdf`)
  with a `window.performance.getEntries()` fallback.
- `box_dl/worker.py` — background `run_job()` → Tk-safe `JobEvent` queue.
- `box_dl/downloader.py` — streaming `download_file()` via httpx.
- `box_dl/clean.py` — `clean_file()` / `clean_bytes()` / `box-dl-clean`: delete
  full-page watermark-background images, keep text and figures.
- `box_dl/store.py` — save-dir persistence, filename sanitising,
  collision-free `name(1).pdf` paths.
- `box_dl/urls.py` — `is_box_url()` validation.
- `tests/` — `python -m unittest discover -s tests`.

## Notes / gotchas

- The Box preview request fires asynchronously after page load: `--wait-time`
  (default 10 s) is a real requirement, not a tunable delay — don't shorten blindly.
- Save dir is stored via `platformdirs` (`~/Library/Application Support/box-dl-gui/…`
  on macOS); the legacy `~/.lastsavepath` file is still read as fallback.
- Existing files are never overwritten: `report.pdf` → `report(1).pdf`.
- Legacy files (`gui.py`, `gui.pyw`, `main.py`, `scraper.py`, `downloader.py`,
  `*.cmd`, old `requirements.txt` entries) are kept for reference but no longer used.

License: GNU General Public License v3.0
