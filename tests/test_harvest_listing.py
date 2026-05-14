"""Integration tests for the ``harvest --listing`` flow.

These tests stand up a fully mocked CanLII (listing page + N case-detail
pages + ``robots.txt``) with :mod:`aioresponses`, then exercise the CLI
end-to-end via Click's :class:`CliRunner`. They are the closest thing the
suite has to a live integration test of the harvester pipeline without
touching the real internet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

aioresponses = pytest.importorskip("aioresponses").aioresponses

from criminal_db.cli import cli
from criminal_db.db import Database


# ── Mock HTML helpers ──────────────────────────────────────────────────────


def _case_html(canlii_ref: str, court: str, year: int, date: str) -> str:
    """Minimal but parser-faithful CanLII-style case page."""
    return f"""<!doctype html>
<html><body>
  <span class="citation">{canlii_ref}</span>
  <div class="court">{court} {year}</div>
  <span class="date" data-type="date">{date}</span>
  <div class="panel"><span class="judge">McLachlin C.J.</span></div>
  <div class="documentcontent">
    <h2>Issues</h2>
    <p class="number">1</p>
    <p class="text">This is the first paragraph of {canlii_ref}, dealing with section 8 of the Charter.</p>
    <p class="number">2</p>
    <p class="text">The court holds that the warrantless search was unreasonable.</p>
    <p class="number">3</p>
    <p class="text">The appeal is allowed and a new trial is ordered.</p>
  </div>
</body></html>"""


LISTING_HTML = """<!doctype html>
<html><body>
  <h1>Search results</h1>
  <ul>
    <li><a href="/en/ca/scc/doc/2024/2024scc1/2024scc1.html">Case A</a></li>
    <li><a href="/en/ca/scc/doc/2024/2024scc2/2024scc2.html">Case B</a></li>
    <li><a href="/en/ca/scc/doc/2024/2024scc3/2024scc3.html">Case C</a></li>
    <li><a href="/en/info/about.html">not a case</a></li>
    <li><a href="/en/ca/scc/doc/2024/2024scc1/2024scc1.html">duplicate</a></li>
  </ul>
