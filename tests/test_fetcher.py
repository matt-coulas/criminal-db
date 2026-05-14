"""Tests for :mod:`criminal_db.harvester.fetcher`.

Uses ``aioresponses`` to mock the HTTP layer so no real network traffic
occurs.  The fetcher's polite-delay is monkey-patched to zero so the suite
stays fast.
"""

from __future__ import annotations

import asyncio

import pytest

aioresponses = pytest.importorskip("aioresponses").aioresponses

from criminal_db.harvester.fetcher import CanLIIFetcher


def _fetcher(**overrides):
    kwargs = dict(
        delay_min=0.0,
        delay_max=0.0,
        max_retries=2,
        respect_robots=False,
    )
    kwargs.update(overrides)
    return CanLIIFetcher(**kwargs)


@pytest.mark.asyncio
async def test_fetch_returns_html_on_200():
    url = "https://example.test/case.html"
    with aioresponses() as mocked:
        mocked.get(url, status=200, body="<html>ok</html>")
        async with _fetcher() as fetcher:
            result = await fetcher.fetch(url)
    assert result is not None
    assert result.status == 200
    assert "<html>ok</html>" in result.html


@pytest.mark.asyncio
async def test_fetch_returns_none_on_real_404():
    url = "https://example.test/missing.html"
    with aioresponses() as mocked:
        mocked.get(url, status=404, body="not found")
        async with _fetcher() as fetcher:
            result = await fetcher.fetch(url)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_retries_on_429_then_succeeds():
    url = "https://example.test/rate.html"
    with aioresponses() as mocked:
        mocked.get(url, status=429, headers={"Retry-After": "0"})
        mocked.get(url, status=200, body="<html>finally</html>")
        async with _fetcher() as fetcher:
            result = await fetcher.fetch(url)
    assert result is not None
    assert result.status == 200


@pytest.mark.asyncio
async def test_fetch_retries_on_5xx_then_gives_up():
    url = "https://example.test/server.html"
    with aioresponses() as mocked:
        for _ in range(3):  # max_retries + 1 attempts total
            mocked.get(url, status=503)
        async with _fetcher(max_retries=2) as fetcher:
            result = await fetcher.fetch(url)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_respects_robots_disallow():
    base = "https://example.test"
    url = f"{base}/case.html"
    robots_body = "User-agent: *\nDisallow: /\n"
    with aioresponses() as mocked:
        mocked.get(f"{base}/robots.txt", status=200, body=robots_body)
        async with _fetcher(respect_robots=True) as fetcher:
            result = await fetcher.fetch(url)
    assert result is None
