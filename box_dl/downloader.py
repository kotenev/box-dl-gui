"""Streaming file download via httpx (replaces raw urllib3)."""

from pathlib import Path
from typing import Dict, List, Optional, Union

import httpx

_HeaderDict = Dict[str, str]
_CookieList = List[Dict[str, str]]


def download_file(
    url: str,
    dest: Union[Path, str],
    timeout: float = 60.0,
    headers: Optional[_HeaderDict] = None,
    cookies: Optional[_CookieList] = None,
) -> Path:
    """Stream ``url`` to ``dest`` (creating parent dirs). Returns the path.

    ``headers``/``cookies`` replay the browser session that produced the URL:
    Box preview URLs (``*.boxcloud.com/...content?preview=true``) carry a
    per-session ``Authorization: Bearer`` token -- a bare GET from any other
    client gets ``401 Unauthorized``.

    Raises:
        httpx.HTTPError: on network/HTTP failures (callers must handle).
        OSError: on filesystem failures.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    jar = httpx.Cookies()
    for cookie in cookies or []:
        if cookie.get("name"):
            jar.set(cookie["name"], cookie.get("value", ""))
    with httpx.stream(
        "GET",
        url,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        headers=headers or None,
        cookies=jar or None,
    ) as response:
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_bytes(chunk_size=65536):
                fh.write(chunk)
    return dest
