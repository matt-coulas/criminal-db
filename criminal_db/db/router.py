"""Route cases to headnotes vs fulltext databases and search across both."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Literal, Optional, Sequence, Union

from .. import config
from .operations import Database, SearchResult
from .schema import init_db

PathLike = Union[str, Path]
StoreName = Literal["fulltext", "headnotes"]


def db_path_for_corpus(corpus: str) -> Path:
    """Return the SQLite path for a parsed case corpus label."""
    if corpus == "headnote":
        return config.HEADNOTES_DB
    return config.FULLTEXT_DB


def _merge_ranked(results: list[SearchResult], *, limit: int) -> list[SearchResult]:
    """Min-max normalise scores across stores and return the top ``limit`` hits."""
    if not results:
        return []
    scores = [r.score for r in results]
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        normalised = [replace(r, score=1.0) for r in results]
    else:
        normalised = [
            replace(r, score=(r.score - lo) / (hi - lo)) for r in results
        ]
    normalised.sort(key=lambda r: r.score, reverse=True)
    return normalised[:limit]


class DatabaseRouter:
    """Facade over ``fulltext.db`` and ``headnotes.db``.

    When ``--db`` is not passed on the CLI, commands use this router to store
    cases in the correct database and to search/embed/analyse both.
    """

    def __init__(
        self,
        *,
        fulltext_path: Optional[PathLike] = None,
        headnotes_path: Optional[PathLike] = None,
        auto_init: bool = True,
    ) -> None:
        self.fulltext_path = Path(fulltext_path or config.FULLTEXT_DB)
        self.headnotes_path = Path(headnotes_path or config.HEADNOTES_DB)
        if auto_init:
            init_db(self.fulltext_path)
            init_db(self.headnotes_path)
        self._fulltext: Optional[Database] = None
        self._headnotes: Optional[Database] = None

    def _db(self, store: StoreName) -> Database:
        if store == "fulltext":
            if self._fulltext is None:
                self._fulltext = Database(self.fulltext_path, auto_init=False)
            return self._fulltext
        if self._headnotes is None:
            self._headnotes = Database(self.headnotes_path, auto_init=False)
        return self._headnotes

    def database_for_corpus(self, corpus: str) -> Database:
        store: StoreName = "headnotes" if corpus == "headnote" else "fulltext"
        return self._db(store)

    def store_case(
        self, case_json: dict, *, write_md: bool = True
    ) -> tuple[int, StoreName]:
        """Store a parsed case in the database matching ``meta.corpus``."""
        meta = case_json.get("meta") or {}
        corpus = meta.get("corpus") or "fulltext"
        store: StoreName = "headnotes" if corpus == "headnote" else "fulltext"
        case_id = self._db(store).store_case(case_json, write_md=write_md)
        return case_id, store

    def stores_for_corpus_filter(
        self, corpus: Optional[str]
    ) -> list[tuple[StoreName, Database]]:
        if corpus == "headnote":
            return [("headnotes", self._db("headnotes"))]
        if corpus == "fulltext":
            return [("fulltext", self._db("fulltext"))]
        return [
            ("fulltext", self._db("fulltext")),
            ("headnotes", self._db("headnotes")),
        ]

    def _tag_results(
        self, results: list[SearchResult], *, store: StoreName
    ) -> list[SearchResult]:
        corpus_label = "headnote" if store == "headnotes" else "fulltext"
        return [
            replace(r, store=store, corpus=r.corpus or corpus_label)
            for r in results
        ]

    def search_fts(
        self,
        query: str,
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
        offset: int = 0,
        criminal_only: bool = True,
    ) -> list[SearchResult]:
        per_store = max(limit + offset, limit) * 2
        combined: list[SearchResult] = []
        for store, db in self.stores_for_corpus_filter(corpus):
            hits = db.search_fts(
                query,
                limit=per_store,
                court=court,
                year=year,
                corpus=corpus,
                criminal_only=criminal_only,
            )
            combined.extend(self._tag_results(hits, store=store))
        merged = _merge_ranked(combined, limit=per_store)
        return merged[offset : offset + limit]

    def search_vector(
        self,
        vector: Sequence[float],
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
        offset: int = 0,
        criminal_only: bool = True,
    ) -> list[SearchResult]:
        per_store = max(limit + offset, limit) * 2
        combined: list[SearchResult] = []
        for store, db in self.stores_for_corpus_filter(corpus):
            hits = db.search_vector(
                vector,
                limit=per_store,
                court=court,
                year=year,
                corpus=corpus,
                criminal_only=criminal_only,
            )
            combined.extend(self._tag_results(hits, store=store))
        merged = _merge_ranked(combined, limit=per_store)
        return merged[offset : offset + limit]

    def search_hybrid(
        self,
        query: str,
        vector: Sequence[float],
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
        offset: int = 0,
        criminal_only: bool = True,
        fts_weight: float = config.HYBRID_FTS_WEIGHT,
    ) -> list[SearchResult]:
        per_store = max(limit + offset, limit) * 2
        combined: list[SearchResult] = []
        for store, db in self.stores_for_corpus_filter(corpus):
            hits = db.search_hybrid(
                query,
                vector,
                limit=per_store,
                court=court,
                year=year,
                corpus=corpus,
                criminal_only=criminal_only,
                fts_weight=fts_weight,
            )
            combined.extend(self._tag_results(hits, store=store))
        merged = _merge_ranked(combined, limit=per_store)
        return merged[offset : offset + limit]

    def paragraphs_missing_embeddings(
        self, *, limit: Optional[int] = None
    ) -> list[tuple[int, str, StoreName]]:
        """Return ``(paragraph_id, text, store)`` tuples missing embeddings."""
        out: list[tuple[int, str, StoreName]] = []
        for store in ("fulltext", "headnotes"):
            for pid, text in self._db(store).paragraphs_missing_embeddings():
                out.append((pid, text, store))
                if limit is not None and len(out) >= limit:
                    return out
        return out

    def store_embeddings(
        self,
        items: Sequence[tuple[int, Sequence[float], StoreName]],
    ) -> int:
        by_store: dict[StoreName, list[tuple[int, Sequence[float]]]] = {
            "fulltext": [],
            "headnotes": [],
        }
        for pid, vec, store in items:
            by_store[store].append((pid, vec))
        written = 0
        for store, rows in by_store.items():
            if rows:
                written += self._db(store).store_embeddings(rows)
        return written

    def analyze(self) -> dict[str, Any]:
        """Return statistics for each store and rolled-up totals."""
        stores: dict[str, Any] = {}
        totals = {
            "cases": 0,
            "criminal_cases": 0,
            "excluded_cases": 0,
            "paragraphs": 0,
            "ratio_paragraphs": 0,
            "headnote_paragraphs": 0,
            "embeddings": 0,
        }
        for store in ("fulltext", "headnotes"):
            db = self._db(store)
            stats = {
                "path": str(db.db_path),
                "cases": db.case_count(),
                "criminal_cases": db.criminal_case_count(),
                "excluded_cases": db.excluded_case_count(),
                "paragraphs": db.paragraph_count(),
                "ratio_paragraphs": db.ratio_paragraph_count(),
                "headnote_paragraphs": db.headnote_paragraph_count(),
                "embeddings": db.embedding_count(),
                "by_court": db.court_distribution(),
                "by_year": db.year_distribution(),
            }
            stores[store] = stats
            totals["cases"] += stats["cases"]
            totals["criminal_cases"] += stats["criminal_cases"]
            totals["excluded_cases"] += stats["excluded_cases"]
            totals["paragraphs"] += stats["paragraphs"]
            totals["ratio_paragraphs"] += stats["ratio_paragraphs"]
            totals["headnote_paragraphs"] += stats["headnote_paragraphs"]
            totals["embeddings"] += stats["embeddings"]
        return {"stores": stores, "total": totals}

    def get_case(
        self,
        canlii_ref: str,
        *,
        criminal_only: bool = False,
    ) -> Optional[tuple[dict, StoreName]]:
        from ..retrieval import citation_lookup_variants

        for ref in citation_lookup_variants(canlii_ref):
            for store in ("fulltext", "headnotes"):
                case = self._db(store).get_case(ref)
                if case is None:
                    continue
                if criminal_only and not case.get("is_criminal"):
                    continue
                return case, store
        return None

    def list_case_refs(
        self,
        *,
        court: Optional[str] = None,
        year: Optional[int] = None,
        criminal_only: bool = True,
    ) -> list[tuple[str, StoreName]]:
        seen: dict[str, StoreName] = {}
        for store in ("fulltext", "headnotes"):
            for ref in self._db(store).list_case_refs(
                court=court, year=year, criminal_only=criminal_only
            ):
                seen.setdefault(ref, store)
        return sorted((ref, seen[ref]) for ref in seen)

    def export_cases(
        self,
        *,
        court: Optional[str] = None,
        year: Optional[int] = None,
        criminal_only: bool = True,
    ) -> list[tuple[dict, StoreName]]:
        from ..retrieval import normalize_canlii_ref

        out: list[tuple[dict, StoreName]] = []
        for ref, store in self.list_case_refs(
            court=court, year=year, criminal_only=criminal_only
        ):
            case = self._db(store).get_case(normalize_canlii_ref(ref))
            if case:
                out.append((case, store))
        return out

    def curate_all(self) -> dict[str, Any]:
        """Re-apply curation rules to every case in both databases."""
        from ..curation.apply import curate_database

        reports = {}
        for store in ("fulltext", "headnotes"):
            reports[store] = curate_database(self._db(store)).to_dict()
        return reports

    def close(self) -> None:
        if self._fulltext is not None:
            self._fulltext.close()
            self._fulltext = None
        if self._headnotes is not None:
            self._headnotes.close()
            self._headnotes = None

    def __enter__(self) -> "DatabaseRouter":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
