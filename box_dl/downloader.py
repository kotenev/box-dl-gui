"""Streaming file download via httpx (replaces raw urllib3)."""

from pathlib import Path
from typing import Union

import httpx


def download_file(url: str, dest: Union[Path, str], timeout: float = 60.0) -> Path:
    """Stream ``url`` to ``dest`` (creating parent dirs). Returns the path.

    Raises:
        httpx.HTTPError: on network/HTTP failures (callers must handle).
        OSError: on filesystem failures.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream(
        "GET", url, timeout=httpx.Timeout(timeout), follow_redirects=True
    ) as response:
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_bytes(chunk_size=65536):
                fh.write(chunk)
    return dest
