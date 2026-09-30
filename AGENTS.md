# AGENTS.md

Small Windows-first Tkinter + Selenium scraper. No tests, lint, typecheck, CI, or build.

## Entrypoints
- `gui.pyw` — canonical GUI (`BoxGUIApp`). Launched via `BoxGUI.cmd` (`start pythonw gui.pyw`). Prefer over `gui.py` (legacy procedural duplicate, no `validate_outfile_name`, no chromedriver existence check).
- `main.py` — CLI: `python main.py <box-url> [--driver-path PATH] [--wait-time 15] [--use-x11] [--out DIR/]`.
- `scraper.py` — `Scraper` + `url_checker`; `downloader.py` — `download_file(url, path)` via `urllib3`.

## Setup
- `pip install -r requirements.txt` (`selenium`, `sv_ttk`, `PyVirtualDisplay`). Windows bootstrap: `setup.cmd` (global pip) or `dev-setup.cmd` (creates/uses `venv/`).
- Requires Google Chrome + matching chromedriver. Hardcoded lookup in `gui.pyw:173-176`: Windows `~\scoop\shims\chromedriver.exe`, Linux `/usr/bin/chromedriver`; anything else (macOS) falls through to `scraper.py:71` default `/usr/local/bin/chromedriver`. `gui.pyw` aborts with a messagebox if the path doesn't exist; `gui.py` does not check.

## Gotchas
- `scraper.py:80` uses Selenium 3-style `webdriver.Chrome(path, chrome_options=...)` — breaks on Selenium 4 (wants `service=Service(path), options=...`). The Windows branch (`service` + `CREATE_NO_WINDOW`) is the only modern call. Pin or migrate Selenium deliberately.
- `Scraper.load_url()` is a fixed `time.sleep(wait_time)` (GUI passes 10, CLI default 15). Don't shorten blindly; the preview URL is scraped from `window.performance.getEntries()` in `get_download_url()`.
- `url_checker()` regex is `https://(.*)\.box\.com/(.*)` and returns `None` (not `False`) on mismatch — test truthiness, not `is False` (`main.py:41` does this wrong for non-matching URLs that aren't exactly `False`).
- `get_download_title()` parses `driver.title` by splitting on `|` and `.` — fragile if Box changes title format; `get_download_url()` returns `None` when no `boxcloud.com/...content?preview=true` or `internal_files...pdf` entry is found.
- GUI runs downloads on a bare `threading.Thread` to keep Tk responsive; Tk widget updates from that thread (`lbl_status.config`) are technically unsafe but relied upon — keep long work off the main thread.
- Save path `Entry` has keypresses disabled (`bind('<Key>', ... 'break')`); change via Browse button only, persisted in `~/.lastsavepath`. Overwrite protection (`validate_outfile_name`, `file(1).pdf` style) exists only in `gui.pyw`.
- `evt_open_fol` handles Windows/Linux only — no-op on macOS. `--use-x11` path needs XQuartz on Darwin / `Display` on Linux.
- `downloader.py` has no error handling: if `http.request` raises/fails, `r` is `None` and `.read` crashes. `main.py` also auto-opens the PDF via `webbrowser.open` after download.
