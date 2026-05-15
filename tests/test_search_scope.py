"""Unified and statute search scope tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.db import DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.search_unified import search_all_fts
from criminal_db.statutes import JusticeCanadaParser, StatutesDatabase

STATUTE_FIXTURE = Path(__file__).parent / "fixtures" / "statutes" / "justice_canada_sample.html"


@pytest.fixture
def scope_router(tmp_path, fixtures_dir):
    ft = tmp_path / "ft.db"
    hn = tmp_path / "hn.db"
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    html = (fixtures_dir / "fulltext_scc.html").read_text(encoding="utf-8")
    router.store_case(export_case_to_json(CanLIIParser(html).parse()))
    yield router
    router.close()


@pytest.fixture
def scope_statutes(tmp_path):
    db = StatutesDatabase(tmp_path / "statutes.db")
    html = STATUTE_FIXTURE.read_text(encoding="utf-8")
    db.store_sections(JusticeCanadaParser(html).parse())
    yield db
    db.close()


def test_search_all_fts(scope_router, scope_statutes):
    hits = search_all_fts(
        "unreasonable search",
        router=scope_router,
        statutes=scope_statutes,
        limit=10,
    )
    kinds = {h.kind for h in hits}
    assert "case" in kinds or "statute" in kinds
    assert len(hits) >= 1
