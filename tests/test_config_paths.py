"""Tests for Docker volume path overrides."""

from __future__ import annotations

import importlib


def test_env_path_overrides(monkeypatch, tmp_path):
    data = tmp_path / "custom_data"
    db = tmp_path / "custom_db"
    data.mkdir()
    db.mkdir()
    monkeypatch.setenv("CRIMINAL_DB_DATA_DIR", str(data))
    monkeypatch.setenv("CRIMINAL_DB_DB_DIR", str(db))
    import criminal_db.config as cfg

    importlib.reload(cfg)
    try:
        assert cfg.DATA_DIR == data.resolve()
        assert cfg.DB_DIR == db.resolve()
        assert cfg.FULLTEXT_DB == db / "fulltext.db"
        assert cfg.MANIFEST_PATH == data / "index" / "manifest.json"
    finally:
        monkeypatch.delenv("CRIMINAL_DB_DATA_DIR", raising=False)
        monkeypatch.delenv("CRIMINAL_DB_DB_DIR", raising=False)
        importlib.reload(cfg)


def test_default_paths_under_base_dir():
    import criminal_db.config as cfg

    assert cfg.DATA_DIR == (cfg.BASE_DIR / "data").resolve()
    assert cfg.DB_DIR == (cfg.BASE_DIR / "db").resolve()
    assert cfg.EMBEDDING_CACHE_DIR == cfg.MODELS_DIR / "embeddings"
