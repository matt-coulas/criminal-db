"""Tests for :mod:`criminal_db.cli` using Click's CliRunner."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from criminal_db.cli import cli


def _invoke(args, **kwargs):
    runner = CliRunner()
    result = runner.invoke(cli, args, catch_exceptions=False, **kwargs)
    return result


def test_init_creates_databases(tmp_path: Path, monkeypatch, fixtures_dir):
    case_db = tmp_path / "criminal.db"
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.CASE_DB", case_db)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", case_db)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", case_db)
    monkeypatch.setattr("criminal_db.config.STATUTES_DB", tmp_path / "statutes.db")
    monkeypatch.setattr("criminal_db.config.DEFAULT_DB", case_db)

    result = _invoke(["init"])
    assert result.exit_code == 0, result.output
    assert case_db.exists()
    assert (tmp_path / "statutes.db").exists()


def test_parse_stores_case_in_db(tmp_path, fixtures_dir):
    db_path = tmp_path / "t.db"
    src = fixtures_dir / "fulltext_scc.html"
    result = _invoke(["parse", str(src), "--db", str(db_path)])
    assert result.exit_code == 0, result.output
    assert "2024 SCC 1" in result.output

    # Confirm with the analyze command.
    result2 = _invoke(["analyze", "--db", str(db_path)])
    assert result2.exit_code == 0, result2.output
    assert "cases:" in result2.output


def test_parse_no_store_emits_json(tmp_path, fixtures_dir):
    src = fixtures_dir / "fulltext_scc.html"
    result = _invoke(["parse", str(src), "--no-store"])
    assert result.exit_code == 0, result.output
    assert "2024 SCC 1" in result.output


def test_search_returns_results(tmp_path, fixtures_dir):
    db_path = tmp_path / "t.db"
    src = fixtures_dir / "fulltext_scc.html"
    assert _invoke(["parse", str(src), "--db", str(db_path)]).exit_code == 0

    result = _invoke(
        ["search", "warrantless", "--db", str(db_path), "--type", "fts"]
    )
    assert result.exit_code == 0, result.output
    assert "2024 SCC 1" in result.output


def test_search_no_results(tmp_path, fixtures_dir):
    db_path = tmp_path / "t.db"
    src = fixtures_dir / "fulltext_scc.html"
    _invoke(["parse", str(src), "--db", str(db_path)])
    result = _invoke(
        ["search", "xyzzyzzy_no_such_word", "--db", str(db_path), "--type", "fts"]
    )
    assert result.exit_code == 0, result.output
    assert "no results" in result.output


def test_help_renders():
    result = _invoke(["--help"])
    assert result.exit_code == 0
    for sub in (
        "init",
        "validate",
        "verify",
        "backup",
        "restore",
        "serve",
        "ingest",
        "import",
        "index",
        "curate",
        "get",
        "export",
        "parse",
        "harvest",
        "embed",
        "search",
        "analyze",
        "statutes",
        "tui",
    ):
        assert sub in result.output


def test_parse_routes_headnote_to_headnotes_db(
    tmp_path: Path, monkeypatch, fixtures_dir
):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(
        "criminal_db.config.MANIFEST_PATH", tmp_path / "index" / "manifest.json"
    )
    monkeypatch.setattr("criminal_db.config.DEFAULT_DB", tmp_path / "fulltext.db")

    _invoke(["init"])
    src = fixtures_dir / "headnote_fca.html"
    result = _invoke(["parse", str(src), "--no-catalog"])
    assert result.exit_code == 0, result.output

    from criminal_db.db import Database

    ft = Database(tmp_path / "fulltext.db", auto_init=False)
    hn = Database(tmp_path / "headnotes.db", auto_init=False)
    try:
        assert ft.case_count() == 0
        assert hn.case_count() == 1
    finally:
        ft.close()
        hn.close()


def test_search_json_output(tmp_path, fixtures_dir):
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr("criminal_db.config.DEFAULT_DB", tmp_path / "fulltext.db")
    try:
        src = fixtures_dir / "fulltext_scc.html"
        _invoke(["parse", str(src), "--db", str(tmp_path / "fulltext.db"), "--no-catalog"])
        result = _invoke(
            [
                "--json",
                "search",
                "warrantless",
                "--db",
                str(tmp_path / "fulltext.db"),
                "--type",
                "fts",
            ]
        )
        assert result.exit_code == 0, result.output
        assert '"results"' in result.output
        assert "2024 SCC 1" in result.output
    finally:
        monkeypatch.undo()
