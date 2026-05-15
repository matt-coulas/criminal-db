"""Tests for get / export retrieval."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from criminal_db.cli import cli
from criminal_db.db import Database, DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.retrieval import citation_lookup_variants, normalize_canlii_ref


def test_normalize_canlii_ref():
    assert normalize_canlii_ref("2024 scc 1") == "2024 SCC 1"
    assert normalize_canlii_ref("  2024  scc   1  ") == "2024 SCC 1"


def test_citation_lookup_variants():
    variants = citation_lookup_variants("2024 scc 1")
    assert "2024 SCC 1" in variants


def test_router_get_case(dual_dbs, fulltext_html):
    ft, hn = dual_dbs
    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    try:
        router.store_case(export_case_to_json(CanLIIParser(fulltext_html).parse()))
        found = router.get_case("2024 scc 1")
        assert found is not None
        case, store = found
        assert case["canlii_ref"] == "2024 SCC 1"
        assert store == "fulltext"
        assert len(case["paragraphs"]) >= 1
    finally:
        router.close()


def test_cli_get_json(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    runner = CliRunner()
    src = fixtures_dir / "fulltext_scc.html"
    assert runner.invoke(cli, ["parse", str(src), "--no-catalog"]).exit_code == 0
    result = runner.invoke(cli, ["--json", "get", "2024 SCC 1"])
    assert result.exit_code == 0, result.output
    assert '"canlii_ref": "2024 SCC 1"' in result.output
    assert '"paragraphs"' in result.output


def test_cli_export(tmp_path, fixtures_dir, monkeypatch):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    out = tmp_path / "cases.json"
    runner = CliRunner()
    src = fixtures_dir / "fulltext_scc.html"
    runner.invoke(cli, ["parse", str(src), "--no-catalog"])
    result = runner.invoke(cli, ["export", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "2024 SCC 1" in out.read_text(encoding="utf-8")
