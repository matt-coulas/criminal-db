"""SQLite schema for criminal-db.

Tables
------
cases                One row per decision (case-level metadata).
paragraphs           One row per paragraph (the searchable unit).
paragraphs_fts       FTS5 mirror of paragraphs.text + paragraphs.heading.
paragraph_embeddings sqlite-vec ``vec0`` virtual table keyed by paragraph_id.

``paragraphs_fts`` is kept in sync with ``paragraphs`` via after-insert,
after-update, and after-delete triggers so editing a paragraph keeps the
search index correct.
"""

from __future__ import annotations

import sqlite3
import warnings
from pathlib import Path
from typing import Tuple, Union

import sqlite_vec

from .. import config


PathLike = Union[str, Path]


class VectorExtensionUnavailable(RuntimeError):
    """Raised when sqlite-vec cannot be loaded into this SQLite build.

    Apple's system Python ships SQLite without ``--enable-loadable-sqlite-
    extensions``.  Install Python via ``python.org`` / ``brew install python``
    / ``uv python install`` / ``pyenv`` to get a build that supports
    loadable extensions, then re-create the database to add the ``vec0``
    table.
    """


def _try_load_vec(conn: sqlite3.Connection) -> bool:
    """Attempt to load sqlite-vec into ``conn``.

    Returns ``True`` on success.  Returns ``False`` (and emits a one-time
    warning) when the SQLite build does not support ``enable_load_extension``
    or when loading otherwise fails — in that case FTS5 still works, but
    vector / hybrid search is unavailable.
    """
    try:
        conn.enable_load_extension(True)
    except AttributeError:
        warnings.warn(
            "This Python's sqlite3 was built without extension loading "
            "support; vector / hybrid search will be unavailable. Install "
            "Python with --enable-loadable-sqlite-extensions (python.org, "
            "homebrew, uv, pyenv) to enable it.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    try:
        sqlite_vec.load(conn)
    except sqlite3.OperationalError as exc:  # pragma: no cover - platform dep
        warnings.warn(
            f"sqlite-vec failed to load: {exc}. Vector search will be "
            "unavailable.",
            RuntimeWarning,
            stacklevel=2,
        )
        return False
    finally:
        try:
            conn.enable_load_extension(False)
        except (AttributeError, sqlite3.OperationalError):
            pass
    return True


def open_connection(db_path: PathLike) -> Tuple[sqlite3.Connection, bool]:
    """Return ``(connection, has_vec)``.

    ``has_vec`` is ``True`` when ``sqlite-vec`` was successfully loaded; in
    that case all vector-related tables and queries are available.  When it
    is ``False`` the connection is still usable for FTS5 / metadata queries.
    """

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn, _try_load_vec(conn)


_DDL = """
CREATE TABLE IF NOT EXISTS cases (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    canlii_ref         TEXT    NOT NULL UNIQUE,
    neutral_citation   TEXT,
    reporter_citation  TEXT,
    court              TEXT,
    court_year         INTEGER,
    decided_date       TEXT,    -- ISO yyyy-mm-dd
    judges             TEXT,    -- JSON array
    corpus             TEXT NOT NULL DEFAULT 'fulltext'
                              CHECK (corpus IN ('fulltext', 'headnote')),
    is_headnote_only   INTEGER NOT NULL DEFAULT 0,
    source_url         TEXT,
    fetched_at         TEXT,    -- ISO timestamp
    created_at         TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_cases_court_year  ON cases(court, court_year);
CREATE INDEX IF NOT EXISTS idx_cases_decided     ON cases(decided_date);
CREATE INDEX IF NOT EXISTS idx_cases_corpus      ON cases(corpus);

CREATE TABLE IF NOT EXISTS paragraphs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id         INTEGER NOT NULL,
    paragraph_num   INTEGER,
    heading         TEXT,
    text            TEXT NOT NULL,
    is_headnote     INTEGER NOT NULL DEFAULT 0,
    is_ratio        INTEGER NOT NULL DEFAULT 0,
    section_number  TEXT,
    FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_paragraphs_case      ON paragraphs(case_id);
CREATE INDEX IF NOT EXISTS idx_paragraphs_para_num  ON paragraphs(paragraph_num);
CREATE INDEX IF NOT EXISTS idx_paragraphs_ratio     ON paragraphs(is_ratio);
CREATE INDEX IF NOT EXISTS idx_paragraphs_headnote  ON paragraphs(is_headnote);

-- FTS5 virtual table mirroring paragraphs.text + heading.
-- content='paragraphs' makes this a contentless external-content table so we
-- don't double-store the body; ``content_rowid='id'`` aligns with paragraphs.id.
CREATE VIRTUAL TABLE IF NOT EXISTS paragraphs_fts USING fts5(
    text,
    heading,
    content='paragraphs',
    content_rowid='id',
    tokenize="porter unicode61"
);

-- Sync triggers (insert / update / delete) keep the FTS index correct.
CREATE TRIGGER IF NOT EXISTS paragraphs_ai
AFTER INSERT ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(rowid, text, heading)
    VALUES (new.id, new.text, COALESCE(new.heading, ''));
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_ad
AFTER DELETE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, text, heading)
    VALUES('delete', old.id, old.text, COALESCE(old.heading, ''));
END;

CREATE TRIGGER IF NOT EXISTS paragraphs_au
AFTER UPDATE ON paragraphs BEGIN
    INSERT INTO paragraphs_fts(paragraphs_fts, rowid, text, heading)
    VALUES('delete', old.id, old.text, COALESCE(old.heading, ''));
    INSERT INTO paragraphs_fts(rowid, text, heading)
    VALUES (new.id, new.text, COALESCE(new.heading, ''));
END;
"""


def init_db(db_path: PathLike, *, embedding_dim: int | None = None) -> Path:
    """Create the schema in ``db_path`` if it does not already exist.

    Returns the absolute path to the database file.

    The ``paragraph_embeddings`` virtual table is only created if the
    underlying SQLite build supports loadable extensions; otherwise vector
    search will raise :class:`VectorExtensionUnavailable` at query time.
    """
    dim = embedding_dim if embedding_dim is not None else config.EMBEDDING_DIM
    conn, vec_ok = open_connection(db_path)
    try:
        conn.executescript(_DDL)
        if vec_ok:
            # vec0 takes the dim at table-creation time and stores it in
            # sqlite-vec's metadata, so it must match what we embed with.
            conn.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS paragraph_embeddings "
                f"USING vec0(paragraph_id INTEGER PRIMARY KEY, "
                f"embedding FLOAT[{dim}])"
            )
        conn.commit()
    finally:
        conn.close()
    return Path(db_path).resolve()


def init_default_databases() -> tuple[Path, Path]:
    """Initialise both ``headnotes.db`` and ``fulltext.db`` in ``DB_DIR``."""

    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    return (
        init_db(config.HEADNOTES_DB),
        init_db(config.FULLTEXT_DB),
    )
