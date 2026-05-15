"""Parse HTML from disk, route to databases, and update the catalog."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from ..curation.rules import classify_case
from ..db.router import DatabaseRouter
from ..harvester.parser import CanLIIParser, export_case_to_json
from .manifest import CatalogEntry, Manifest, ensure_catalog_dirs


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _infer_corpus_hint(path: Path) -> Optional[str]:
    """Guess corpus from ``data/cases/{fulltext,headnotes}/`` layout."""
    parts = {p.lower() for p in path.parts}
    if "headnotes" in parts:
        return "headnote"
    if "fulltext" in parts:
        return "fulltext"
    return None


def collect_html_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in paths:
        p = root.resolve()
        if p.is_dir():
            files.extend(sorted(p.rglob("*.html")))
        elif p.suffix.lower() == ".html":
            files.append(p)
    # Stable order, skip listing index pages by convention.
    return [f for f in files if f.name != "_index.html"]


@dataclass
class IngestReport:
    ok: int = 0
    skipped: int = 0
    excluded: int = 0
    failed: int = 0
    entries: list[CatalogEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "excluded": self.excluded,
            "failed": self.failed,
            "entries": [e.to_dict() for e in self.entries],
        }


def ingest_paths(
    paths: list[Path],
    *,
    router: DatabaseRouter,
    manifest: Optional[Manifest] = None,
    force: bool = False,
    criminal_only: bool = False,
    on_progress: Optional[Callable[[CatalogEntry], None]] = None,
) -> IngestReport:
    """Parse HTML files, store via ``router``, and update ``manifest``."""
    ensure_catalog_dirs()
    manifest = manifest or Manifest.load()
    report = IngestReport()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for path in collect_html_files(paths):
        key = Manifest.entry_key(path)
        digest = _sha256_file(path)
        existing = manifest.get(path)

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
            continue

        entry = CatalogEntry(
            source_path=key,
            status="pending",
            sha256=digest,
            fetched_at=existing.fetched_at if existing else None,
        )
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            case = CanLIIParser(
                html, source_url=path.resolve().as_uri()
            ).parse()
            hint = _infer_corpus_hint(path)
            if hint and case.corpus != hint:
                # Prefer directory layout when the parser is ambiguous.
                case.corpus = hint
                case.is_headnote_only = 1 if hint == "headnote" else 0

            if case.canlii_ref == "UNKNOWN":
                entry.status = "skipped"
                entry.parse_error = "no citation detected"
                report.skipped += 1
            else:
                payload = export_case_to_json(case)
                decision = classify_case(
                    payload["meta"], payload.get("paragraphs") or []
                )
                if criminal_only and not decision.is_criminal:
                    entry.status = "excluded"
                    entry.canlii_ref = case.canlii_ref
                    entry.parse_error = decision.reason
                    report.excluded += 1
                else:
                    case_id, store = router.store_case(payload)
                    entry.status = "ok"
                    entry.canlii_ref = case.canlii_ref
                    entry.corpus = case.corpus
                    entry.case_id = case_id
                    entry.store = store
                    entry.source_url = case.source_url
                    entry.parsed_at = now
                    report.ok += 1
        except Exception as exc:
            entry.status = "failed"
            entry.parse_error = str(exc)
            report.failed += 1

        manifest.upsert(entry)
        report.entries.append(entry)
        if on_progress:
            on_progress(entry)

    manifest.save()
    return report
