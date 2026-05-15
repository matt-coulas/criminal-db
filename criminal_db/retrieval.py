"""Case lookup and formatting for CLI / agent retrieval."""

from __future__ import annotations

from typing import Optional


def normalize_canlii_ref(ref: str) -> str:
    """Normalise a neutral citation for database lookup."""
    parts = ref.split()
    if len(parts) >= 3 and parts[1].isalpha():
        return f"{parts[0]} {parts[1].upper()} {parts[2]}"
    return " ".join(parts)


def format_case_text(case: dict, *, store: Optional[str] = None) -> str:
    """Render a :func:`Database.get_case` dict as plain text."""
    lines = [
        case.get("canlii_ref") or "UNKNOWN",
        f"{case.get('court') or '—'} ({case.get('decided_date') or '—'})",
    ]
    if store:
        lines.append(f"store: {store}")
    if case.get("is_criminal") is not None:
        flag = "yes" if case.get("is_criminal") else "no"
        lines.append(f"criminal: {flag}")
        if case.get("exclusion_reason"):
            lines.append(f"excluded: {case['exclusion_reason']}")
    lines.append("")
    for p in case.get("paragraphs") or []:
        num = p.get("paragraph_num")
        prefix = f"[{num}] " if num is not None else ""
        heading = p.get("heading")
        if heading:
            lines.append(f"## {heading}")
        lines.append(prefix + (p.get("text") or ""))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def case_to_export_json(case: dict, *, store: Optional[str] = None) -> dict:
    """Shape a case row for JSON export."""
    out = {
        "meta": {
            "canlii_ref": case.get("canlii_ref"),
            "neutral_citation": case.get("neutral_citation"),
            "reporter_citation": case.get("reporter_citation"),
            "court": case.get("court"),
            "court_year": case.get("court_year"),
            "decided_date": case.get("decided_date"),
            "judges": case.get("judges"),
            "corpus": case.get("corpus"),
            "is_headnote_only": case.get("is_headnote_only"),
            "is_criminal": case.get("is_criminal"),
            "exclusion_reason": case.get("exclusion_reason"),
            "source_url": case.get("source_url"),
        },
        "paragraphs": case.get("paragraphs") or [],
    }
    if store:
        out["meta"]["store"] = store
    return out
