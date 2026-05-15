"""SQLite schema for statute sections (Criminal Code)."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Tuple, Union

from .. import config

PathLike = Union[str, Path]

_DDL = """
CREATE TABLE IF NOT EXISTS sections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    act             TEXT NOT NULL DEFAULT 'criminal_code',
    section_number  TEXT NOT NULL,
    heading         TEXT,
    text            TEXT NOT NULL,
    part            TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(act, section_number)
);

CREATE INDEX IF NOT EXISTS idx_sections_act ON sections(act);
CREATE INDEX IF NOT EXISTS idx_sections_part ON sections(part);

CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    text,
    heading,
    section_number,
    content='sections',
    content_rowid='id',
    tokenize="porter unicode61"
);

CREATE TRIGGER IF NOT EXISTS sections_ai
AFTER INSERT ON sections BEGIN
    INSERT INTO sections_fts(rowid, text, heading, section_number)
    VALUES (new.id, new.text, COALESCE(new.heading, ''), new.section_number);
END;

CREATE TRIGGER IF NOT EXISTS sections_ad
AFTER DELETE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, text, heading, section_number)
    VALUES('delete', old.id, old.text, COALESCE(old.heading, ''), old.section_number);
END;

CREATE TRIGGER IF NOT EXISTS sections_au
AFTER UPDATE ON sections BEGIN
    INSERT INTO sections_fts(sections_fts, rowid, text, heading, section_number)
    VALUES('delete', old.id, old.text, COALESCE(old.heading, ''), old.section_number);
    INSERT INTO sections_fts(rowid, text, heading, section_number)
    VALUES (new.id, new.text, COALESCE(new.heading, ''), new.section_number);
END;
"""


def open_connection(db_path: PathLike) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_statutes_db(db_path: PathLike | None = None) -> Path:
    path = Path(db_path or config.STATUTES_DB)
    conn = open_connection(path)
    try:
        conn.executescript(_DDL)
        conn.commit()
    finally:
        conn.close()
    return path.resolve()
