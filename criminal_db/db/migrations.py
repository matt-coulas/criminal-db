"""Versioned SQLite schema migrations for case databases."""

from __future__ import annotations

import sqlite3

CURRENT_SCHEMA_VERSION = 2


def _ensure_version_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def schema_version(conn: sqlite3.Connection) -> int:
    """Return recorded schema version, or 0 if unset."""
    _ensure_version_table(conn)
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def _set_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO schema_version(version, applied_at) "
        "VALUES (?, datetime('now'))",
        (version,),
    )


def _migrate_v1(conn: sqlite3.Connection) -> None:
    """Add curation columns introduced after the initial schema."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cases)")}
    if "is_criminal" not in cols:
        conn.execute(
            "ALTER TABLE cases ADD COLUMN is_criminal INTEGER NOT NULL DEFAULT 1"
        )
    if "exclusion_reason" not in cols:
        conn.execute("ALTER TABLE cases ADD COLUMN exclusion_reason TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cases_is_criminal ON cases(is_criminal)"
    )


def apply_case_migrations(conn: sqlite3.Connection) -> int:
    """Apply pending migrations. Returns the schema version after migration."""
    _ensure_version_table(conn)
    version = schema_version(conn)
    if version < 1:
        _migrate_v1(conn)
        _set_version(conn, 1)
        version = 1
    if version < CURRENT_SCHEMA_VERSION:
        _set_version(conn, CURRENT_SCHEMA_VERSION)
        version = CURRENT_SCHEMA_VERSION
    return version
