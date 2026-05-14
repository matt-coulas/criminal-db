"""Round-trip tests over realistic CanLII-style HTML fixtures.

These fixtures are SYNTHETIC — they are not scraped from canlii.org.  Real
CanLII pages are disallowed for our ``criminal-db/*`` User-Agent by
``https://www.canlii.org/robots.txt`` (the catch-all ``User-agent: * /
Disallow: /`` rule).  The fixtures here mimic the structural shapes we see
across courts and eras and exist to exercise each branch of the parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from criminal_db.db import Database
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "real"


@dataclass
class Expectation:
    """What we assert about a particular fixture once parsed + stored."""

    filename: str
    canlii_ref: str
    court: str
    court_year: int
    decided_date: str
    min_paragraphs: int
    max_paragraphs: int
    corpus: str  # 'fulltext' | 'headnote'
    judges_contains: tuple[str, ...]
    fts_query: str  # one example query that should match this case
    must_contain_paragraph_num: int | None = None


CASES: list[Expectation] = [
    Expectation(
        filename="scc_charter_section8.html",
        canlii_ref="2024 SCC 12",
        court="Supreme Court of Canada",
        court_year=2024,
        decided_date="2024-04-18",
        min_paragraphs=12,
        max_paragraphs=12,
        corpus="fulltext",
        judges_contains=("Wagner C.J.", "Karakatsanis J.", "Côté J."),
        fts_query="warrantless aerial thermal imaging",
        must_contain_paragraph_num=1,
    ),
    Expectation(
        filename="onca_inline_numbers.html",
        canlii_ref="2023 ONCA 712",
        court="Court of Appeal for Ontario",
        court_year=2023,
        decided_date="2023-11-02",
        min_paragraphs=9,
        max_paragraphs=9,
        corpus="fulltext",
        judges_contains=("Pepall J.A.", "Tulloch J.A.", "Coroza J.A."),
        fts_query="breath analyser impaired driving",
        must_contain_paragraph_num=1,
    ),
    Expectation(
        filename="fca_judicial_review.html",
        canlii_ref="2024 FCA 88",
        court="Federal Court of Appeal",
        court_year=2024,
        decided_date="2024-05-21",
        min_paragraphs=7,
        max_paragraphs=7,
        corpus="fulltext",
        judges_contains=("Stratas J.A.", "Mactavish J.A."),
        fts_query="Parole Board statutory release Vavilov",
    ),
    Expectation(
        filename="abca_headnote_only.html",
        canlii_ref="2022 ABCA 305",
        court="Court of Appeal of Alberta",
        court_year=2022,
        decided_date="2022-09-30",
        min_paragraphs=5,
        max_paragraphs=5,
        corpus="headnote",
        judges_contains=("Watson J.A.",),
        fts_query="aggravated assault air of reality self-defence",
    ),
    Expectation(
        filename="qcca_french_metadata.html",
        canlii_ref="2024 QCCA 401",
        court="Cour d'appel du Québec",
        court_year=2024,
        decided_date="2024-03-07",
        min_paragraphs=6,
        max_paragraphs=6,
        corpus="fulltext",
        judges_contains=("Bich J.A.",),
        fts_query="sexual assault reasonableness verdict",
    ),
]


@pytest.fixture(scope="module")
def real_fixture_db(tmp_path_factory) -> Database:
    """Parse every real fixture into a shared in-tree SQLite database."""
    db_path = tmp_path_factory.mktemp("real") / "real.db"
    db = Database(db_path)
    for expect in CASES:
        html = (FIXTURES_DIR / expect.filename).read_text(encoding="utf-8")
        case = CanLIIParser(html, source_url=f"fixture://{expect.filename}").parse()
        assert case.canlii_ref != "UNKNOWN", expect.filename
        db.store_case(export_case_to_json(case))
    yield db
    db.close()


# ── Parametrised expectations ──────────────────────────────────────────────


@pytest.mark.parametrize("expect", CASES, ids=lambda e: e.canlii_ref)
def test_parse_extracts_correct_metadata(expect: Expectation):
    html = (FIXTURES_DIR / expect.filename).read_text(encoding="utf-8")
    case = CanLIIParser(html).parse()
    assert case.canlii_ref == expect.canlii_ref
    assert expect.court in case.court
    assert case.court_year == expect.court_year
    assert case.decided_date == expect.decided_date
    assert case.corpus == expect.corpus
    for judge in expect.judges_contains:
        assert judge in case.judges, (judge, case.judges)


@pytest.mark.parametrize("expect", CASES, ids=lambda e: e.canlii_ref)
def test_parse_extracts_paragraphs(expect: Expectation):
    html = (FIXTURES_DIR / expect.filename).read_text(encoding="utf-8")
    case = CanLIIParser(html).parse()
    assert expect.min_paragraphs <= len(case.paragraphs) <= expect.max_paragraphs
    # All paragraphs should have non-empty text.
    assert all(p.text.strip() for p in case.paragraphs)
    # Paragraph numbers (when present) should be strictly increasing.
    nums = [p.paragraph_num for p in case.paragraphs if p.paragraph_num is not None]
    assert nums == sorted(set(nums)), nums
    if expect.must_contain_paragraph_num is not None:
        assert expect.must_contain_paragraph_num in nums


@pytest.mark.parametrize("expect", CASES, ids=lambda e: e.canlii_ref)
def test_db_round_trip_matches_parse(expect: Expectation, real_fixture_db: Database):
    case = real_fixture_db.get_case(expect.canlii_ref)
    assert case is not None
    assert case["court_year"] == expect.court_year
    assert case["decided_date"] == expect.decided_date
    assert case["corpus"] == expect.corpus
    assert (
        expect.min_paragraphs
        <= len(case["paragraphs"])
        <= expect.max_paragraphs
    )
    for judge in expect.judges_contains:
        assert judge in case["judges"]


@pytest.mark.parametrize("expect", CASES, ids=lambda e: e.canlii_ref)
def test_fts_finds_each_case(expect: Expectation, real_fixture_db: Database):
    results = real_fixture_db.search_fts(expect.fts_query, limit=5)
    refs = {r.canlii_ref for r in results}
    assert expect.canlii_ref in refs, (
        f"Expected {expect.canlii_ref} in FTS results for {expect.fts_query!r}, "
        f"got {refs}"
    )


# ── Cross-case sanity checks ───────────────────────────────────────────────


def test_corpus_filter_excludes_headnote_when_requested(real_fixture_db: Database):
    """When the user filters to fulltext, headnote-only cases must drop out."""
    results = real_fixture_db.search_fts("appeal", limit=20, corpus="fulltext")
    refs = {r.canlii_ref for r in results}
    assert "2022 ABCA 305" not in refs
    assert "2024 SCC 12" in refs or "2024 QCCA 401" in refs


def test_year_filter(real_fixture_db: Database):
    results = real_fixture_db.search_fts("appeal", limit=20, year=2024)
    years = {r.canlii_ref.split()[0] for r in results}
    assert years <= {"2024"}, years


def test_distinct_courts_recorded(real_fixture_db: Database):
    courts = set(real_fixture_db.court_distribution())
    # Each fixture should have produced a distinct court name.
    assert len(courts) >= 4
