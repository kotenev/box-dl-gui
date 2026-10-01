"""Modern CLI (replaces legacy main.py).

Usage:
    python -m box_dl.cli URL [URL ...] [--out DIR] [--wait-time 10]
                         [--use-chrome] [--open] [-v]
"""

import argparse
import logging
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

from .store import load_last_dir
from .worker import DownloadJob, run_job

log = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="box-dl",
        description="Download protected box.com shared files as PDF.",
    )
    parser.add_argument("urls", metavar="URL", nargs="+", help="Box.com shared URL(s)")
    parser.add_argument("--out", dest="out", default=str(load_last_dir()),
                        help="Output folder (default: last used or ~/Downloads)")
    parser.add_argument("--wait-time", dest="wait_time", type=float, default=10.0,
                        help="Seconds to wait for the Box preview to load (default: 10)")
    parser.add_argument("--use-chrome", action="store_true",
                        help="Drive installed Google Chrome instead of bundled Chromium")
    parser.add_argument("--open", action="store_true",
                        help="Open downloaded PDFs when finished")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--version", action="version", version="%(prog)s 2.0.0")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    out_dir = Path(args.out).expanduser()
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        parser.error(f"cannot create output folder: {exc}")

    events: queue.Queue = queue.Queue()
    stop = threading.Event()
    job = DownloadJob(
        urls=args.urls,
        out_dir=out_dir,
        wait_time=args.wait_time,
        browser_channel="chrome" if args.use_chrome else None,
    )
    failures = 0
    saved: List[str] = []

    worker = threading.Thread(target=run_job, args=(job, events, stop), daemon=True)
    worker.start()
    worker.join()

    while not events.empty():
        event = events.get()
        kind = event.kind
        if kind == "status":
            print(event.message)
        elif kind == "file_done":
            print(f"OK  {event.message} -> {event.path}")
            saved.append(event.path)
        elif kind == "file_error":
            print(f"FAIL {event.message}", file=sys.stderr)
            failures += 1

    if args.open:
        for path in saved:
            try:
                if sys.platform == "darwin":
                    subprocess.run(["open", path], check=False)
                else:
                    import webbrowser
                    webbrowser.open(path)
            except OSError as exc:
                log.warning("open failed for %s: %s", path, exc)

    if failures:
        print(f"{failures} of {len(args.urls)} failed.", file=sys.stderr)
        return 1
    print(f"Saved {len(saved)} file(s) to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
