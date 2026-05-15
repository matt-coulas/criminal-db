"""Tests for Criminal Code / Justice Canada statute parsing."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from criminal_db.cli import cli
from criminal_db.statutes import JusticeCanadaParser, StatutesDatabase, normalize_section_ref

FIXTURE = Path(__file__).parent / "fixtures" / "statutes" / "justice_canada_sample.html"


@pytest.fixture
def statute_html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


def test_normalize_section_ref():
    assert normalize_section_ref("s. 8") == "8"
    assert normalize_section_ref("section 83.01") == "83.01"


def test_parser_extracts_sections(statute_html):
    sections = JusticeCanadaParser(statute_html).parse()
    nums = {s.section_number for s in sections}
    assert "8" in nums
    assert "9" in nums
    assert "83.01" in nums
    s8 = next(s for s in sections if s.section_number == "8")
    assert "unreasonable search" in s8.text.lower()
    assert s8.heading and "search" in s8.heading.lower()


def test_statutes_db_round_trip(tmp_path, statute_html):
    db_path = tmp_path / "statutes.db"
    db = StatutesDatabase(db_path)
    sections = JusticeCanadaParser(statute_html).parse()
    assert db.store_sections(sections) == len(sections)
    row = db.get_section("8")
    assert row is not None
    assert "secure" in row["text"].lower()
    hits = db.search_fts("unreasonable search", limit=5)
    assert any(h.section_number == "8" for h in hits)
    db.close()


def test_cli_statutes_parse_and_get(tmp_path, monkeypatch, statute_html):
    monkeypatch.setattr("criminal_db.config.STATUTES_DB", tmp_path / "statutes.db")
    src = tmp_path / "cc.html"
    src.write_text(statute_html, encoding="utf-8")
    runner = CliRunner()
    assert runner.invoke(cli, ["statutes", "parse", str(src)]).exit_code == 0
    result = runner.invoke(cli, ["--json", "statutes", "get", "8"])
    assert result.exit_code == 0, result.output
    assert '"section_number": "8"' in result.output


def test_search_scope_statutes(tmp_path, monkeypatch, statute_html):
    monkeypatch.setattr("criminal_db.config.STATUTES_DB", tmp_path / "statutes.db")
    src = tmp_path / "cc.html"
    src.write_text(statute_html, encoding="utf-8")
    runner = CliRunner()
    runner.invoke(cli, ["statutes", "parse", str(src)])
    result = runner.invoke(
        cli, ["--json", "search", "unreasonable search", "--scope", "statutes"]
    )
    assert result.exit_code == 0, result.output
    assert '"section": "8"' in result.output
