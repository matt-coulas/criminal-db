"""Cross-corpus search (cases + statutes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from . import config
from .db import DatabaseRouter
from .db.operations import SearchResult
from .statutes.db import StatuteSearchResult, StatutesDatabase

HitKind = Literal["case", "statute"]


@dataclass
class UnifiedSearchHit:
    kind: HitKind
    score: float
    case: Optional[SearchResult] = None
    statute: Optional[StatuteSearchResult] = None

    def to_dict(self) -> dict:
        if self.kind == "case" and self.case:
            return {
                "kind": "case",
                "score": self.score,
                "canlii_ref": self.case.canlii_ref,
                "court": self.case.court,
                "paragraph_num": self.case.paragraph_num,
                "heading": self.case.heading,
                "text": self.case.text,
                "store": self.case.store,
            }
        if self.kind == "statute" and self.statute:
            return {
                "kind": "statute",
                "score": self.score,
                "section": self.statute.section_number,
                "heading": self.statute.heading,
                "text": self.statute.text,
            }
        return {"kind": self.kind, "score": self.score}


def _minmax_norm(scores: list[float]) -> dict[int, float]:
    if not scores:
        return {}
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return {i: 1.0 for i in range(len(scores))}
    return {i: (scores[i] - lo) / (hi - lo) for i in range(len(scores))}


def search_all_fts(
    query: str,
    *,
    router: DatabaseRouter,
    statutes: StatutesDatabase,
    limit: int = 10,
    offset: int = 0,
    court: Optional[str] = None,
    year: Optional[int] = None,
    corpus: Optional[str] = None,
    criminal_only: bool = True,
) -> list[UnifiedSearchHit]:
    """Merge case and statute FTS hits with min-max normalised scores."""
    per = max(limit + offset, limit) * 2
    case_hits = router.search_fts(
        query,
        limit=per,
        court=court,
        year=year,
        corpus=corpus,
        criminal_only=criminal_only,
    )
    stat_hits = statutes.search_fts(query, limit=per)
    case_norm = _minmax_norm([h.score for h in case_hits])
    stat_norm = _minmax_norm([h.score for h in stat_hits])
    merged: list[UnifiedSearchHit] = []
    for i, h in enumerate(case_hits):
        merged.append(
            UnifiedSearchHit(kind="case", score=case_norm.get(i, h.score), case=h)
        )
    for i, h in enumerate(stat_hits):
        merged.append(
            UnifiedSearchHit(kind="statute", score=stat_norm.get(i, h.score), statute=h)
        )
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[offset : offset + limit]


def search_all_hybrid(
    query: str,
    vector: Sequence[float],
    *,
    router: DatabaseRouter,
    statutes: StatutesDatabase,
    limit: int = 10,
    offset: int = 0,
    court: Optional[str] = None,
    year: Optional[int] = None,
    corpus: Optional[str] = None,
    criminal_only: bool = True,
    fts_weight: float = config.HYBRID_FTS_WEIGHT,
) -> list[UnifiedSearchHit]:
    per = max(limit + offset, limit) * 2
    case_hits = router.search_hybrid(
        query,
        vector,
        limit=per,
        court=court,
        year=year,
        corpus=corpus,
        criminal_only=criminal_only,
        fts_weight=fts_weight,
    )
    stat_hits = statutes.search_hybrid(
        query, vector, limit=per, fts_weight=fts_weight
    )
    case_norm = _minmax_norm([h.score for h in case_hits])
    stat_norm = _minmax_norm([h.score for h in stat_hits])
    merged: list[UnifiedSearchHit] = []
    for i, h in enumerate(case_hits):
        merged.append(
            UnifiedSearchHit(kind="case", score=case_norm.get(i, h.score), case=h)
        )
    for i, h in enumerate(stat_hits):
        merged.append(
            UnifiedSearchHit(kind="statute", score=stat_norm.get(i, h.score), statute=h)
        )
    merged.sort(key=lambda x: x.score, reverse=True)
    return merged[offset : offset + limit]
