"""Modern CustomTkinter GUI for macOS (replaces legacy gui.py / gui.pyw).

Run:  ``python -m box_dl``  or  ``python app.py``

Threading model: the download worker runs in a background thread and only
puts JobEvent objects on a queue. All Tk widgets are touched from the main
thread via ``after()`` polling -- the old code updated widgets directly
from the worker thread, which is unsafe in Tk.
"""

import logging
import platform
import queue
import subprocess
import threading
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Optional, Union

import customtkinter as ctk

from .store import load_last_dir, save_last_dir
from .worker import DownloadJob, run_job

log = logging.getLogger(__name__)


def open_in_file_manager(path: Union[Path, str]) -> None:
    """Reveal ``path`` in Finder / Explorer / xdg-open."""
    path = str(path)
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(["open", path], check=False)
        elif system == "Windows":
            subprocess.run(["explorer", str(Path(path))], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except OSError as exc:
        log.warning("open file manager failed: %s", exc)


class App(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Box.com Downloader")
        self.geometry("660x640")
        self.minsize(560, 540)

        self._events: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None

        # --- save path row ---
        save_frame = ctk.CTkFrame(self)
        save_frame.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(save_frame, text="Save to:").pack(side="left", padx=(10, 6), pady=10)
        self._save_var = ctk.StringVar(value=str(load_last_dir()))
        self._save_entry = ctk.CTkEntry(save_frame, textvariable=self._save_var)
        self._save_entry.pack(side="left", fill="x", expand=True, padx=6, pady=10)
        ctk.CTkButton(save_frame, text="Browse…", width=90,
                      command=self._on_browse).pack(side="left", padx=(6, 10), pady=10)

        # --- links ---
        ctk.CTkLabel(self, text="Paste box.com links (space or newline separated):",
                     anchor="w").pack(fill="x", padx=14, pady=(6, 0))
        self._links_box = ctk.CTkTextbox(self, height=140)
        self._links_box.pack(fill="both", expand=False, padx=12, pady=6)

        # --- options row ---
        opts = ctk.CTkFrame(self)
        opts.pack(fill="x", padx=12, pady=6)
        ctk.CTkLabel(opts, text="Wait (s):").pack(side="left", padx=(10, 4), pady=8)
        self._wait_var = ctk.StringVar(value="10")
        ctk.CTkEntry(opts, textvariable=self._wait_var, width=60).pack(
            side="left", padx=4, pady=8)
        self._chrome_var = ctk.BooleanVar(value=False)
        self._chrome_switch = ctk.CTkSwitch(
            opts, text="Use installed Chrome", variable=self._chrome_var)
        self._chrome_switch.pack(side="left", padx=16, pady=8)

        # --- buttons row ---
        btns = ctk.CTkFrame(self)
        btns.pack(fill="x", padx=12, pady=6)
        self._dl_btn = ctk.CTkButton(btns, text="Download", command=self._on_download)
        self._dl_btn.pack(side="left", padx=10, pady=10)
        self._cancel_btn = ctk.CTkButton(btns, text="Cancel", state="disabled",
                                         fg_color="gray", command=self._on_cancel)
        self._cancel_btn.pack(side="left", padx=6, pady=10)
        ctk.CTkButton(btns, text="Open folder",
                      command=lambda: open_in_file_manager(self._save_var.get())
                      ).pack(side="right", padx=10, pady=10)

        # --- progress + status ---
        self._progress = ctk.CTkProgressBar(self)
        self._progress.pack(fill="x", padx=12, pady=(6, 2))
        self._progress.set(0)
        self._status_var = ctk.StringVar(value="Ready")
        ctk.CTkLabel(self, textvariable=self._status_var,
                     anchor="w").pack(fill="x", padx=14, pady=2)

        # --- log ---
        ctk.CTkLabel(self, text="Log:", anchor="w").pack(fill="x", padx=14, pady=(4, 0))
        self._log_box = ctk.CTkTextbox(self, height=120, state="disabled")
        self._log_box.pack(fill="both", expand=True, padx=12, pady=(2, 12))

        self.after(150, self._poll)

    # -- UI helpers (main thread only) --
    def _log(self, message: str) -> None:
        self._log_box.configure(state="normal")
        self._log_box.insert("end", message + "\n")
        self._log_box.see("end")
        self._log_box.configure(state="disabled")

    def _set_running(self, running: bool) -> None:
        self._dl_btn.configure(state="disabled" if running else "normal")
        self._cancel_btn.configure(state="normal" if running else "disabled")

    # -- events --
    def _on_browse(self) -> None:
        chosen = filedialog.askdirectory(title="Choose PDF save folder")
        if chosen:
            self._save_var.set(chosen)
            save_last_dir(chosen)

    def _on_download(self) -> None:
        raw = self._links_box.get("1.0", "end")
        urls = [u for u in raw.split() if u]
        if not urls:
            messagebox.showinfo("Box Downloader", "Nothing to download.")
            return
        try:
            wait_time = max(1.0, float(self._wait_var.get()))
        except ValueError:
            messagebox.showerror("Box Downloader", "Wait time must be a number.")
            return
        out_dir = Path(self._save_var.get()).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("Box Downloader", f"Cannot create folder:\n{exc}")
            return
        save_last_dir(out_dir)

        self._events = queue.Queue()
        self._stop = threading.Event()
        job = DownloadJob(
            urls=urls,
            out_dir=out_dir,
            wait_time=wait_time,
            browser_channel="chrome" if self._chrome_var.get() else None,
        )
        self._worker = threading.Thread(target=run_job,
                                        args=(job, self._events, self._stop),
                                        daemon=True)
        self._set_running(True)
        self._progress.set(0)
        self._status_var.set(f"Starting… 0/{len(urls)}")
        self._log(f"Downloading {len(urls)} link(s) to {out_dir}")
        self._worker.start()

    def _on_cancel(self) -> None:
        self._stop.set()
        self._status_var.set("Cancelling…")

    def _poll(self) -> None:
        try:
            while True:
                event = self._events.get_nowait()
                self._handle_event(event)
        except queue.Empty:
            pass
        self.after(150, self._poll)

    def _handle_event(self, event):
        if event.total:
            try:
                self._progress.set(event.done / max(event.total, 1))
            except ValueError:
                pass
        if event.kind == "status":
            self._status_var.set(event.message)
        elif event.kind in ("file_done", "file_error"):
            self._status_var.set(event.message)
            self._log(event.message)
        elif event.kind == "finished":
            self._set_running(False)
            self._progress.set(1.0 if event.total else 0)
            self._status_var.set("Ready")
            self._log("Done.")


def main() -> None:
    """Launch the GUI (follows macOS light/dark mode automatically)."""
    logging.basicConfig(level=logging.WARNING)
    ctk.set_appearance_mode("System")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
