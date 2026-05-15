"""Tests for catalog/DB verification."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.catalog.manifest import CatalogEntry, Manifest
from criminal_db.db import DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.verify import run_verify, verify_catalog_and_databases


def test_verify_empty_manifest_ok(tmp_path, monkeypatch):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", tmp_path / "index" / "manifest.json")
    (tmp_path / "index").mkdir()
    Manifest().save()
    router = DatabaseRouter(
        fulltext_path=tmp_path / "fulltext.db",
        headnotes_path=tmp_path / "headnotes.db",
    )
    router.close()
    report = verify_catalog_and_databases()
    assert report.ok


def test_verify_detects_missing_case(tmp_path, monkeypatch, fixtures_dir):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    ft = tmp_path / "fulltext.db"
    hn = tmp_path / "headnotes.db"
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn)
    idx = tmp_path / "index"
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", idx)
    mpath = idx / "manifest.json"
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", mpath)
    idx.mkdir()
    manifest = Manifest()
    manifest.upsert(
        CatalogEntry(
            source_path="data/cases/fulltext/x.html",
            status="ok",
            canlii_ref="2024 SCC 1",
            case_id=999,
            store="fulltext",
        )
    )
    manifest.save()
    DatabaseRouter(fulltext_path=ft, headnotes_path=hn).close()
    report = verify_catalog_and_databases()
    assert not report.ok
    assert any(i.code == "manifest_case_missing" for i in report.issues)


def test_verify_ok_with_stored_case(tmp_path, monkeypatch, fixtures_dir):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    ft = tmp_path / "fulltext.db"
    hn = tmp_path / "headnotes.db"
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn)
    idx = tmp_path / "index"
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", idx)
    mpath = idx / "manifest.json"
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", mpath)
    idx.mkdir()
    html = (fixtures_dir / "fulltext_scc.html").read_text(encoding="utf-8")
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    case = CanLIIParser(html).parse()
    case_id, store = router.store_case(export_case_to_json(case))
    router.close()
    manifest = Manifest()
    manifest.upsert(
        CatalogEntry(
            source_path="data/cases/fulltext/x.html",
            status="ok",
            canlii_ref=case.canlii_ref,
            case_id=case_id,
            store=store,
        )
    )
    manifest.save()
    report = verify_catalog_and_databases()
    assert report.ok
