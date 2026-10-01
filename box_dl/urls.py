"""Box shared-URL validation.

Old ``url_checker`` returned ``True`` or ``None`` (never ``False``), so
callers testing ``is False`` misclassified bad URLs. This returns a real
``bool`` -- test it with truthiness.
"""

from urllib.parse import urlparse


def is_box_url(url: str) -> bool:
    """Return True for ``https://`` Box URLs (``box.com`` or ``*.box.com``)."""
    if not url or not isinstance(url, str):
        return False
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.netloc:
        return False
    host = parts.netloc.split("@")[-1].split(":")[0].lower()
    return host == "box.com" or host.endswith(".box.com")
