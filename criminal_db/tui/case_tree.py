"""Court → year → case tree for the case browser screen."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from ..db.router import DatabaseRouter
from ..retrieval import format_case_text, normalize_canlii_ref

_TITLE_FROM_LEAD = re.compile(
    r"(R\.?\s*(?:v\.|c\.)\s+[^\n.;]{3,80}|"
    r"Her Majesty(?:\s+the\s+Queen)?\s+v\.?\s+[^\n.;]{3,80})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CaseBrowserEntry:
    canlii_ref: str
    neutral_citation: Optional[str]
    court: str
    court_year: int
    short_title: str
    store: str


@dataclass(frozen=True)
class CaseBrowserNode:
    """One selectable row in a column."""

    label: str
    court: Optional[str] = None
    year: Optional[int] = None
    entry: Optional[CaseBrowserEntry] = None


def short_title_from_fields(
    *,
    canlii_ref: str,
    neutral_citation: Optional[str],
    heading: Optional[str],
    lead_text: Optional[str],
) -> str:
    if heading and heading.strip():
        text = heading.strip()
        return text if len(text) <= 72 else text[:69] + "..."
    lead = (lead_text or "").strip().replace("\n", " ")
    if lead:
        m = _TITLE_FROM_LEAD.search(lead)
        if m:
            title = m.group(0).strip()
            return title if len(title) <= 72 else title[:69] + "..."
        return lead if len(lead) <= 72 else lead[:69] + "..."
    return (neutral_citation or canlii_ref).strip()


def load_browser_entries(
    router: DatabaseRouter,
    *,
    criminal_only: bool = True,
) -> list[CaseBrowserEntry]:
    entries: list[CaseBrowserEntry] = []
    for row in router.list_browser_cases(criminal_only=criminal_only):
        ref = row["canlii_ref"]
        entries.append(
            CaseBrowserEntry(
                canlii_ref=ref,
                neutral_citation=row.get("neutral_citation"),
                court=row["court"] or "UNKNOWN",
                court_year=int(row["court_year"] or 0),
                short_title=short_title_from_fields(
                    canlii_ref=ref,
                    neutral_citation=row.get("neutral_citation"),
                    heading=row.get("heading"),
                    lead_text=row.get("lead_text"),
                ),
                store=row.get("store") or "fulltext",
            )
        )
    return sorted(
        entries,
        key=lambda e: (e.court, -e.court_year, e.canlii_ref),
    )


def courts_from_entries(entries: list[CaseBrowserEntry]) -> list[str]:
    return sorted({e.court for e in entries})


def years_for_court(entries: list[CaseBrowserEntry], court: str) -> list[int]:
    years = {e.court_year for e in entries if e.court == court and e.court_year}
    return sorted(years, reverse=True)


def cases_for_court_year(
    entries: list[CaseBrowserEntry], court: str, year: int
) -> list[CaseBrowserEntry]:
    return [e for e in entries if e.court == court and e.court_year == year]


def case_label(entry: CaseBrowserEntry) -> str:
    cite = entry.neutral_citation or entry.canlii_ref
    return f"{entry.short_title} · {cite}"


def load_case_full_text(
    router: DatabaseRouter, entry: CaseBrowserEntry
) -> str:
    result = router.get_case(normalize_canlii_ref(entry.canlii_ref))
    if result is None:
        return f"(case not found: {entry.canlii_ref})"
    case, store = result
    return format_case_text(case, store=store)
