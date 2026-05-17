"""Tests for seed database builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from criminal_db.seed import build_seed_database, install_seed_database


def test_build_seed_database_from_fixtures(tmp_path: Path, fixtures_dir: Path):
    incoming = fixtures_dir.parent / "seed_corpus" / "incoming"
    if not any(incoming.rglob("*.html")):
        pytest.skip("seed_corpus/incoming has no HTML")

    db_dir = tmp_path / "db"
    data_dir = tmp_path / "data"
    result = build_seed_database(
        incoming,
        db_dir=db_dir,
        data_dir=data_dir,
        write_md=False,
    )
    assert result.source_files >= 1
    assert result.html_files >= 1
    assert result.report.ok >= 1
    assert result.case_db.is_file()
    assert result.fulltext_db == result.case_db
    assert result.headnotes_db == result.case_db
    assert result.manifest_path.is_file()


def test_build_seed_database_includes_pdf(tmp_path: Path):
    pytest.importorskip("fitz")
    incoming = tmp_path / "incoming"
    pdf_dir = incoming / "uploads"
    pdf_dir.mkdir(parents=True)
    pdf_path = pdf_dir / "synthetic.pdf"

    import fitz

    doc = fitz.open()
    page = doc.new_page()
    page.insert_text(
        (72, 72),
        "R. v. Seed 2024 ONCA 99\n\n"
        "[1] This is a synthetic paragraph for seed-build PDF support.\n",
    )
    doc.save(pdf_path)
    doc.close()

    db_dir = tmp_path / "db"
    data_dir = tmp_path / "data"
    result = build_seed_database(
        incoming,
        db_dir=db_dir,
        data_dir=data_dir,
        write_md=False,
    )
    assert result.pdf_files == 1
    assert result.report.ok >= 1


def test_install_seed_database(tmp_path: Path, fixtures_dir: Path):
    incoming = fixtures_dir.parent / "seed_corpus" / "incoming"
    if not any(incoming.rglob("*.html")):
        pytest.skip("seed_corpus/incoming has no HTML")

    seed_db = tmp_path / "seed"
    build_seed_database(incoming, db_dir=seed_db, data_dir=tmp_path / "data", write_md=False)
    target = tmp_path / "db"
    copied = install_seed_database(seed_db, target_db_dir=target)
    assert (target / "criminal.db").is_file()
    assert len(copied) >= 1


def test_build_seed_database_custom_db_path(tmp_path: Path, fixtures_dir: Path):
    incoming = fixtures_dir.parent / "seed_corpus" / "incoming"
    if not any(incoming.rglob("*.html")):
        pytest.skip("seed_corpus/incoming has no HTML")

    out = tmp_path / "custom.db"
    result = build_seed_database(
        incoming,
        db_dir=tmp_path,
        case_db=out,
        data_dir=tmp_path / "data",
        write_md=False,
    )
    assert result.case_db == out.resolve()
    assert out.is_file()
