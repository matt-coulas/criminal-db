"""Tests for offline HTML/PDF import."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from criminal_db.catalog.import_paths import (
    collect_import_files,
    import_paths,
    stage_import_file,
)
from criminal_db.catalog.pdf_extract import detect_paragraphs, extract_citation_from_text
from criminal_db.db import DatabaseRouter


@pytest.fixture
def import_env(tmp_path: Path, monkeypatch, fixtures_dir):
    data = tmp_path / "data"
    index = data / "index"
    import_dir = data / "import"
    for d in (index, import_dir / "html", import_dir / "pdf"):
        d.mkdir(parents=True)
    ft_db = tmp_path / "fulltext.db"
    hn_db = tmp_path / "headnotes.db"
    manifest = index / "manifest.json"

    monkeypatch.setattr("criminal_db.config.DATA_DIR", data)
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", index)
    monkeypatch.setattr("criminal_db.config.MANIFEST_PATH", manifest)
    monkeypatch.setattr("criminal_db.config.IMPORT_DIR", import_dir)
    monkeypatch.setattr("criminal_db.config.CASES_DIR", data / "cases")
    monkeypatch.setattr("criminal_db.config.RAW_DIR", data / "raw")
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", ft_db)
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", hn_db)
    monkeypatch.setattr("criminal_db.config.BASE_DIR", tmp_path)

    html_src = fixtures_dir / "fulltext_scc.html"
    return import_dir, manifest, ft_db, html_src


def test_detect_paragraphs_numbered():
    text = "[1] First point.\n[2] Second point."
    paras = detect_paragraphs(text)
    assert len(paras) == 2
    assert paras[0] == (1, "First point.")
    assert paras[1] == (2, "Second point.")


def test_extract_citation_from_text():
    assert extract_citation_from_text("Decision in 2024 SCC 1") == "2024 SCC 1"


def test_collect_import_files(import_env, fixtures_dir):
    import_dir, _, _, html_src = import_env
    outside = import_dir.parent / "outside.html"
    outside.write_text(html_src.read_text(encoding="utf-8"), encoding="utf-8")
    found = collect_import_files([import_dir.parent])
    suffixes = {p.suffix.lower() for p, _ in found}
    assert ".html" in suffixes


def test_import_html_populates_manifest(import_env):
    import_dir, manifest_path, ft_db, html_src = import_env
    dest = import_dir / "html" / "case.html"
    dest.write_text(html_src.read_text(encoding="utf-8"), encoding="utf-8")

    router = DatabaseRouter()
    try:
        report = import_paths([dest], router=router)
    finally:
        router.close()

    assert report.ok == 1
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(iter(data["entries"].values()))
    assert entry["source_type"] == "html"
    assert entry["canlii_ref"] == "2024 SCC 1"

    from criminal_db.db import Database

    db = Database(ft_db, auto_init=False)
    try:
        assert db.case_count() == 1
    finally:
        db.close()


def test_stage_import_file_copies_outside(import_env, fixtures_dir):
    import_dir, _, _, html_src = import_env
    outside = import_dir.parent / "remote.html"
    outside.write_text("x", encoding="utf-8")
    staged = stage_import_file(outside, "html")
    assert staged.parent == import_dir / "html"
    assert staged.exists()


def test_import_pdf_minimal(import_env, tmp_path):
    fitz = pytest.importorskip("fitz")
    import_dir, manifest_path, ft_db, _ = import_env

    pdf_path = import_dir / "pdf" / "synthetic.pdf"
    doc = fitz.open()
    page = doc.new_page()
    body = (
        "2024 SCC 99\n\n"
        "[1] The appellant challenges the search.\n\n"
        "[2] The appeal is allowed."
    )
    page.insert_text((72, 72), body, fontsize=11)
    doc.save(pdf_path)
    doc.close()

    router = DatabaseRouter()
    try:
        report = import_paths([pdf_path], router=router)
    finally:
        router.close()

    assert report.ok == 1
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    entry = next(iter(data["entries"].values()))
    assert entry["source_type"] == "pdf"
    assert entry["canlii_ref"] == "2024 SCC 99"

    from criminal_db.db import Database

    db = Database(ft_db, auto_init=False)
    try:
        assert db.case_count() == 1
    finally:
        db.close()


def test_import_cli_json(tmp_path, monkeypatch, fixtures_dir):
    monkeypatch.setattr("criminal_db.config.DB_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.FULLTEXT_DB", tmp_path / "fulltext.db")
    monkeypatch.setattr("criminal_db.config.HEADNOTES_DB", tmp_path / "headnotes.db")
    monkeypatch.setattr("criminal_db.config.INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(
        "criminal_db.config.MANIFEST_PATH", tmp_path / "index" / "manifest.json"
    )
    monkeypatch.setattr("criminal_db.config.IMPORT_DIR", tmp_path / "import")
    monkeypatch.setattr("criminal_db.config.BASE_DIR", tmp_path)
    monkeypatch.setattr("criminal_db.config.DATA_DIR", tmp_path / "data")

    from click.testing import CliRunner

    from criminal_db.cli import cli

    imp = tmp_path / "import" / "html"
    imp.mkdir(parents=True)
    (imp / "c.html").write_text(
        (fixtures_dir / "fulltext_scc.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(cli, ["--json", "import", str(imp)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] == 1
