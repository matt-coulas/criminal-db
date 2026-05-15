"""Import HTML or PDF case files from disk (no CanLII scraping)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Callable, Optional

from .. import config
from ..curation.rules import classify_case
from ..db.router import DatabaseRouter
from ..harvester.parser import CanLIIParser, export_case_to_json
from .ingest import IngestReport, _infer_corpus_hint, _sha256_file, ingest_paths
from .manifest import CatalogEntry, Manifest, SourceType, ensure_catalog_dirs
from .pdf_extract import pdf_to_canlii_html

_HTML_SUFFIXES = {".html", ".htm"}
_PDF_SUFFIX = ".pdf"


def collect_import_files(paths: list[Path]) -> list[tuple[Path, SourceType]]:
    """Expand *paths* into ``(file, source_type)`` pairs."""
    found: list[tuple[Path, SourceType]] = []
    for root in paths:
        p = root.resolve()
        if p.is_dir():
            for suffix, stype in (
                ("*.html", "html"),
                ("*.htm", "html"),
                ("*.pdf", "pdf"),
            ):
                for f in sorted(p.rglob(suffix)):
                    if f.name != "_index.html":
                        found.append((f, stype))  # type: ignore[arg-type]
        elif p.suffix.lower() in _HTML_SUFFIXES:
            found.append((p, "html"))
        elif p.suffix.lower() == _PDF_SUFFIX:
            found.append((p, "pdf"))
    return found


def _import_subdir(source_type: SourceType) -> Path:
    return config.IMPORT_DIR / source_type


def _is_under_import_dir(path: Path) -> bool:
    try:
        path.resolve().relative_to(config.IMPORT_DIR.resolve())
        return True
    except ValueError:
        return False


def stage_import_file(path: Path, source_type: SourceType) -> Path:
    """Copy *path* into ``data/import/{html|pdf}/`` unless already staged."""
    path = path.resolve()
    if _is_under_import_dir(path):
        return path

    dest_dir = _import_subdir(source_type)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists() and dest.resolve() != path:
        stem = path.stem
        suffix = path.suffix
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:8]
        dest = dest_dir / f"{stem}_{digest}{suffix}"
    if not dest.exists():
        shutil.copy2(path, dest)
    return dest.resolve()


def _process_parsed_case(
    entry: CatalogEntry,
    case,
    *,
    router: DatabaseRouter,
    criminal_only: bool,
    now: str,
    report: IngestReport,
    write_md: bool = True,
    unknown_citation_message: str = "no citation detected",
) -> None:
    """Apply curation, store, and update *entry* / *report* counters."""
    if case.canlii_ref == "UNKNOWN":
        entry.status = "skipped"
        entry.parse_error = unknown_citation_message
        report.skipped += 1
        return

    payload = export_case_to_json(case)
    decision = classify_case(payload["meta"], payload.get("paragraphs") or [])
    if criminal_only and not decision.is_criminal:
        entry.status = "excluded"
        entry.canlii_ref = case.canlii_ref
        entry.parse_error = decision.reason
        report.excluded += 1
        return

    case_id, store = router.store_case(payload, write_md=write_md)
    entry.status = "ok"
    entry.canlii_ref = case.canlii_ref
    entry.corpus = case.corpus
    entry.case_id = case_id
    entry.store = store
    entry.source_url = case.source_url
    entry.parsed_at = now
    report.ok += 1


def _ingest_one_pdf(
    path: Path,
    *,
    router: DatabaseRouter,
    manifest: Manifest,
    force: bool,
    criminal_only: bool,
    write_md: bool,
    now: str,
    report: IngestReport,
    on_progress: Optional[Callable[[CatalogEntry], None]],
    original_filename: str,
) -> None:
    staged = stage_import_file(path, "pdf")
    key = Manifest.entry_key(staged)
    digest = _sha256_file(staged)
    existing = manifest.get(staged)

    if (
        not force
        and existing
        and existing.status == "ok"
        and existing.sha256 == digest
    ):
        report.skipped += 1
        report.entries.append(existing)
        if on_progress:
            on_progress(existing)
        return

    entry = CatalogEntry(
        source_path=key,
        status="pending",
        sha256=digest,
        fetched_at=existing.fetched_at if existing else now,
        source_type="pdf",
        original_filename=original_filename,
    )
    try:
        html, _citation_hint = pdf_to_canlii_html(staged)
        case = CanLIIParser(html, source_url=staged.resolve().as_uri()).parse()
        hint = _infer_corpus_hint(staged)
        if hint and case.corpus != hint:
            case.corpus = hint
            case.is_headnote_only = 1 if hint == "headnote" else 0
        _process_parsed_case(
            entry,
            case,
            router=router,
            criminal_only=criminal_only,
            now=now,
            report=report,
            write_md=write_md,
            unknown_citation_message=(
                "no citation detected; manual review needed (PDF import)"
            ),
        )
    except ImportError as exc:
        entry.status = "failed"
        entry.parse_error = str(exc)
        report.failed += 1
    except Exception as exc:
        entry.status = "failed"
        entry.parse_error = str(exc)
        report.failed += 1

    manifest.upsert(entry)
    report.entries.append(entry)
    if on_progress:
        on_progress(entry)


def import_paths(
    paths: list[Path],
    *,
    router: DatabaseRouter,
    manifest: Optional[Manifest] = None,
    force: bool = False,
    criminal_only: bool = False,
    write_md: bool = True,
    on_progress: Optional[Callable[[CatalogEntry], None]] = None,
) -> IngestReport:
    """Stage and import HTML/PDF files; update the catalog manifest."""
    from datetime import datetime, timezone

    ensure_catalog_dirs()
    manifest = manifest or Manifest.load()
    items = collect_import_files(paths)
    if not items:
        manifest.save()
        return IngestReport()

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    html_paths: list[Path] = []
    html_originals: dict[str, str] = {}
    pdf_items: list[tuple[Path, str]] = []

    for path, source_type in items:
        original = path.name
        staged = stage_import_file(path, source_type)
        if source_type == "html":
            html_paths.append(staged)
            html_originals[Manifest.entry_key(staged)] = original
        else:
            pdf_items.append((staged, original))

    report = IngestReport()

    if html_paths:
        html_report = ingest_paths(
            html_paths,
            router=router,
            manifest=manifest,
            force=force,
            criminal_only=criminal_only,
            write_md=write_md,
            on_progress=on_progress,
            source_type="html",
        )
        for entry in html_report.entries:
            entry.original_filename = html_originals.get(
                entry.source_path, entry.original_filename or Path(entry.source_path).name
            )
            manifest.upsert(entry)
        report.ok += html_report.ok
        report.skipped += html_report.skipped
        report.excluded += html_report.excluded
        report.failed += html_report.failed
        report.entries.extend(html_report.entries)

    for staged, original in pdf_items:
        _ingest_one_pdf(
            staged,
            router=router,
            manifest=manifest,
            force=force,
            criminal_only=criminal_only,
            write_md=write_md,
            now=now,
            report=report,
            on_progress=on_progress,
            original_filename=original,
        )

    manifest.save()
    return report
