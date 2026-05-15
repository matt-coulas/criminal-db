"""Tests for catalog manifest and ingest."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from criminal_db.catalog import Manifest, ingest_paths
from criminal_db.db import DatabaseRouter


@pytest.fixture
def catalog_env(tmp_path: Path, monkeypatch, fixtures_dir):
    data = tmp_path / "data"
    index = data / "index"
    cases_ft = data / "cases" / "fulltext"
    cases_hn = data / "cases" / "headnotes"
    for d in (index, cases_ft, cases_hn):
        d.mkdir(parents=True)
    ft_db = tmp_path / "fulltext.db"
    hn_db = tmp_path / "headnotes.db"
    manifest = index / "manifest.json"

    monkeypatch.setattr("criminal_db.config.DATA_DIR", data)
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", index)
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", manifest)
    monkeypatch.setattr("criminal_db.config.CASES_DIR", data / "cases")
    monkeypatch.setattr("criminal_db.config.RAW_DIR", data / "raw")
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft_db)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn_db)

    (cases_ft / "scc.html").write_text(
        (fixtures_dir / "fulltext_scc.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (cases_hn / "fca.html").write_text(
        (fixtures_dir / "headnote_fca.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return cases_ft, cases_hn, manifest, ft_db, hn_db


def test_ingest_populates_manifest_and_databases(catalog_env):
    cases_ft, cases_hn, manifest_path, ft_db, hn_db = catalog_env
    router = DatabaseRouter()
    try:
        report = ingest_paths([cases_ft, cases_hn], router=router)
    finally:
        router.close()

    assert report.ok == 2
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 2

    from criminal_db.db import Database

    ft = Database(ft_db, auto_init=False)
    hn = Database(hn_db, auto_init=False)
    try:
        assert ft.case_count() == 1
        assert hn.case_count() == 1
    finally:
        ft.close()
        hn.close()


def test_ingest_skips_unchanged_hash(catalog_env):
    cases_ft, _, manifest_path, _, _ = catalog_env
    router = DatabaseRouter()
    try:
        first = ingest_paths([cases_ft], router=router)
        second = ingest_paths([cases_ft], router=router)
    finally:
        router.close()

    assert first.ok == 1
    assert second.skipped == 1
    assert second.ok == 0
