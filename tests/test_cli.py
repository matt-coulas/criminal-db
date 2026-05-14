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
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.DEFAULT_DB", tmp_path / "fulltext.db")

    result = _invoke(["init"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "headnotes.db").exists()
    assert (tmp_path / "fulltext.db").exists()


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
    # The previous CLI crashed at import time on @cli.command before def cli().
    for sub in ("init", "parse", "harvest", "embed", "search", "analyze"):
        assert sub in result.output
