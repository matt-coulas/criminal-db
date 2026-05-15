"""Database operations for statute sections."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence, Union

from .. import config
from ..db.operations import sanitize_fts5
from ..db.schema import VectorExtensionUnavailable
from .parser import SectionData, normalize_section_ref
from .schema import init_statutes_db, open_connection

PathLike = Union[str, Path]


def _vec_blob(vector: Sequence[float]) -> bytes:
    import sqlite_vec

    return sqlite_vec.serialize_float32(list(vector))


@dataclass
class StatuteSearchResult:
    section_id: int
    act: str
    section_number: str
    heading: Optional[str]
    text: str
    score: float
    source: str = "fts"


class StatutesDatabase:
    def __init__(self, db_path: PathLike | None = None, *, auto_init: bool = True) -> None:
        self.db_path = Path(db_path or config.STATUTES_DB)
        if auto_init:
            init_statutes_db(self.db_path)
        self.conn, self.has_vec = open_connection(self.db_path)

    def __enter__(self) -> "StatutesDatabase":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def close(self) -> None:
        self.conn.close()

    def store_sections(self, sections: list[SectionData]) -> int:
        written = 0
        with self.conn:
            for sec in sections:
                existing = self.conn.execute(
                    "SELECT id FROM sections WHERE act = ? AND section_number = ?",
                    (sec.act, sec.section_number),
                ).fetchone()
                if existing:
                    self.conn.execute(
                        """
                        UPDATE sections SET heading = ?, text = ?, part = ?,
                        updated_at = datetime('now')
                        WHERE id = ?
                        """,
                        (sec.heading, sec.text, sec.part, existing["id"]),
                    )
                    if self.has_vec:
                        self.conn.execute(
                            "DELETE FROM section_embeddings WHERE section_id = ?",
                            (existing["id"],),
                        )
                else:
                    self.conn.execute(
                        """
                        INSERT INTO sections (act, section_number, heading, text, part)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (sec.act, sec.section_number, sec.heading, sec.text, sec.part),
                    )
                written += 1
        return written

    def get_section(
        self, ref: str, *, act: str = "criminal_code"
    ) -> Optional[dict]:
        num = normalize_section_ref(ref)
        row = self.conn.execute(
            "SELECT * FROM sections WHERE act = ? AND section_number = ?",
            (act, num),
        ).fetchone()
        return dict(row) if row else None

    def section_count(self) -> int:
        return int(self.conn.execute("SELECT COUNT(*) FROM sections").fetchone()[0])

    def embedding_count(self) -> int:
        if not self.has_vec:
            return 0
        return int(
            self.conn.execute("SELECT COUNT(*) FROM section_embeddings").fetchone()[0]
        )

    def sections_missing_embeddings(
        self, *, limit: Optional[int] = None
    ) -> list[tuple[int, str]]:
        if not self.has_vec:
            return []
        sql = (
            "SELECT s.id, s.text FROM sections s "
            "LEFT JOIN section_embeddings se ON se.section_id = s.id "
            "WHERE se.section_id IS NULL"
        )
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        return [(int(r["id"]), r["text"]) for r in self.conn.execute(sql)]

    def store_embeddings(
        self, embeddings: Sequence[tuple[int, Sequence[float]]]
    ) -> int:
        if not self.has_vec:
            raise VectorExtensionUnavailable(
                "sqlite-vec is not available; cannot store statute embeddings."
            )
        rows = [(sid, _vec_blob(vec)) for sid, vec in embeddings]
        if not rows:
            return 0
        with self.conn:
            self.conn.executemany(
                "INSERT OR REPLACE INTO section_embeddings(section_id, embedding) "
                "VALUES (?, ?)",
                rows,
            )
        return len(rows)

    def search_fts(self, query: str, *, limit: int = 10) -> list[StatuteSearchResult]:
        match_expr = sanitize_fts5(query)
        rows = self.conn.execute(
            """
            SELECT s.id AS section_id, s.act, s.section_number, s.heading, s.text,
                   -fts.rank AS score
            FROM sections_fts fts
            JOIN sections s ON s.id = fts.rowid
            WHERE sections_fts MATCH ?
            ORDER BY fts.rank
            LIMIT ?
            """,
            (match_expr, int(limit)),
        ).fetchall()
        return [_row_to_statute_result(r, source="fts") for r in rows]

    def search_vector(
        self, vector: Sequence[float], *, limit: int = 10
    ) -> list[StatuteSearchResult]:
        if not self.has_vec:
            raise VectorExtensionUnavailable(
                "sqlite-vec is not available; use --type fts for statutes."
            )
        blob = _vec_blob(vector)
        rows = self.conn.execute(
            """
            SELECT s.id AS section_id, s.act, s.section_number, s.heading, s.text,
                   1.0 - se.distance AS score
            FROM section_embeddings se
            JOIN sections s ON s.id = se.section_id
            WHERE se.embedding MATCH ? AND k = ?
            ORDER BY se.distance
            """,
            (blob, int(limit)),
        ).fetchall()
        return [_row_to_statute_result(r, source="vector") for r in rows]

    def search_hybrid(
        self,
        query: str,
        vector: Sequence[float],
        *,
        limit: int = 10,
        fts_weight: float = config.HYBRID_FTS_WEIGHT,
    ) -> list[StatuteSearchResult]:
        fts_results = self.search_fts(query, limit=limit * 3)
        vec_results = self.search_vector(vector, limit=limit * 3)
        fts_scores = [r.score for r in fts_results]
        vec_scores = [r.score for r in vec_results]
        fts_lo, fts_hi = (min(fts_scores), max(fts_scores)) if fts_scores else (0.0, 1.0)
        vec_lo, vec_hi = (min(vec_scores), max(vec_scores)) if vec_scores else (0.0, 1.0)

        def norm(val: float, lo: float, hi: float) -> float:
            if hi - lo < 1e-9:
                return 1.0
            return (val - lo) / (hi - lo)

        by_id: dict[int, StatuteSearchResult] = {}
        for r in fts_results + vec_results:
            by_id.setdefault(r.section_id, r)
        w = max(0.0, min(1.0, fts_weight))
        combined: list[StatuteSearchResult] = []
        for sid, base in by_id.items():
            fts_n = norm(
                next((r.score for r in fts_results if r.section_id == sid), 0.0),
                fts_lo,
                fts_hi,
            )
            vec_n = norm(
                next((r.score for r in vec_results if r.section_id == sid), 0.0),
                vec_lo,
                vec_hi,
            )
            combined.append(
                StatuteSearchResult(
                    section_id=base.section_id,
                    act=base.act,
                    section_number=base.section_number,
                    heading=base.heading,
                    text=base.text,
                    score=w * fts_n + (1 - w) * vec_n,
                    source="hybrid",
                )
            )
        combined.sort(key=lambda r: r.score, reverse=True)
        return combined[:limit]


def _row_to_statute_result(row: sqlite3.Row, *, source: str) -> StatuteSearchResult:
    return StatuteSearchResult(
        section_id=int(row["section_id"]),
        act=str(row["act"]),
        section_number=str(row["section_number"]),
        heading=row["heading"],
        text=str(row["text"]),
        score=float(row["score"]),
        source=source,
    )
