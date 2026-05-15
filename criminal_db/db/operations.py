"""High-level database operations for criminal-db.

This module exposes a single :class:`Database` facade.  It is the only
abstraction the rest of the codebase needs over SQLite + sqlite-vec.

Conventions
-----------
* All public methods accept primitive types and return primitives or
  :class:`SearchResult` dataclasses.
* A ``Database`` instance owns a single connection.  Use it as a context
  manager (``with Database(path) as db: ...``) when possible.
* Insertion of a parsed case is idempotent on ``canlii_ref``.  Inserting an
  existing case replaces its paragraphs and embeddings so the case becomes a
  consistent reflection of the latest parse.
"""

from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence, Union

import sqlite_vec

from .. import config
from .schema import VectorExtensionUnavailable, init_db, open_connection


PathLike = Union[str, Path]


# ── Public types ────────────────────────────────────────────────────────────


@dataclass
class SearchResult:
    """A single search hit, joined to its case metadata."""

    paragraph_id: int
    case_id: int
    canlii_ref: str
    court: Optional[str]
    decided_date: Optional[str]
    paragraph_num: Optional[int]
    heading: Optional[str]
    text: str
    score: float
    source: str  # 'fts' | 'vector' | 'hybrid'
    store: str = "fulltext"  # physical db: 'fulltext' | 'headnotes'
    corpus: Optional[str] = None  # case corpus: 'fulltext' | 'headnote'


# ── FTS5 query sanitisation ─────────────────────────────────────────────────

# Characters that have meaning inside an FTS5 MATCH expression.  We rebuild the
# query as a phrase-tokenised sequence to keep user input safe and predictable.
_FTS5_SPECIAL = set('"():*^')


def sanitize_fts5(query: str, *, join: str = "OR") -> str:
    """Return an FTS5-safe MATCH expression from arbitrary user input.

    Each whitespace-separated token is wrapped in double quotes (with any
    internal double quote doubled, per FTS5 grammar) and joined with the
    ``join`` connector — ``"OR"`` by default so ranked retrieval can rank
    partial matches via BM25.  Explicit ``AND`` / ``OR`` / ``NOT`` / ``NEAR``
    tokens supplied by the user are preserved literally and suppress the
    auto-connector.
    """
    if join.upper() not in {"AND", "OR"}:
        raise ValueError("join must be 'AND' or 'OR'")
    operators = {"AND", "OR", "NOT", "NEAR"}
    raw_tokens = query.split()

    parts: list[str] = []
    prev_was_value = False
    for raw in raw_tokens:
        if raw in operators:
            if parts and prev_was_value:
                parts.append(raw)
            prev_was_value = False
            continue
        cleaned = "".join(c for c in raw if c not in _FTS5_SPECIAL)
        if not cleaned:
            continue
        quoted = '"' + cleaned.replace('"', '""') + '"'
        if prev_was_value:
            parts.append(join.upper())
        parts.append(quoted)
        prev_was_value = True

    # Trim any trailing dangling operator from explicit-user input.
    while parts and parts[-1] in operators:
        parts.pop()
    return " ".join(parts) if parts else '""'


# ── Vector helpers ──────────────────────────────────────────────────────────


def _vec_blob(vector: Sequence[float]) -> bytes:
    """Serialize a Python sequence of floats as a sqlite-vec FLOAT32 blob."""
    return sqlite_vec.serialize_float32(list(vector))


# ── Database facade ─────────────────────────────────────────────────────────


@dataclass
class _CaseRow:
    canlii_ref: str
    neutral_citation: Optional[str] = None
    reporter_citation: Optional[str] = None
    court: Optional[str] = None
    court_year: Optional[int] = None
    decided_date: Optional[str] = None
    judges: list[str] = field(default_factory=list)
    corpus: str = "fulltext"
    is_headnote_only: bool = False
    source_url: Optional[str] = None


