"""Markdown export and write-on-store behaviour."""

from __future__ import annotations

from pathlib import Path

from criminal_db import config
from criminal_db.catalog.markdown_export import (
    case_markdown_filename,
    export_markdown,
    markdown_path_for_ref,
)
from criminal_db.db import Database, DatabaseRouter
from criminal_db.harvester.parser import CanLIIParser, export_case_to_json
from criminal_db.retrieval import format_case_markdown


def test_case_markdown_filename():
    assert case_markdown_filename("2024 SCC 1") == "2024_SCC_1.md"


def test_format_case_markdown_has_front_matter(fulltext_html):
    case = CanLIIParser(fulltext_html).parse()
    payload = export_case_to_json(case)
    text = format_case_markdown(
        {
            **payload["meta"],
            "paragraphs": payload["paragraphs"],
            "is_criminal": 1,
        },
        store="fulltext",
    )
    assert text.startswith("---\n")
    assert "canlii_ref:" in text
    assert "# " in text
    assert "**[1]**" in text or "[1]" in text


def test_store_case_writes_markdown(tmp_db, fulltext_html, tmp_path, monkeypatch):
    md_dir = tmp_path / "md"
    monkeypatch.setattr(config, "CASES_MD_DIR", md_dir)
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    ref = case.canlii_ref
    db.store_case(export_case_to_json(case))
    db.close()

    path = markdown_path_for_ref(ref, output_dir=md_dir)
    assert path.exists()
    body = path.read_text(encoding="utf-8")
    assert ref in body
    assert "---" in body


def test_store_case_no_md_skips_file(tmp_db, fulltext_html, tmp_path, monkeypatch):
    md_dir = tmp_path / "md"
    monkeypatch.setattr(config, "CASES_MD_DIR", md_dir)
    db = Database(tmp_db)
    case = CanLIIParser(fulltext_html).parse()
    db.store_case(export_case_to_json(case), write_md=False)
    db.close()
    assert not list(md_dir.glob("*.md"))


def test_export_markdown_command(dual_dbs, fulltext_html, tmp_path, monkeypatch):
    ft, hn = dual_dbs
    md_dir = tmp_path / "export-md"
    monkeypatch.setattr(config, "CASES_MD_DIR", md_dir)
    monkeypatch.setattr(config, "FULLTEXT_DB", ft)
    monkeypatch.setattr(config, "HEADNOTES_DB", hn)

    router = DatabaseRouter(fulltext_path=ft, headnotes_path=hn)
    try:
        router.store_case(export_case_to_json(CanLIIParser(fulltext_html).parse()))
        count = export_markdown(router, md_dir)
    finally:
        router.close()

    assert count == 1
    assert list(md_dir.glob("*.md"))


def test_cli_export_md(tmp_path, fixtures_dir, monkeypatch):
    from click.testing import CliRunner

    from criminal_db.cli import cli

    ft = tmp_path / "fulltext.db"
    md_dir = tmp_path / "md-out"
    monkeypatch.setattr(config, "FULLTEXT_DB", ft)
    monkeypatch.setattr(config, "HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr(config, "CASES_MD_DIR", tmp_path / "cases-md")

    src = fixtures_dir / "fulltext_scc.html"
    runner = CliRunner()
    runner.invoke(cli, ["parse", str(src), "--no-catalog"])
    result = runner.invoke(
        cli, ["export-md", "-o", str(md_dir), "--db", str(ft)]
    )
    assert result.exit_code == 0, result.output
    assert list(md_dir.glob("*.md"))
