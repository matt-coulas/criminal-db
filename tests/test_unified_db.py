"""Unified case database config and router behaviour."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db import config
from criminal_db.db import Database, DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


@pytest.fixture
def unified_db(tmp_path: Path, monkeypatch):
    case_db = tmp_path / "criminal.db"
    monkeypatch.setattr("criminal_db.config.CASE_DB", case_db)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", case_db)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", case_db)
    return case_db


def test_unified_config_paths_equal():
    assert config.case_db_unified()
    assert config.FULLTEXT_DB.resolve() == config.HEADNOTES_DB.resolve()
    assert config.CASE_DB.resolve() == config.FULLTEXT_DB.resolve()


def test_unified_router_searches_once(unified_db, fulltext_html, headnote_html):
    router = DatabaseRouter(fulltext_path=unified_db, headnotes_path=unified_db)
    try:
        router.store_case(export_case_to_json(CanLIIParser(fulltext_html).parse()))
        router.store_case(export_case_to_json(CanLIIParser(headnote_html).parse()))

        stores = router.stores_for_corpus_filter(None)
        assert len(stores) == 1

        db = Database(unified_db, auto_init=False)
        try:
            assert db.case_count() == 2
        finally:
            db.close()

        analysis = router.analyze()
        assert analysis["total"]["cases"] == 2
        assert analysis["stores"]["fulltext"]["cases"] == 2
    finally:
        router.close()
