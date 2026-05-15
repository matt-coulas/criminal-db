"""Catalog and database consistency checks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Optional

from . import config
from .catalog.manifest import Manifest
from .db import Database, DatabaseRouter
from .db.schema import init_db
from .retrieval import normalize_canlii_ref

IssueLevel = Literal["error", "warning", "info"]


@dataclass
class VerifyIssue:
    level: IssueLevel
    code: str
    message: str
    detail: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


@dataclass
class VerifyReport:
    ok: bool = True
    issues: list[VerifyIssue] = field(default_factory=list)

    def add(self, level: IssueLevel, code: str, message: str, **detail: Any) -> None:
        issue = VerifyIssue(
            level=level,
            code=code,
            message=message,
            detail=detail or None,
        )
        self.issues.append(issue)
        if level == "error":
            self.ok = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": sum(1 for i in self.issues if i.level == "error"),
            "warning_count": sum(1 for i in self.issues if i.level == "warning"),
            "issues": [i.to_dict() for i in self.issues],
        }


def _check_db_file(path: Path, report: VerifyReport, *, label: str) -> Optional[Database]:
    if not path.exists():
        report.add("warning", "db_missing", f"{label} database not found", path=str(path))
        return None
    try:
        return Database(path, auto_init=False)
    except Exception as exc:
        report.add("error", "db_open_failed", f"Cannot open {label} database", path=str(path), error=str(exc))
        return None


def _fts_paragraph_drift(db: Database, report: VerifyReport, *, label: str) -> None:
    para_count = db.paragraph_count()
    try:
        fts_count = int(
            db.conn.execute("SELECT COUNT(*) FROM paragraphs_fts").fetchone()[0]
        )
    except sqlite3.Error as exc:
        report.add("error", "fts_check_failed", f"{label}: FTS count failed", error=str(exc))
        return
    if para_count != fts_count:
        report.add(
            "error",
            "fts_drift",
            f"{label}: paragraph count ({para_count}) != FTS rows ({fts_count})",
            store=label,
            paragraphs=para_count,
            fts_rows=fts_count,
        )


def verify_catalog_and_databases(
    *,
    manifest_path: Optional[Path] = None,
    fulltext_path: Optional[Path] = None,
    headnotes_path: Optional[Path] = None,
) -> VerifyReport:
    """Cross-check manifest entries against SQLite case stores."""
    report = VerifyReport()
    mpath = manifest_path or config.MANIFEST_PATH
    if not mpath.exists():
        report.add("info", "manifest_missing", "No manifest file (run criminal-db init)")
        return report

    manifest = Manifest.load(mpath)
    ft_db = _check_db_file(fulltext_path or config.FULLTEXT_DB, report, label="fulltext")
    hn_db = _check_db_file(headnotes_path or config.HEADNOTES_DB, report, label="headnotes")

    store_db: dict[str, Optional[Database]] = {
        "fulltext": ft_db,
        "headnotes": hn_db,
    }

    for key, entry in manifest.entries.items():
        if entry.status != "ok":
            continue
        if not entry.canlii_ref:
            report.add(
                "warning",
                "manifest_no_ref",
                f"ok entry missing canlii_ref: {key}",
                source_path=key,
            )
            continue
        store = entry.store or "fulltext"
        db = store_db.get(store)
        if db is None:
            continue
        ref = normalize_canlii_ref(entry.canlii_ref)
        case = db.get_case(ref)
        if case is None:
            report.add(
                "error",
                "manifest_case_missing",
                f"Manifest ok but case not in {store} DB: {ref}",
                source_path=key,
                canlii_ref=ref,
                store=store,
            )
            continue
        if entry.case_id is not None and int(case["id"]) != int(entry.case_id):
            report.add(
                "warning",
                "manifest_case_id_mismatch",
                f"Manifest case_id {entry.case_id} != DB id {case['id']} for {ref}",
                source_path=key,
                canlii_ref=ref,
            )
        if not case.get("paragraphs"):
            report.add(
                "warning",
                "case_no_paragraphs",
                f"Case {ref} has no paragraphs",
                canlii_ref=ref,
                store=store,
            )

    for label, db in (("fulltext", ft_db), ("headnotes", hn_db)):
        if db is None:
            continue
        _fts_paragraph_drift(db, report, label=label)
        if db.has_vec:
            missing = len(db.paragraphs_missing_embeddings())
            if missing:
                report.add(
                    "info",
                    "embeddings_incomplete",
                    f"{label}: {missing} paragraph(s) without embeddings",
                    store=label,
                    missing=missing,
                )
        db.close()

    return report


def verify_statutes_db(path: Optional[Path] = None) -> VerifyReport:
    """Check statutes database FTS consistency."""
    from .statutes.db import StatutesDatabase

    report = VerifyReport()
    db_path = path or config.STATUTES_DB
    if not db_path.exists():
        report.add("warning", "statutes_db_missing", "Statutes database not found", path=str(db_path))
        return report
    db = StatutesDatabase(db_path, auto_init=False)
    try:
        sec_count = db.section_count()
        fts_count = int(db.conn.execute("SELECT COUNT(*) FROM sections_fts").fetchone()[0])
        if sec_count != fts_count:
            report.add(
                "error",
                "statutes_fts_drift",
                f"Section count ({sec_count}) != FTS rows ({fts_count})",
                sections=sec_count,
                fts_rows=fts_count,
            )
        if db.has_vec:
            missing = len(db.sections_missing_embeddings())
            if missing:
                report.add(
                    "info",
                    "statute_embeddings_incomplete",
                    f"{missing} section(s) without embeddings",
                    missing=missing,
                )
    finally:
        db.close()
    return report


def run_verify(*, include_statutes: bool = True) -> VerifyReport:
    """Run all verification passes and merge results."""
    if not config.FULLTEXT_DB.parent.exists():
        init_db(config.FULLTEXT_DB)
    main = verify_catalog_and_databases()
    if not include_statutes:
        return main
    stat = verify_statutes_db()
    main.issues.extend(stat.issues)
    if not stat.ok:
        main.ok = False
    return main
