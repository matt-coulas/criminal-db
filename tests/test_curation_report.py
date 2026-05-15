"""Tests for curation QA report."""

from __future__ import annotations

from click.testing import CliRunner

from criminal_db.curation.report import (
    audit_database,
    is_borderline_excluded,
    is_borderline_included,
)
from criminal_db.curation.rules import CurationDecision, classify_case
from criminal_db.db import Database
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json


def test_borderline_excluded_mixed_court_no_signals():
    d = CurationDecision(False, "court:ONCA:no_criminal_signals")
    assert is_borderline_excluded(d)
    assert not is_borderline_included(d)


def test_borderline_included_content_only():
    d = CurationDecision(True, "content:criminal_law")
    assert is_borderline_included(d)
    assert not is_borderline_excluded(d)


def test_audit_database_lists_excluded(tmp_db, fulltext_html):
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    db.store_case(export_case_to_json(case))
    db.store_case(
        {
            "meta": {
                "canlii_ref": "2024 FCA 200",
                "court": "Federal Court of Appeal",
                "corpus": "fulltext",
            },
            "paragraphs": [
                {
                    "text": "Contract dispute between commercial parties.",
                    "paragraph_num": 1,
                }
            ],
        }
    )
    report = audit_database(db, apply=False)
    assert report.total == 2
    assert report.excluded >= 1
    assert any(r.canlii_ref == "2024 FCA 200" for r in report.excluded_cases)
    db.close()


def test_curate_report_json(tmp_path, monkeypatch, fixtures_dir):
    from criminal_db.cli import cli

    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    runner = CliRunner()
    src = fixtures_dir / "fulltext_scc.html"
    assert runner.invoke(cli, ["init"]).exit_code == 0
    assert runner.invoke(cli, ["parse", str(src), "--no-catalog"]).exit_code == 0
    result = runner.invoke(cli, ["--json", "curate", "--report", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "borderline" in result.output
    assert '"applied": false' in result.output or '"applied":false' in result.output.replace(
        " ", ""
    )
