"""Smoke eval: search quality on synthetic fixture corpora."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from criminal_db.db import DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.search_unified import search_all_fts
from criminal_db.statutes import JusticeCanadaParser, StatutesDatabase

EVAL_QUERIES = Path(__file__).parent / "eval" / "queries.json"
REAL_FIXTURES = Path(__file__).parent / "fixtures" / "real"
STATUTE_FIXTURE = Path(__file__).parent / "fixtures" / "statutes" / "justice_canada_sample.html"


@pytest.fixture(scope="module")
def eval_router(tmp_path_factory):
    base = tmp_path_factory.mktemp("eval")
    ft = base / "fulltext.db"
    hn = base / "headnotes.db"
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    for path in REAL_FIXTURES.glob("*.html"):
        if "headnote" in path.name and "headnote_only" not in path.name:
            continue
        html = path.read_text(encoding="utf-8")
        case = CanLIIParser(html, source_url=path.as_uri()).parse()
        if case.canlii_ref != "UNKNOWN":
            router.store_case(export_case_to_json(case))
    yield router
    router.close()


@pytest.fixture(scope="module")
def eval_statutes(tmp_path_factory):
    db_path = tmp_path_factory.mktemp("eval_stat") / "statutes.db"
    db = StatutesDatabase(db_path)
    html = STATUTE_FIXTURE.read_text(encoding="utf-8")
    db.store_sections(JusticeCanadaParser(html).parse())
    yield db
    db.close()


@pytest.mark.parametrize("case", json.loads(EVAL_QUERIES.read_text(encoding="utf-8")))
def test_eval_query(case, eval_router, eval_statutes):
    scope = case.get("scope", "cases")
    query = case["query"]
    min_hits = case.get("min_hits", 1)

    if scope == "statutes":
        results = eval_statutes.search_fts(query, limit=10)
        if case.get("expect_sections"):
            nums = {r.section_number for r in results}
            for sec in case["expect_sections"]:
                assert sec in nums, f"{case['id']}: expected s. {sec} in {nums}"
        assert len(results) >= min_hits, case["id"]
        return

    if scope == "all":
        hits = search_all_fts(
            query, router=eval_router, statutes=eval_statutes, limit=10
        )
        assert len(hits) >= min_hits, case["id"]
        return

    results = eval_router.search_fts(query, limit=10, criminal_only=True)
    refs = {r.canlii_ref for r in results}
    if case.get("expect_case_refs"):
        for ref in case["expect_case_refs"]:
            assert ref in refs, f"{case['id']}: expected {ref} in {refs}"
    assert len(results) >= min_hits, case["id"]
