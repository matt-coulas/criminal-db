"""Build a starter SQLite corpus from HTML on disk (seed / demo database)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config
from .catalog.import_paths import collect_import_files, import_paths
from .catalog.ingest import IngestReport
from .catalog.manifest import ensure_catalog_dirs
from .db.router import DatabaseRouter
from .db.schema import init_db


@dataclass(frozen=True)
class SeedBuildResult:
    """Paths and ingest stats after :func:`build_seed_database`."""

    db_dir: Path
    data_dir: Path
    fulltext_db: Path
    headnotes_db: Path
    manifest_path: Path
    report: IngestReport
    source_files: int
    html_files: int
    pdf_files: int

    def to_dict(self) -> dict:
        return {
            "db_dir": str(self.db_dir),
            "data_dir": str(self.data_dir),
            "fulltext_db": str(self.fulltext_db),
            "headnotes_db": str(self.headnotes_db),
            "manifest_path": str(self.manifest_path),
            "source_files": self.source_files,
            "html_files": self.html_files,
            "pdf_files": self.pdf_files,
            "ingest": self.report.to_dict(),
        }


def build_seed_database(
    input_dir: Path,
    *,
    db_dir: Optional[Path] = None,
    data_dir: Optional[Path] = None,
    criminal_only: bool = False,
    force: bool = False,
    write_md: bool = True,
) -> SeedBuildResult:
    """Parse HTML and PDF under ``input_dir`` into fresh DB files under ``db_dir``.

    Any nested layout is fine (e.g. ``court/year/case.html``); files are
    discovered recursively. Corpus (fulltext vs headnote) is inferred from
    path segments ``fulltext`` / ``headnotes`` when present. PDFs require the
    ``criminal-db[pdf]`` extra (PyMuPDF).
    """
    incoming = input_dir.resolve()
    if not incoming.is_dir():
        raise FileNotFoundError(f"seed input directory not found: {incoming}")

    sources = collect_import_files([incoming])
    if not sources:
        raise ValueError(
            f"no .html or .pdf files under {incoming}; add case files first"
        )
    html_files = sum(1 for _path, kind in sources if kind == "html")
    pdf_files = sum(1 for _path, kind in sources if kind == "pdf")

    out_db = Path(db_dir or (config.BASE_DIR / "db" / "seed")).resolve()
    out_data = Path(data_dir or (config.BASE_DIR / "data" / "seed")).resolve()
    out_db.mkdir(parents=True, exist_ok=True)
    out_data.mkdir(parents=True, exist_ok=True)

    ft_path = out_db / "fulltext.db"
    hn_path = out_db / "headnotes.db"
    if force:
        for p in (ft_path, hn_path):
            if p.exists():
                p.unlink()

    # Temporarily point config at seed trees (manifest + optional markdown).
    prev = _snapshot_config_paths()
    report: IngestReport
    try:
        _apply_config_paths(
            data_dir=out_data,
            db_dir=out_db,
            fulltext_db=ft_path,
            headnotes_db=hn_path,
        )
        ensure_catalog_dirs()
        init_db(ft_path)
        init_db(hn_path)

        router = DatabaseRouter(
            fulltext_path=ft_path,
            headnotes_path=hn_path,
            auto_init=False,
        )
        try:
            report = import_paths(
                [incoming],
                router=router,
                force=force,
                criminal_only=criminal_only,
                write_md=write_md,
            )
        finally:
            router.close()
    finally:
        _restore_config_paths(prev)

    return SeedBuildResult(
        db_dir=out_db,
        data_dir=out_data,
        fulltext_db=ft_path,
        headnotes_db=hn_path,
        manifest_path=out_data / "index" / "manifest.json",
        report=report,
        source_files=len(sources),
        html_files=html_files,
        pdf_files=pdf_files,
    )


def _snapshot_config_paths() -> dict[str, Path]:
    keys = (
        "DATA_DIR",
        "DB_DIR",
        "INDEX_DIR",
        "MANIFEST_PATH",
        "OVERRIDES_PATH",
        "FULLTEXT_DB",
        "HEADNOTES_DB",
        "CASES_DIR",
        "CASES_MD_DIR",
        "IMPORT_DIR",
        "RAW_DIR",
    )
    return {k: getattr(config, k) for k in keys}


def _apply_config_paths(
    *,
    data_dir: Path,
    db_dir: Path,
    fulltext_db: Path,
    headnotes_db: Path,
) -> None:
    config.DATA_DIR = data_dir
    config.DB_DIR = db_dir
    config.INDEX_DIR = data_dir / "index"
    config.MANIFEST_PATH = config.INDEX_DIR / "manifest.json"
    config.OVERRIDES_PATH = config.INDEX_DIR / "overrides.yaml"
    config.FULLTEXT_DB = fulltext_db
    config.HEADNOTES_DB = headnotes_db
    config.CASES_DIR = data_dir / "cases"
    config.CASES_MD_DIR = config.CASES_DIR / "md"
    config.IMPORT_DIR = data_dir / "import"
    config.RAW_DIR = data_dir / "raw"


def _restore_config_paths(snapshot: dict[str, Path]) -> None:
    for key, value in snapshot.items():
        setattr(config, key, value)


def install_seed_database(
    seed_db_dir: Path,
    *,
    target_db_dir: Optional[Path] = None,
) -> list[Path]:
    """Copy ``fulltext.db`` and ``headnotes.db`` from a seed build into ``db/``."""
    src = seed_db_dir.resolve()
    dest = Path(target_db_dir or config.DB_DIR).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in ("fulltext.db", "headnotes.db", "statutes.db"):
        s = src / name
        if s.exists():
            shutil.copy2(s, dest / name)
            copied.append(dest / name)
    return copied
