"""Parser validation and layout regression tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from criminal_db.cli import cli
from criminal_db.harvester.parser import CanLIIParser
from criminal_db.validate import validate_paths

LAYOUTS = Path(__file__).parent / "fixtures" / "layouts"
REAL = Path(__file__).parent / "fixtures" / "real"


def test_validate_real_fixtures_all_ok():
    results = validate_paths([REAL])
    assert results, "expected at least one real fixture"
    errors = [r for r in results if not r.ok]
    assert not errors, [e.to_dict() for e in errors]


def test_documentcontent_only_layout():
    html = (LAYOUTS / "documentcontent_only.html").read_text(encoding="utf-8")
    case = CanLIIParser(html).parse()
    assert case.canlii_ref == "2022 ONCJ 100"
    assert len(case.paragraphs) >= 2
    assert case.corpus == "fulltext"


def test_meta_citation_layout():
    html = (LAYOUTS / "meta_citation.html").read_text(encoding="utf-8")
    case = CanLIIParser(html).parse()
    assert case.canlii_ref == "2021 BCCA 55"
    assert len(case.paragraphs) == 2


def test_cli_validate_json(tmp_path, fixtures_dir):
    src = fixtures_dir / "fulltext_scc.html"
    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "validate", str(src)])
    assert result.exit_code == 0, result.output
    assert '"ok": true' in result.output
    assert "2024 SCC 1" in result.output
