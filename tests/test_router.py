"""Tests for :mod:`criminal_db.db.router`."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.db import Database, DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


@pytest.fixture
def dual_dbs(tmp_path: Path, monkeypatch):
    ft = tmp_path / "fulltext.db"
    hn = tmp_path / "headnotes.db"
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn)
    return ft, hn


def test_store_routes_by_corpus(dual_dbs, fulltext_html, headnote_html):
    ft, hn = dual_dbs
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    try:
        full = CanLIIParser(fulltext_html).parse()
        head = CanLIIParser(headnote_html).parse()
        assert full.corpus == "fulltext"
        assert head.corpus == "headnote"

        router.store_case(export_case_to_json(full))
        router.store_case(export_case_to_json(head))

        ft_db = Database(ft, auto_init=False)
        hn_db = Database(hn, auto_init=False)
        try:
            assert ft_db.case_count() == 1
            assert hn_db.case_count() == 1
            assert ft_db.get_case(full.canlii_ref) is not None
            assert hn_db.get_case(head.canlii_ref) is not None
        finally:
            ft_db.close()
            hn_db.close()
    finally:
        router.close()


def test_unified_search_merges_stores(dual_dbs, fulltext_html, headnote_html):
    ft, hn = dual_dbs
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    try:
        router.store_case(export_case_to_json(CanLIIParser(fulltext_html).parse()))
        router.store_case(export_case_to_json(CanLIIParser(headnote_html).parse()))

        hits = router.search_fts("Charter", limit=10)
        stores = {h.store for h in hits}
        assert "fulltext" in stores or "headnotes" in stores
        assert len(hits) >= 1
        assert all(h.store in ("fulltext", "headnotes") for h in hits)
    finally:
        router.close()
