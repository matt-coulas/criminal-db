"""Detailed curation QA reports for human review."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .overrides import Overrides, load_overrides
from .rules import CurationDecision, classify_case, court_code_from_ref

if TYPE_CHECKING:
    from ..db.operations import Database
    from ..db.router import DatabaseRouter


def is_borderline_excluded(decision: CurationDecision) -> bool:
    """Likely false negative: mixed court but no keyword match."""
    return (
        not decision.is_criminal
        and decision.reason.endswith(":no_criminal_signals")
    )


def is_borderline_included(decision: CurationDecision) -> bool:
    """Likely false positive: included on vocabulary only, no criminal court."""
    return decision.is_criminal and decision.reason == "content:criminal_law"


@dataclass
class CurationCaseRow:
    canlii_ref: str
    court: Optional[str]
    court_code: Optional[str]
    decided_date: Optional[str]
    is_criminal: bool
    reason: str
    previous_is_criminal: Optional[bool]
    previous_reason: Optional[str]
    borderline: bool
    borderline_kind: Optional[str] = None  # "excluded" | "included"

    def to_dict(self) -> dict[str, Any]:
        return {
            "canlii_ref": self.canlii_ref,
            "court": self.court,
            "court_code": self.court_code,
            "decided_date": self.decided_date,
            "is_criminal": self.is_criminal,
            "reason": self.reason,
            "previous_is_criminal": self.previous_is_criminal,
            "previous_reason": self.previous_reason,
            "borderline": self.borderline,
            "borderline_kind": self.borderline_kind,
            "status_changed": (
                self.previous_is_criminal is not None
                and self.previous_is_criminal != self.is_criminal
            ),
        }


@dataclass
class StoreQAReport:
    store: str
    total: int = 0
    criminal: int = 0
    excluded: int = 0
    borderline_excluded: int = 0
    borderline_included: int = 0
    status_changed: int = 0
    excluded_cases: list[CurationCaseRow] = field(default_factory=list)
    borderline_cases: list[CurationCaseRow] = field(default_factory=list)
    status_changes: list[CurationCaseRow] = field(default_factory=list)
    override_include: list[str] = field(default_factory=list)
    override_exclude: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "store": self.store,
            "total": self.total,
            "criminal": self.criminal,
            "excluded": self.excluded,
            "borderline_excluded": self.borderline_excluded,
            "borderline_included": self.borderline_included,
            "status_changed": self.status_changed,
            "excluded_cases": [r.to_dict() for r in self.excluded_cases],
            "borderline_cases": [r.to_dict() for r in self.borderline_cases],
            "status_changes": [r.to_dict() for r in self.status_changes],
            "override_include": self.override_include,
            "override_exclude": self.override_exclude,
        }


def audit_database(
    db: "Database",
    *,
    store: str = "single",
    overrides: Optional[Overrides] = None,
    apply: bool = True,
) -> StoreQAReport:
    """Classify every case and build a QA report; optionally write flags to DB."""
    overrides = overrides or load_overrides()
    report = StoreQAReport(store=store)
    report.override_include = sorted(overrides.normalised().include)
    report.override_exclude = sorted(overrides.normalised().exclude)

    rows = db.conn.execute(
        "SELECT id, canlii_ref, court, decided_date, is_criminal, exclusion_reason "
        "FROM cases ORDER BY canlii_ref"
    ).fetchall()

    for row in rows:
        case_id = int(row["id"])
        paragraphs = [
            dict(p)
            for p in db.conn.execute(
                "SELECT paragraph_num, heading, text, is_headnote, is_ratio "
                "FROM paragraphs WHERE case_id = ? "
                "ORDER BY COALESCE(paragraph_num, id)",
                (case_id,),
            )
        ]
        meta = {
            "canlii_ref": row["canlii_ref"],
            "court": row["court"],
            "decided_date": row["decided_date"],
        }
        decision = classify_case(meta, paragraphs, overrides=overrides)
        prev_criminal = bool(row["is_criminal"])
        prev_reason = row["exclusion_reason"]

        b_ex = is_borderline_excluded(decision)
        b_in = is_borderline_included(decision)
        borderline = b_ex or b_in
        b_kind: Optional[str] = None
        if b_ex:
            b_kind = "excluded"
        elif b_in:
            b_kind = "included"

        entry = CurationCaseRow(
            canlii_ref=str(row["canlii_ref"]),
            court=row["court"],
            court_code=court_code_from_ref(str(row["canlii_ref"])),
            decided_date=row["decided_date"],
            is_criminal=decision.is_criminal,
            reason=decision.reason,
            previous_is_criminal=prev_criminal,
            previous_reason=prev_reason,
            borderline=borderline,
            borderline_kind=b_kind,
        )
        report.total += 1
        if decision.is_criminal:
            report.criminal += 1
        else:
            report.excluded += 1
            report.excluded_cases.append(entry)
        if borderline:
            report.borderline_cases.append(entry)
            if b_ex:
                report.borderline_excluded += 1
            if b_in:
                report.borderline_included += 1
        if prev_criminal != decision.is_criminal:
            report.status_changed += 1
            report.status_changes.append(entry)

        if apply:
            db.set_case_curation(
                case_id,
                is_criminal=decision.is_criminal,
                exclusion_reason=None if decision.is_criminal else decision.reason,
            )

    return report


def audit_router(
    router: "DatabaseRouter",
    *,
    apply: bool = True,
    overrides: Optional[Overrides] = None,
) -> dict[str, Any]:
    """QA report for both case stores."""
    overrides = overrides or load_overrides()
    stores: dict[str, Any] = {}
    totals = {
        "total": 0,
        "criminal": 0,
        "excluded": 0,
        "borderline_excluded": 0,
        "borderline_included": 0,
        "status_changed": 0,
    }
    for store in ("fulltext", "headnotes"):
        rep = audit_database(
            router._db(store),  # noqa: SLF001 — router facade
            store=store,
            overrides=overrides,
            apply=apply,
        )
        stores[store] = rep.to_dict()
        for key in totals:
            totals[key] += getattr(rep, key)
    return {
        "stores": stores,
        "total": totals,
        "override_include": sorted(overrides.normalised().include),
        "override_exclude": sorted(overrides.normalised().exclude),
        "applied": apply,
    }
