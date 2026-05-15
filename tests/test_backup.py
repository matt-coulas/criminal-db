"""Backup and restore round-trip."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.db import DatabaseRouter
from criminal_db.db.schema import init_db
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.ops.backup import backup_data, restore_data


def test_backup_restore_roundtrip(tmp_path, monkeypatch, fixtures_dir):
    db_dir = tmp_path / "db"
    db_dir.mkdir()
    ft = db_dir / "fulltext.db"
    hn = db_dir / "headnotes.db"
    monkeypatch.setattr("criminal_db.config.DB_DIR", db_dir)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn)
    idx = tmp_path / "index"
    idx.mkdir()
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", idx)
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", idx / "manifest.json")
    init_db(ft)
    init_db(hn)
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn, auto_init=False)
    html = (fixtures_dir / "fulltext_scc.html").read_text(encoding="utf-8")
    router.store_case(export_case_to_json(CanLIIParser(html).parse()))
    router.close()

    archive = backup_data(tmp_path / "out", include_statutes=False)
    assert archive.is_file()

    ft.unlink()
    hn.unlink()
    restored = restore_data(archive)
    assert any(p.name == "fulltext.db" for p in restored)
    router2 = DatabaseRouter(fulltext_path=ft, headnotes_path=hn, auto_init=False)
    case = router2.get_case("2024 SCC 1")
    router2.close()
    assert case is not None
