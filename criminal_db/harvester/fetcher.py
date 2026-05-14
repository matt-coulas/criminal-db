"""Async HTTP fetcher with polite defaults and retry-with-backoff.

Defaults:

* A single, honest User-Agent (override via ``CRIMINAL_DB_USER_AGENT``).
* ≥5s minimum delay between requests, plus jitter.
* Optional ``robots.txt`` check at startup (skip with
  ``CRIMINAL_DB_RESPECT_ROBOTS=0``).
* Exponential backoff on 429 / 5xx with capped retries.
* No automatic retry on 4xx other than 429 — those are real errors.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import Optional
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import aiohttp

from .. import config


@dataclass
class FetchResult:
    """Result of a successful HTTP fetch."""

    url: str
    status: int
    html: str


_TRANSIENT_STATUSES = {429, 500, 502, 503, 504}


class CanLIIFetcher:
    """Async-safe HTTP fetcher.

    Designed to be used as an async context manager::

        async with CanLIIFetcher() as fetcher:
            result = await fetcher.fetch(url)
    """

    def __init__(
        self,
        *,
        user_agent: Optional[str] = None,
        delay_min: float | None = None,
        delay_max: float | None = None,
        max_retries: int | None = None,
        timeout: float | None = None,
        respect_robots: bool | None = None,
        proxy: Optional[str] = None,
    ) -> None:
        self.user_agent = user_agent or config.CANLII_USER_AGENT
        self.delay_min = float(
            delay_min if delay_min is not None else config.CANLII_DELAY_MIN
        )
        self.delay_max = float(
            delay_max if delay_max is not None else config.CANLII_DELAY_MAX
        )
        if self.delay_max < self.delay_min:
            self.delay_max = self.delay_min
        self.max_retries = int(
            max_retries if max_retries is not None else config.CANLII_MAX_RETRIES
        )
        self.timeout = float(
            timeout if timeout is not None else config.CANLII_TIMEOUT_S
        )
        self.respect_robots = (
            respect_robots
            if respect_robots is not None
            else config.CANLII_RESPECT_ROBOTS
        )
        self.proxy = proxy

        self._session: Optional[aiohttp.ClientSession] = None
        self._robots_cache: dict[str, robotparser.RobotFileParser] = {}
        self._last_request_at: float = 0.0
        self._lock = asyncio.Lock()

    # ── context manager ────────────────────────────────────────────────────

    async def __aenter__(self) -> "CanLIIFetcher":
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-CA,en;q=0.9",
                "Connection": "keep-alive",
            }
            self._session = aiohttp.ClientSession(
                headers=headers,
                connector=aiohttp.TCPConnector(
                    limit=max(1, config.CANLII_MAX_CONCURRENCY),
                    limit_per_host=max(1, config.CANLII_MAX_CONCURRENCY),
                    ttl_dns_cache=300,
                ),
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            )
        return self._session

    # ── robots.txt ─────────────────────────────────────────────────────────

    async def allowed_by_robots(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        rp = self._robots_cache.get(origin)
        if rp is None:
            rp = robotparser.RobotFileParser()
            robots_url = urljoin(origin, "/robots.txt")
            session = await self._ensure_session()
            try:
                async with session.get(robots_url) as resp:
                    if resp.status == 200:
                        body = await resp.text(errors="replace")
                        rp.parse(body.splitlines())
                    else:
                        # No robots.txt => assume allowed.
                        rp.parse([])
            except (aiohttp.ClientError, asyncio.TimeoutError):
                rp.parse([])
            self._robots_cache[origin] = rp
        return rp.can_fetch(self.user_agent, url)

    # ── fetch ─────────────────────────────────────────────────────────────

    async def fetch(self, url: str) -> Optional[FetchResult]:
        """Fetch ``url``.  Returns :class:`FetchResult` on 200, ``None`` otherwise."""
        if not await self.allowed_by_robots(url):
            return None

        session = await self._ensure_session()
        last_status: Optional[int] = None

        for attempt in range(self.max_retries + 1):
            await self._wait_polite_delay()
            try:
                kwargs = {}
                if self.proxy:
                    kwargs["proxy"] = self.proxy
                async with session.get(url, **kwargs) as resp:
                    last_status = resp.status
                    if resp.status == 200:
                        html = await resp.text(errors="replace")
                        if html:
                            return FetchResult(url=url, status=resp.status, html=html)
                        return None
                    if resp.status in _TRANSIENT_STATUSES:
                        await self._backoff_sleep(attempt, resp.headers.get("Retry-After"))
                        continue
                    # Other 4xx: real error, do not retry.
                    return None
            except (aiohttp.ClientError, asyncio.TimeoutError):
                await self._backoff_sleep(attempt, None)
                continue

        # Exhausted retries.
        _ = last_status  # silenced; caller can re-fetch to debug.
        return None

    # ── timing helpers ─────────────────────────────────────────────────────

    async def _wait_polite_delay(self) -> None:
        """Sleep so that consecutive fetches are spaced by ≥ ``delay_min``."""
        async with self._lock:
            loop = asyncio.get_event_loop()
            now = loop.time()
            elapsed = now - self._last_request_at
            wait_for = random.uniform(self.delay_min, self.delay_max)
            if elapsed < wait_for and self._last_request_at > 0:
                await asyncio.sleep(wait_for - elapsed)
            self._last_request_at = loop.time()

    async def _backoff_sleep(
        self, attempt: int, retry_after: Optional[str]
    ) -> None:
        if retry_after:
            try:
                await asyncio.sleep(min(120.0, float(retry_after)))
                return
            except ValueError:
                pass
        # Exponential backoff: 2^attempt * delay_min, capped at 120s.
        base = min(120.0, (2 ** attempt) * max(1.0, self.delay_min))
        jitter = base * random.uniform(-0.25, 0.25)
        await asyncio.sleep(max(1.0, base + jitter))