class Database:
    """Facade around a single criminal-db SQLite database."""

    def __init__(self, db_path: PathLike, *, auto_init: bool = True) -> None:
        self.db_path = Path(db_path)
        if auto_init:
            init_db(self.db_path)
        self.conn, self.has_vec = open_connection(self.db_path)

    # -- context manager -----------------------------------------------------

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.ProgrammingError:
            # Already closed.
            pass

    # ── case insertion ──────────────────────────────────────────────────────

    def store_case(self, case_json: dict) -> int:
        """Insert (or replace) a parsed case + its paragraphs.

        ``case_json`` must follow the structure produced by
        :func:`criminal_db.harvester.parser.export_case_to_json` — a
        ``{"meta": {...}, "paragraphs": [...]}``` dict.

        Returns the integer ``cases.id`` of the stored case.
        """
        meta = case_json.get("meta") or {}
        canlii_ref = meta.get("canlii_ref")
        if not canlii_ref or canlii_ref == "UNKNOWN":
            raise ValueError("case_json.meta.canlii_ref is required and non-empty")

        case_row = _CaseRow(
            canlii_ref=canlii_ref,
            neutral_citation=meta.get("neutral_citation") or None,
            reporter_citation=meta.get("reporter_citation") or None,
            court=meta.get("court") or None,
            court_year=meta.get("court_year") or None,
            decided_date=meta.get("decided_date") or None,
            judges=list(meta.get("judges") or []),
            corpus=meta.get("corpus") or "fulltext",
            is_headnote_only=bool(meta.get("is_headnote_only", False)),
            source_url=meta.get("source_url") or None,
        )

        with self.conn:
            existing = self.conn.execute(
                "SELECT id FROM cases WHERE canlii_ref = ?", (canlii_ref,)
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")

            if existing:
                case_id = existing["id"]
                self.conn.execute(
                    """
                    UPDATE cases SET
                        neutral_citation = ?,
                        reporter_citation = ?,
                        court = ?,
                        court_year = ?,
                        decided_date = ?,
                        judges = ?,
                        corpus = ?,
                        is_headnote_only = ?,
                        source_url = ?,
                        fetched_at = COALESCE(?, fetched_at),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        case_row.neutral_citation,
                        case_row.reporter_citation,
                        case_row.court,
                        case_row.court_year,
                        case_row.decided_date,
                        json.dumps(case_row.judges, ensure_ascii=False),
                        case_row.corpus,
                        int(case_row.is_headnote_only),
                        case_row.source_url,
                        now,
                        now,
                        case_id,
                    ),
                )
                # Replace paragraphs (triggers maintain FTS).  Embeddings
                # are deleted manually because vec0 has no DELETE-cascade.
                if self.has_vec:
                    self.conn.execute(
                        "DELETE FROM paragraph_embeddings "
                        "WHERE paragraph_id IN "
                        "(SELECT id FROM paragraphs WHERE case_id = ?)",
                        (case_id,),
                    )
                self.conn.execute(
                    "DELETE FROM paragraphs WHERE case_id = ?", (case_id,)
                )
            else:
                cur = self.conn.execute(
                    """
                    INSERT INTO cases (
                        canlii_ref, neutral_citation, reporter_citation,
                        court, court_year, decided_date, judges,
                        corpus, is_headnote_only, source_url, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        case_row.canlii_ref,
                        case_row.neutral_citation,
                        case_row.reporter_citation,
                        case_row.court,
                        case_row.court_year,
                        case_row.decided_date,
                        json.dumps(case_row.judges, ensure_ascii=False),
                        case_row.corpus,
                        int(case_row.is_headnote_only),
                        case_row.source_url,
                        now,
                    ),
                )
                case_id = int(cur.lastrowid)

            paragraphs: list[dict] = case_json.get("paragraphs") or []
            if paragraphs:
                self.conn.executemany(
                    """
                    INSERT INTO paragraphs (
                        case_id, paragraph_num, heading, text,
                        is_headnote, is_ratio, section_number
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            case_id,
                            p.get("paragraph_num"),
                            p.get("heading"),
                            p.get("text") or "",
                            int(bool(p.get("is_headnote"))),
                            int(bool(p.get("is_ratio"))),
                            p.get("section_number"),
                        )
                        for p in paragraphs
                        if (p.get("text") or "").strip()
                    ],
                )

        return case_id

    # ── reads ───────────────────────────────────────────────────────────────

    def get_case(self, canlii_ref: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM cases WHERE canlii_ref = ?", (canlii_ref,)
        ).fetchone()
        if row is None:
            return None
        case = dict(row)
        case["judges"] = json.loads(case["judges"] or "[]")
        case["paragraphs"] = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM paragraphs WHERE case_id = ? "
                "ORDER BY COALESCE(paragraph_num, id)",
                (case["id"],),
            )
        ]
        return case

    def case_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0])

    def paragraph_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM paragraphs").fetchone()[0])

    def ratio_paragraph_count(self) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM paragraphs WHERE is_ratio = 1"
            ).fetchone()[0]
        )

    def headnote_paragraph_count(self) -> int:
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM paragraphs WHERE is_headnote = 1"
            ).fetchone()[0]
        )

    def court_distribution(self) -> dict[str, int]:
        return {
            row["court"] or "UNKNOWN": int(row["n"])
            for row in self.conn.execute(
                "SELECT COALESCE(court, '') AS court, COUNT(*) AS n "
                "FROM cases GROUP BY court"
            )
        }

    def year_distribution(self) -> dict[int, int]:
        return {
            int(row["court_year"]): int(row["n"])
            for row in self.conn.execute(
                "SELECT court_year, COUNT(*) AS n FROM cases "
                "WHERE court_year IS NOT NULL GROUP BY court_year ORDER BY court_year"
            )
        }

    # ── search ──────────────────────────────────────────────────────────────

    def search_fts(
        self,
        query: str,
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
    ) -> list[SearchResult]:
        """FTS5 search across paragraphs, optionally filtered by case metadata.

        Lower ``rank`` is better in FTS5; we negate it so higher score = better.
        """
        match_expr = sanitize_fts5(query)
        sql = [
            "SELECT p.id AS paragraph_id, p.case_id, c.canlii_ref, c.court, "
            "       c.decided_date, p.paragraph_num, p.heading, p.text, "
            "       -fts.rank AS score "
            "FROM paragraphs_fts fts "
            "JOIN paragraphs p ON p.id = fts.rowid "
            "JOIN cases c ON c.id = p.case_id "
            "WHERE paragraphs_fts MATCH ?"
        ]
        params: list[Any] = [match_expr]
        if court:
            sql.append("AND c.court = ?")
            params.append(court)
        if year is not None:
            sql.append("AND c.court_year = ?")
            params.append(year)
        if corpus:
            sql.append("AND c.corpus = ?")
            params.append(corpus)
        sql.append("ORDER BY fts.rank LIMIT ?")
        params.append(int(limit))

        rows = self.conn.execute("\n".join(sql), params).fetchall()
        return [_row_to_result(row, source="fts") for row in rows]

    def search_vector(
        self,
        vector: Sequence[float],
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
    ) -> list[SearchResult]:
        """KNN search over paragraph embeddings.

        ``score`` is ``1 - distance`` so higher = better, matching ``search_fts``.
        """
        if not self.has_vec:
            raise VectorExtensionUnavailable(
                "sqlite-vec is not available in this Python's SQLite build; "
                "vector search is disabled. Use --type fts or install a "
                "Python with extension-loading support."
            )
        blob = _vec_blob(vector)
        # vec0 KNN: ``embedding MATCH ?`` paired with ``k = ?`` clause.
        rows = self.conn.execute(
            """
            SELECT p.id AS paragraph_id, p.case_id, c.canlii_ref, c.court,
                   c.decided_date, p.paragraph_num, p.heading, p.text,
                   1.0 - pe.distance AS score
            FROM paragraph_embeddings pe
            JOIN paragraphs p ON p.id = pe.paragraph_id
            JOIN cases      c ON c.id = p.case_id
            WHERE pe.embedding MATCH ? AND k = ?
              AND (? IS NULL OR c.court = ?)
              AND (? IS NULL OR c.court_year = ?)
              AND (? IS NULL OR c.corpus = ?)
            ORDER BY pe.distance
            """,
            (
                blob,
                int(limit),
                court, court,
                year, year,
                corpus, corpus,
            ),
        ).fetchall()
        return [_row_to_result(row, source="vector") for row in rows]

    def search_hybrid(
        self,
        query: str,
        vector: Sequence[float],
        *,
        limit: int = 10,
        court: Optional[str] = None,
        year: Optional[int] = None,
        corpus: Optional[str] = None,
        fts_weight: float = config.HYBRID_FTS_WEIGHT,
    ) -> list[SearchResult]:
        """Hybrid FTS + vector with normalised score fusion.

        Each side fetches ``2 * limit`` candidates; scores are min-max
        normalised within each side, then combined with a convex weight.
        """
        fts_results = self.search_fts(
            query, limit=limit * 2, court=court, year=year, corpus=corpus
        )
        vec_results = self.search_vector(
            vector, limit=limit * 2, court=court, year=year, corpus=corpus
        )

        def _normalise(items: list[SearchResult]) -> dict[int, float]:
            if not items:
                return {}
            scores = [r.score for r in items]
            lo, hi = min(scores), max(scores)
            if hi - lo < 1e-9:
                return {r.paragraph_id: 1.0 for r in items}
            return {
                r.paragraph_id: (r.score - lo) / (hi - lo) for r in items
            }

        fts_norm = _normalise(fts_results)
        vec_norm = _normalise(vec_results)

        by_id: dict[int, SearchResult] = {}
        for r in fts_results + vec_results:
            if r.paragraph_id not in by_id:
                by_id[r.paragraph_id] = r

        combined: list[SearchResult] = []
        w = max(0.0, min(1.0, fts_weight))
        for pid, base in by_id.items():
            score = w * fts_norm.get(pid, 0.0) + (1 - w) * vec_norm.get(pid, 0.0)
            combined.append(
                SearchResult(
                    paragraph_id=base.paragraph_id,
                    case_id=base.case_id,
                    canlii_ref=base.canlii_ref,
                    court=base.court,
                    decided_date=base.decided_date,
                    paragraph_num=base.paragraph_num,
                    heading=base.heading,
                    text=base.text,
                    score=score,
                    source="hybrid",
                )
            )
        combined.sort(key=lambda r: r.score, reverse=True)
        return combined[:limit]

    # ── embeddings ──────────────────────────────────────────────────────────

    def paragraphs_missing_embeddings(
        self, *, limit: Optional[int] = None
    ) -> list[tuple[int, str]]:
        """Return ``(paragraph_id, text)`` for paragraphs without an embedding."""
        sql = (
            "SELECT p.id, p.text FROM paragraphs p "
            "LEFT JOIN paragraph_embeddings pe ON pe.paragraph_id = p.id "
            "WHERE pe.paragraph_id IS NULL"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [(int(r["id"]), r["text"]) for r in self.conn.execute(sql)]

    def store_embeddings(
        self, embeddings: Iterable[tuple[int, Sequence[float]]]
    ) -> int:
        """Insert ``(paragraph_id, vector)`` pairs.  Returns the number written."""
        if not self.has_vec:
            raise VectorExtensionUnavailable(
                "sqlite-vec is not available; cannot store embeddings."
            )
        rows = [(pid, _vec_blob(vec)) for pid, vec in embeddings]
        if not rows:
            return 0
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO paragraph_embeddings(paragraph_id, embedding) "
                "VALUES (?, ?)",
                rows,
            )
        return len(rows)

    def embedding_count(self) -> int:
        if not self.has_vec:
            return 0
        return int(
            self.conn.execute(
                "SELECT COUNT(*) FROM paragraph_embeddings"
            ).fetchone()[0]
        )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _row_to_result(row: sqlite3.Row, *, source: str) -> SearchResult:
    return SearchResult(
        paragraph_id=int(row["paragraph_id"]),
        case_id=int(row["case_id"]),
        canlii_ref=str(row["canlii_ref"]),
        court=row["court"],
        decided_date=row["decided_date"],
        paragraph_num=row["paragraph_num"],
        heading=row["heading"],
        text=row["text"],
        score=float(row["score"]),
        source=source,
    )