</body></html>"""

PERMISSIVE_ROBOTS = "User-agent: *\nAllow: /\n"


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fast_delays(monkeypatch):
    """Strip out all polite delays for the duration of these tests."""
    monkeypatch.setattr("criminal_db.config.CANLII_DELAY_MIN", 0.0)
    monkeypatch.setattr("criminal_db.config.CANLII_DELAY_MAX", 0.0)
    monkeypatch.setattr("criminal_db.config.CANLII_MAX_RETRIES", 1)


def _invoke(args, **kwargs):
    runner = CliRunner()
    return runner.invoke(cli, args, catch_exceptions=False, **kwargs)


def _mock_listing_response(mocked: aioresponses, *, robots: str = PERMISSIVE_ROBOTS) -> None:
    mocked.get(
        "https://www.canlii.org/robots.txt", status=200, body=robots
    )
    mocked.get(
        "https://www.canlii.org/en/ca/scc/listing", status=200, body=LISTING_HTML
    )


# ── Tests ─────────────────────────────────────────────────────────────────


def test_listing_harvest_stores_all_three_cases(tmp_path: Path):
    db_path = tmp_path / "listing.db"
    save_html = tmp_path / "saved"

    with aioresponses() as mocked:
        _mock_listing_response(mocked)
        for n in (1, 2, 3):
            mocked.get(
                f"https://www.canlii.org/en/ca/scc/doc/2024/2024scc{n}/2024scc{n}.html",
                status=200,
                body=_case_html(f"2024 SCC {n}", "Supreme Court of Canada", 2024, "2024-01-15"),
            )

        result = _invoke(
            [
                "harvest",
                "--listing",
                "--limit",
                "3",
                "--db",
                str(db_path),
                "--save-html",
                str(save_html),
                "https://www.canlii.org/en/ca/scc/listing",
            ]
        )

    assert result.exit_code == 0, result.output
    db = Database(db_path)
    try:
        assert db.case_count() == 3
        for n in (1, 2, 3):
            case = db.get_case(f"2024 SCC {n}")
            assert case is not None, f"missing 2024 SCC {n}"
            assert len(case["paragraphs"]) == 3
            assert case["paragraphs"][0]["paragraph_num"] == 1
    finally:
        db.close()

    saved = sorted(p.name for p in save_html.iterdir())
    assert "_index.html" in saved
    assert any("2024_SCC_1" in n for n in saved)
    assert any("2024_SCC_2" in n for n in saved)
    assert any("2024_SCC_3" in n for n in saved)


def test_listing_respects_limit(tmp_path: Path):
    db_path = tmp_path / "limit.db"

    with aioresponses() as mocked:
        _mock_listing_response(mocked)
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc1/2024scc1.html",
            status=200,
            body=_case_html("2024 SCC 1", "Supreme Court of Canada", 2024, "2024-01-15"),
        )
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc2/2024scc2.html",
            status=200,
            body=_case_html("2024 SCC 2", "Supreme Court of Canada", 2024, "2024-02-15"),
        )

        result = _invoke(
            [
                "harvest",
                "--listing",
                "--limit",
                "2",
                "--db",
                str(db_path),
                "https://www.canlii.org/en/ca/scc/listing",
            ]
        )

    assert result.exit_code == 0, result.output
    db = Database(db_path)
    try:
        assert db.case_count() == 2
        assert db.get_case("2024 SCC 3") is None
    finally:
        db.close()


def test_listing_continues_past_failing_case(tmp_path: Path):
    """A 404 on one case in the listing must not abort the rest."""
    db_path = tmp_path / "partial.db"

    with aioresponses() as mocked:
        _mock_listing_response(mocked)
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc1/2024scc1.html",
            status=200,
            body=_case_html("2024 SCC 1", "Supreme Court of Canada", 2024, "2024-01-15"),
        )
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc2/2024scc2.html",
            status=404,
            body="not found",
        )
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc3/2024scc3.html",
            status=200,
            body=_case_html("2024 SCC 3", "Supreme Court of Canada", 2024, "2024-03-15"),
        )

        result = _invoke(
            [
                "harvest",
                "--listing",
                "--limit",
                "3",
                "--db",
                str(db_path),
                "https://www.canlii.org/en/ca/scc/listing",
            ]
        )

    assert result.exit_code == 0, result.output
    db = Database(db_path)
    try:
        # Should have 1 and 3, not 2.
        assert db.case_count() == 2
        assert db.get_case("2024 SCC 1") is not None
        assert db.get_case("2024 SCC 3") is not None
        assert db.get_case("2024 SCC 2") is None
    finally:
        db.close()


def test_listing_aborts_when_index_fetch_fails(tmp_path: Path):
    """If the listing URL itself returns 503, we should bail without crashing."""
    db_path = tmp_path / "fail.db"

    with aioresponses() as mocked:
        mocked.get(
            "https://www.canlii.org/robots.txt", status=200, body=PERMISSIVE_ROBOTS
        )
        for _ in range(3):  # CANLII_MAX_RETRIES + 1 retries
            mocked.get(
                "https://www.canlii.org/en/ca/scc/listing",
                status=503,
            )

        result = _invoke(
            [
                "harvest",
                "--listing",
                "--limit",
                "5",
                "--db",
                str(db_path),
                "https://www.canlii.org/en/ca/scc/listing",
            ]
        )

    assert result.exit_code == 0, result.output
    assert "failed to fetch listing" in result.output

    db = Database(db_path)
    try:
        assert db.case_count() == 0
    finally:
        db.close()


def test_listing_robots_disallow_blocks_harvest(tmp_path: Path):
    """If robots.txt disallows our UA, the listing fetch is short-circuited."""
    db_path = tmp_path / "robots.db"

    with aioresponses() as mocked:
        mocked.get(
            "https://www.canlii.org/robots.txt",
            status=200,
            body="User-agent: *\nDisallow: /\n",
        )
        # No need to mock the listing URL — we should never call it.

        result = _invoke(
            [
                "harvest",
                "--listing",
                "--limit",
                "3",
                "--db",
                str(db_path),
                "https://www.canlii.org/en/ca/scc/listing",
            ]
        )

    assert result.exit_code == 0, result.output
    assert "failed to fetch listing" in result.output
    db = Database(db_path)
    try:
        assert db.case_count() == 0
    finally:
        db.close()


def test_single_harvest_stores_case(tmp_path: Path):
    """`--single` (default) harvest of a specific case URL stores one case."""
    db_path = tmp_path / "single.db"

    with aioresponses() as mocked:
        mocked.get(
            "https://www.canlii.org/robots.txt", status=200, body=PERMISSIVE_ROBOTS
        )
        mocked.get(
            "https://www.canlii.org/en/ca/scc/doc/2024/2024scc7/2024scc7.html",
            status=200,
            body=_case_html("2024 SCC 7", "Supreme Court of Canada", 2024, "2024-07-04"),
        )
        result = _invoke(
            [
                "harvest",
                "--db",
                str(db_path),
                "https://www.canlii.org/en/ca/scc/doc/2024/2024scc7/2024scc7.html",
            ]
        )

    assert result.exit_code == 0, result.output
    db = Database(db_path)
    try:
        case = db.get_case("2024 SCC 7")
        assert case is not None
        assert case["decided_date"] == "2024-07-04"
    finally:
        db.close()
