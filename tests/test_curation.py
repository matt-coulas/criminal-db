"""Tests for criminal-law curation rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.curation import (
    Overrides,
    classify_case,
    curate_database,
    load_overrides,
)
from criminal_db.db import Database
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


def test_classify_criminal_by_title(fulltext_html):
    case = CanLIIParser(fulltext_html).parse()
    payload = export_case_to_json(case)
    decision = classify_case(payload["meta"], payload["paragraphs"])
    assert decision.is_criminal
    assert "court" in decision.reason or "content" in decision.reason


def test_classify_excludes_civil_fca_without_caption():
    meta = {
        "canlii_ref": "2024 FCA 99",
        "court": "Federal Court of Appeal",
    }
    paragraphs = [
        {
            "text": "This application for judicial review concerns administrative law.",
            "heading": "Issues",
        }
    ]
    decision = classify_case(meta, paragraphs)
    assert not decision.is_criminal


def test_override_include_wins():
    meta = {"canlii_ref": "2024 FCA 99", "court": "Federal Court of Appeal"}
    overrides = Overrides(include={"2024 FCA 99"})
    decision = classify_case(meta, [], overrides=overrides)
    assert decision.is_criminal
    assert decision.reason == "override:include"


def test_override_exclude_wins():
    meta = {"canlii_ref": "2024 SCC 1", "court": "Supreme Court of Canada"}
    paragraphs = [{"text": "R. v. Smith on appeal from conviction."}]
    overrides = Overrides(exclude={"2024 SCC 1"})
    decision = classify_case(meta, paragraphs, overrides=overrides)
    assert not decision.is_criminal


def test_store_case_sets_is_criminal(tmp_db, fulltext_html):
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    db.store_case(export_case_to_json(case))
    row = db.conn.execute(
        "SELECT is_criminal, exclusion_reason FROM cases WHERE canlii_ref = ?",
        ("2024 SCC 1",),
    ).fetchone()
    assert row["is_criminal"] == 1
    assert row["exclusion_reason"] is None
    db.close()


def test_search_hides_excluded_by_default(tmp_db, fulltext_html):
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    case_id = db.store_case(export_case_to_json(case))
    db.set_case_curation(case_id, is_criminal=False, exclusion_reason="test")
    hits = db.search_fts("warrantless", limit=5, criminal_only=True)
    assert not hits
    hits_all = db.search_fts("warrantless", limit=5, criminal_only=False)
    assert hits_all
    db.close()


def test_curate_command_json(tmp_path, monkeypatch, fixtures_dir):
    from click.testing import CliRunner

    from criminal_db.cli import cli

    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    runner = CliRunner()
    src = fixtures_dir / "fulltext_scc.html"
    assert runner.invoke(cli, ["init"]).exit_code == 0
    assert runner.invoke(cli, ["parse", str(src), "--no-catalog"]).exit_code == 0
    result = runner.invoke(cli, ["--json", "curate"])
    assert result.exit_code == 0, result.output
    assert "criminal" in result.output


def test_ingest_criminal_only_excludes(tmp_path, monkeypatch):
    from click.testing import CliRunner

    from criminal_db.cli import cli

    data = tmp_path / "data"
    index = data / "index"
    cases = data / "cases" / "fulltext"
    cases.mkdir(parents=True)
    index.mkdir(parents=True)
    monkeypatch.setattr("criminal_db.config.DATA_DIR", data)
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", index)
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", index / "manifest.json")
    monkeypatch.setattr("criminal_db.config.CASES_DIR", data / "cases")
    monkeypatch.setattr("criminal_db.config.RAW_DIR", data / "raw")
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")

    civil = cases / "civil.html"
    civil.write_text(
        """<!doctype html><html><body>
        <span class="citation">2024 FCA 200</span>
        <motion class="court">Federal Court of Appeal 2024</motion>
        <p class="text">Contract dispute between commercial parties.</p>
        </body></html>""".replace("motion", "div"),
        encoding="utf-8",
    )
    runner = CliRunner()
    assert runner.invoke(cli, ["init"]).exit_code == 0
    result = runner.invoke(cli, ["--json", "ingest", "--criminal-only"])
    assert result.exit_code == 0, result.output
    assert '"excluded": 1' in result.output or '"excluded":1' in result.output.replace(" ", "")
