"""Case lookup and formatting for CLI / agent retrieval."""

from __future__ import annotations

import json
import re
from typing import Optional

_NEUTRAL_CITATION_RE = re.compile(
    r"\b(\d{4})\s+([A-Za-z]{2,10})\s+(\d{1,5})\b"
)


def normalize_canlii_ref(ref: str) -> str:
    """Normalise a neutral citation for database lookup."""
    raw = (ref or "").strip()
    raw = re.sub(r"\s+", " ", raw)
    m = _NEUTRAL_CITATION_RE.search(raw)
    if m:
        return f"{m.group(1)} {m.group(2).upper()} {m.group(3)}"
    parts = raw.split()
    if len(parts) >= 3 and parts[1].isalpha():
        return f"{parts[0]} {parts[1].upper()} {parts[2]}"
    return raw


def citation_lookup_variants(ref: str) -> list[str]:
    """Return normalised citation forms to try for lookup (deduplicated)."""
    primary = normalize_canlii_ref(ref)
    variants = [primary]
    m = _NEUTRAL_CITATION_RE.search(ref or "")
    if m:
        year, court, num = m.group(1), m.group(2).upper(), m.group(3)
        variants.append(f"{year} {court} {num}")
        if court.endswith("C"):
            variants.append(f"{year} {court[:-1]} {num}")
    seen: set[str] = set()
    out: list[str] = []
    for v in variants:
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


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


def format_case_markdown(case: dict, *, store: Optional[str] = None) -> str:
    """Render a case as Markdown with YAML front matter and paragraph body."""
    ref = case.get("canlii_ref") or "UNKNOWN"
    meta: dict[str, object] = {
        "canlii_ref": ref,
        "neutral_citation": case.get("neutral_citation"),
        "reporter_citation": case.get("reporter_citation"),
        "court": case.get("court"),
        "court_year": case.get("court_year"),
        "decided_date": case.get("decided_date"),
        "corpus": case.get("corpus"),
        "is_headnote_only": bool(case.get("is_headnote_only")),
        "is_criminal": case.get("is_criminal"),
        "exclusion_reason": case.get("exclusion_reason"),
        "source_url": case.get("source_url"),
    }
    if store:
        meta["store"] = store
    judges = case.get("judges")
    if judges:
        meta["judges"] = judges

    fm_lines = ["---"]
    for key, val in meta.items():
        if val is None or val == "":
            continue
        if key == "judges":
            fm_lines.append(
                f"judges: {json.dumps(val, ensure_ascii=False)}"
            )
        elif isinstance(val, bool):
            fm_lines.append(f"{key}: {'true' if val else 'false'}")
        elif isinstance(val, int):
            fm_lines.append(f"{key}: {val}")
        else:
            escaped = str(val).replace("\\", "\\\\").replace('"', '\\"')
            fm_lines.append(f'{key}: "{escaped}"')
    fm_lines.append("---")

    body: list[str] = [fm_lines[0]]
    body.extend(fm_lines[1:])
    body.append("")
    body.append(f"# {ref}")
    body.append("")
    court = case.get("court") or "—"
    date = case.get("decided_date") or "—"
    body.append(f"*{court}* · {date}")
    body.append("")

    for p in case.get("paragraphs") or []:
        num = p.get("paragraph_num")
        heading = p.get("heading")
        if heading:
            body.append(f"## {heading}")
            body.append("")
        prefix = f"**[{num}]** " if num is not None else ""
        text = (p.get("text") or "").strip()
        if text:
            body.append(prefix + text)
            body.append("")

    return "\n".join(body).rstrip() + "\n"


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
