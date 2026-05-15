"""Dry-run HTML validation for offline case files (no database writes)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .catalog.ingest import collect_html_files
from .curation.rules import classify_case
from .harvester.parser import CanLIIParser, export_case_to_json

IssueLevel = Literal["error", "warn"]


@dataclass
class ValidationIssue:
    level: IssueLevel
    code: str
    message: str

    def to_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message}


@dataclass
class FileValidation:
    path: str
    canlii_ref: str
    corpus: str
    paragraph_count: int
    criminal: bool | None = None
    curation_reason: str | None = None
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "canlii_ref": self.canlii_ref,
            "corpus": self.corpus,
            "paragraph_count": self.paragraph_count,
            "criminal": self.criminal,
            "curation_reason": self.curation_reason,
            "ok": self.ok,
            "issues": [i.to_dict() for i in self.issues],
        }


def _check_case(path: Path, html: str) -> FileValidation:
    rel = str(path)
    issues: list[ValidationIssue] = []
    try:
        case = CanLIIParser(html, source_url=path.resolve().as_uri()).parse()
    except Exception as exc:
        return FileValidation(
            path=rel,
            canlii_ref="UNKNOWN",
            corpus="",
            paragraph_count=0,
            issues=[
                ValidationIssue("error", "parse_exception", str(exc)),
            ],
        )

    payload = export_case_to_json(case)
    decision = classify_case(payload["meta"], payload.get("paragraphs") or [])

    if case.canlii_ref == "UNKNOWN":
        issues.append(
            ValidationIssue(
                "error",
                "unknown_citation",
                "No neutral citation detected; check title/meta or first page text",
            )
        )
    if not case.paragraphs:
        issues.append(
            ValidationIssue("error", "no_paragraphs", "Parser found zero paragraphs")
        )

    nums = [p.paragraph_num for p in case.paragraphs if p.paragraph_num is not None]
    if len(nums) != len(set(nums)):
        issues.append(
            ValidationIssue("warn", "duplicate_paragraph_nums", "Duplicate paragraph numbers")
        )
    if case.corpus == "headnote" and nums:
        issues.append(
            ValidationIssue(
                "warn",
                "headnote_with_numbers",
                "Classified as headnote but paragraph numbers present",
            )
        )
    if case.corpus == "fulltext" and not nums and case.paragraphs:
        issues.append(
            ValidationIssue(
                "warn",
                "fulltext_without_numbers",
                "Fulltext corpus but no paragraph numbers extracted",
            )
        )
    if case.corpus == "fulltext" and not case.judges:
        issues.append(
            ValidationIssue("warn", "no_judges", "No judges extracted from panel/coram")
        )
    short = [p for p in case.paragraphs if len((p.text or "").split()) < 8]
    if len(short) > max(1, len(case.paragraphs) // 2):
        issues.append(
            ValidationIssue(
                "warn",
                "many_short_paragraphs",
                f"{len(short)} paragraphs under 8 words",
            )
        )

    return FileValidation(
        path=rel,
        canlii_ref=case.canlii_ref,
        corpus=case.corpus,
        paragraph_count=len(case.paragraphs),
        criminal=decision.is_criminal,
        curation_reason=decision.reason,
        issues=issues,
    )


def validate_paths(paths: list[Path]) -> list[FileValidation]:
    """Parse HTML files under *paths* and return validation reports (no DB writes)."""
    results: list[FileValidation] = []
    for path in collect_html_files(paths):
        html = path.read_text(encoding="utf-8", errors="replace")
        results.append(_check_case(path, html))
    return results
