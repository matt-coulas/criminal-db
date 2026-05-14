"""Extract individual case URLs from a CanLII listing/search page."""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from .. import config

# CanLII case-document URLs look like:
#   /en/<jurisdiction>/<court>/doc/<year>/<canlii-id>/<canlii-id>.html
_CASE_URL_RE = re.compile(
    r"^/(?:en|fr)/[a-z]{2,4}(?:/[a-z]+)*/doc/\d{4}/[^/]+/[^/]+\.html?$",
    re.IGNORECASE,
)


def extract_case_links(html: str, *, base_url: str = config.CANLII_BASE) -> list[str]:
    """Return absolute URLs of case-detail pages linked from ``html``.

    Duplicates are removed while preserving order.  The base URL defaults to
    the CanLII root; supply a different one if the listing was fetched from a
    mirror or saved file.
    """
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, None] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href:
            continue
        path = href if href.startswith("/") else _path_of(href)
        if path and _CASE_URL_RE.match(path):
            absolute = urljoin(base_url + "/", path.lstrip("/"))
            seen.setdefault(absolute, None)
    return list(seen)


def _path_of(url: str) -> str:
    parts = urlsplit(url)
    return parts.path or ""


def case_url_iter(html: str, *, base_url: str = config.CANLII_BASE) -> Iterable[str]:
    """Iterator variant of :func:`extract_case_links`."""
    yield from extract_case_links(html, base_url=base_url)
