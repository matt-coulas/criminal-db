"""Heuristic rules for criminal-law case classification."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .overrides import Overrides, load_overrides

# Court codes from neutral citations (must match parser ``_CITATION_RE``).
_CITATION_RE = re.compile(
    r"\b\d{4}\s+"
    r"(SCC|SCR|FCA|FC|TCC|ABCA|BCCA|MBCA|NBCA|NLCA|NSCA|"
    r"ONCA|ONSC|ONCJ|PECA|QCCA|QCCS|QCCQ|SKCA|NWTCA|YKCA|NUCA|"
    r"ABQB|BCSC|MBQB|NBQB|NLSC|NSSC|PESC|SKQB|NWTSC|YKSC|NUCJ)"
    r"\s+\d+\b",
    re.IGNORECASE,
)

# Courts that primarily hear criminal matters (or criminal appeals).
_CRIMINAL_COURT_CODES = frozenset(
    {
        "ONCJ",
        "QCCQ",
        "QCCS",  # criminal division often; title check for mixed
        "NSSC",
        "SKQB",
        "NUCJ",
        "YKSC",
        "NWTSC",
        "ABQB",
        "MBQB",
        "NBQB",
        "NLSC",
        "BCPC",
    }
)

# Appellate / supreme courts: criminal and civil — require title signal.
_MIXED_COURT_CODES = frozenset(
    {
        "SCC",
        "SCR",
        "ONCA",
        "QCCA",
        "ABCA",
        "BCCA",
        "MBCA",
        "NBCA",
        "NLCA",
        "NSCA",
        "PECA",
        "SKCA",
        "NWTCA",
        "YKCA",
        "NUCA",
        "FCA",
        "FC",
        "ONSC",
        "BCSC",
        "QCCS",
    }
)

# Strong criminal title signals (English and French).
_CRIMINAL_TITLE_RE = re.compile(
    r"\b("
    r"R\.?\s*v\.?|"
    r"Her Majesty(?:\s+the\s+Queen)?|"
    r"The Queen|"
    r"Regina|"
    r"R\s+c\.|"
    r"c\.?\s*R\.?"
    r")\b",
    re.IGNORECASE,
)

# Substantive criminal-law vocabulary (used for mixed/general courts).
_CRIMINAL_CONTENT_RE = re.compile(
    r"\b("
    r"Criminal Code|"
    r"the Crown|"
    r"conviction|"
    r"accused|"
    r"voir dire|"
    r"guilty plea|"
    r"indictment|"
    r"Charter"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CurationDecision:
    is_criminal: bool
    reason: str


def court_code_from_ref(canlii_ref: str) -> Optional[str]:
    m = _CITATION_RE.search(canlii_ref or "")
    return m.group(1).upper() if m else None


def _sample_text(meta: dict, paragraphs: list[dict], *, max_chars: int = 8000) -> str:
    chunks: list[str] = [
        meta.get("canlii_ref") or "",
        meta.get("court") or "",
        meta.get("neutral_citation") or "",
        meta.get("reporter_citation") or "",
    ]
    for p in paragraphs:
        if p.get("heading"):
            chunks.append(str(p["heading"]))
        if p.get("text"):
            chunks.append(str(p["text"]))
    blob = " ".join(chunks)
    return blob[:max_chars]


def _has_criminal_signals(text: str) -> bool:
    return bool(
        _CRIMINAL_TITLE_RE.search(text) or _CRIMINAL_CONTENT_RE.search(text)
    )


def classify_case(
    meta: dict,
    paragraphs: Optional[list[dict]] = None,
    *,
    overrides: Optional[Overrides] = None,
) -> CurationDecision:
    """Return whether a parsed case belongs in the criminal-law corpus."""
    overrides = (overrides or load_overrides()).normalised()
    ref = _norm(meta.get("canlii_ref") or "")
    paragraphs = paragraphs or []

    if ref in overrides.exclude:
        return CurationDecision(False, "override:exclude")
    if ref in overrides.include:
        return CurationDecision(True, "override:include")

    code = court_code_from_ref(ref)
    text = _sample_text(meta, paragraphs)
    has_signals = _has_criminal_signals(text)

    if code in _CRIMINAL_COURT_CODES:
        return CurationDecision(True, f"court:{code}")

    if code in _MIXED_COURT_CODES:
        if has_signals:
            return CurationDecision(True, f"court:{code}+content")
        return CurationDecision(False, f"court:{code}:no_criminal_signals")

    if has_signals:
        return CurationDecision(True, "content:criminal_law")

    return CurationDecision(False, "default:not_classified")


def _norm(ref: str) -> str:
    return " ".join(ref.split())
