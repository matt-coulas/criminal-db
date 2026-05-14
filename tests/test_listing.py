"""Tests for :mod:`criminal_db.harvester.listing`."""

from __future__ import annotations

from criminal_db.harvester.listing import extract_case_links


def test_extracts_unique_absolute_links(listing_html):
    links = extract_case_links(listing_html)
    assert links == [
        "https://www.canlii.org/en/ca/scc/doc/2024/2024scc1/2024scc1.html",
        "https://www.canlii.org/en/ca/fca/doc/2023/2023fca42/2023fca42.html",
        "https://www.canlii.org/en/on/onca/doc/2022/2022onca100/2022onca100.html",
    ]


def test_ignores_non_case_links(listing_html):
    links = extract_case_links(listing_html)
    assert all("/doc/" in url for url in links)
    assert all("about.html" not in url for url in links)


def test_empty_html_returns_empty_list():
    assert extract_case_links("") == []
