"""Apply curation decisions to SQLite case rows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .overrides import Overrides, load_overrides
from .rules import classify_case

if TYPE_CHECKING:
    from ..db.operations import Database


@dataclass
class CurationReport:
    criminal: int = 0
    excluded: int = 0
    total: int = 0
    samples: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "criminal": self.criminal,
            "excluded": self.excluded,
            "total": self.total,
            "samples": self.samples,
        }


def curate_database(
    db: "Database",
    *,
    overrides: Optional[Overrides] = None,
    max_samples: int = 20,
) -> CurationReport:
    """Re-classify every case in one database."""
    overrides = overrides or load_overrides()
    report = CurationReport()
    rows = db.conn.execute(
        "SELECT id, canlii_ref, court, court_year, decided_date, judges, "
        "corpus, is_headnote_only, source_url FROM cases"
    ).fetchall()

    for row in rows:
        case_id = int(row["id"])
        paragraphs = [
            dict(p)
            for p in db.conn.execute(
                "SELECT paragraph_num, heading, text, is_headnote, is_ratio "
                "FROM paragraphs WHERE case_id = ? ORDER BY COALESCE(paragraph_num, id)",
                (case_id,),
            )
        ]
        meta = {
            "canlii_ref": row["canlii_ref"],
            "court": row["court"],
            "court_year": row["court_year"],
            "decided_date": row["decided_date"],
            "corpus": row["corpus"],
        }
        decision = classify_case(meta, paragraphs, overrides=overrides)
        db.set_case_curation(
            case_id,
            is_criminal=decision.is_criminal,
            exclusion_reason=None if decision.is_criminal else decision.reason,
        )
        report.total += 1
        if decision.is_criminal:
            report.criminal += 1
        else:
            report.excluded += 1
            if len(report.samples) < max_samples:
                report.samples.append(
                    {
                        "canlii_ref": row["canlii_ref"],
                        "reason": decision.reason,
                    }
                )
    return report
