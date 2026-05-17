"""Tests for config path env overrides."""

from __future__ import annotations

import importlib


def test_env_path_overrides(monkeypatch, tmp_path):
    data = tmp_path / "custom_data"
    db = tmp_path / "custom_db"
    data.mkdir()
    db.mkdir()
    monkeypatch.setenv("CRIMINAL_DB_DATA_DIR", str(data))
    monkeypatch.setenv("CRIMINAL_DB_DB_DIR", str(db))
    monkeypatch.delenv("CRIMINAL_DB_CASE_DB", raising=False)
    monkeypatch.delenv("CRIMINAL_DB_FULLTEXT_DB", raising=False)
    monkeypatch.delenv("CRIMINAL_DB_HEADNOTES_DB", raising=False)
    import criminal_db.config as cfg

    importlib.reload(cfg)
    try:
        assert cfg.DATA_DIR == data.resolve()
        assert cfg.DB_DIR == db.resolve()
        assert cfg.CASE_DB == db / "criminal.db"
        assert cfg.FULLTEXT_DB == cfg.CASE_DB
        assert cfg.HEADNOTES_DB == cfg.CASE_DB
        assert cfg.case_db_unified()
        assert cfg.MANIFEST_PATH == data / "index" / "manifest.json"
    finally:
        monkeypatch.delenv("CRIMINAL_DB_DATA_DIR", raising=False)
        monkeypatch.delenv("CRIMINAL_DB_DB_DIR", raising=False)
        importlib.reload(cfg)


def test_default_paths_under_base_dir():
    import criminal_db.config as cfg

    assert cfg.DATA_DIR == (cfg.BASE_DIR / "data").resolve()
    assert cfg.DB_DIR == (cfg.BASE_DIR / "db").resolve()
    assert cfg.CASE_DB == (cfg.DB_DIR / "criminal.db").resolve()
    assert cfg.case_db_unified()
    assert cfg.EMBEDDING_CACHE_DIR == cfg.MODELS_DIR / "embeddings"


def test_legacy_split_env(monkeypatch, tmp_path):
    ft = tmp_path / "fulltext.db"
    hn = tmp_path / "headnotes.db"
    monkeypatch.setenv("CRIMINAL_DB_FULLTEXT_DB", str(ft))
    monkeypatch.setenv("CRIMINAL_DB_HEADNOTES_DB", str(hn))
    monkeypatch.delenv("CRIMINAL_DB_CASE_DB", raising=False)
    import criminal_db.config as cfg

    importlib.reload(cfg)
    try:
        assert not cfg.case_db_unified()
        assert cfg.FULLTEXT_DB == ft.resolve()
        assert cfg.HEADNOTES_DB == hn.resolve()
    finally:
        monkeypatch.delenv("CRIMINAL_DB_FULLTEXT_DB", raising=False)
        monkeypatch.delenv("CRIMINAL_DB_HEADNOTES_DB", raising=False)
        importlib.reload(cfg)
