"""Database operations for statute sections."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

from ..db.operations import sanitize_fts5
from .parser import SectionData, normalize_section_ref
from .schema import init_statutes_db, open_connection

PathLike = Union[str, Path]


@dataclass
class StatuteSearchResult:
    section_id: int
    act: str
    section_number: str
    heading: Optional[str]
    text: str
    score: float


class StatutesDatabase:
    def __init__(self, db_path: PathLike | None = None, *, auto_init: bool = True) -> None:
        from .. import config

        self.db_path = Path(db_path or config.STATUTES_DB)
        if auto_init:
            init_statutes_db(self.db_path)
        self.conn = open_connection(self.db_path)

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
        return [
            StatuteSearchResult(
                section_id=int(r["section_id"]),
                act=str(r["act"]),
                section_number=str(r["section_number"]),
                heading=r["heading"],
                text=str(r["text"]),
                score=float(r["score"]),
            )
            for r in rows
        ]
