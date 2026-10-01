"""Save-directory persistence, filename sanitising, collision-free paths."""

from __future__ import annotations

import re
from pathlib import Path

from platformdirs import user_config_path

APP_NAME = "box-dl-gui"
_LEGACY_LAST_PATH = Path.home() / ".lastsavepath"

_VERSION_SUFFIX = re.compile(r"\((\d+)\)$")
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def _read_first_existing(*paths: Path) -> str:
    for p in paths:
        try:
            text = p.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return ""


def _config_file() -> Path:
    return user_config_path(APP_NAME) / "lastsavepath.txt"


def load_last_dir() -> Path:
    """Return the last used save dir, else ``~/Downloads``.

    Reads the new platformdirs config first, then the legacy
    ``~/.lastsavepath`` file for backward compatibility.
    """
    raw = _read_first_existing(_config_file(), _LEGACY_LAST_PATH)
    if raw:
        candidate = Path(raw).expanduser()
        if candidate.exists():
            return candidate
    return Path.home() / "Downloads"


def save_last_dir(directory: Path | str) -> None:
    """Persist the save dir (best effort -- never raises)."""
    try:
        cfg = _config_file()
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(str(Path(directory).expanduser()), encoding="utf-8")
    except OSError:
        pass


def sanitize_filename(name: str, fallback: str = "download") -> str:
    """Strip characters illegal on macOS/Windows, cap length, never empty."""
    cleaned = _BAD_CHARS.sub("_", (name or "").strip()).strip(" .")
    if len(cleaned) > 200:
        cleaned = cleaned[:200].rstrip(" .")
    return cleaned or fallback


def unique_path(path: Path | str) -> Path:
    """Return ``path`` or the first free ``name(1).ext`` sibling.

    Fixes the old regex version which only handled single-digit suffixes
    and recursed: ``report(9).pdf`` -> ``report(10).pdf``.
    """
    path = Path(path)
    if not path.exists():
        return path
    match = _VERSION_SUFFIX.search(path.stem)
    if match:
        base = path.stem[: match.start()].rstrip()
        counter = int(match.group(1)) + 1
    else:
        base = path.stem
        counter = 1
    while True:
        candidate = path.with_name(f"{base}({counter}){path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
