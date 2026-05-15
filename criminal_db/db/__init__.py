"""Database layer for criminal-db."""

from .schema import (
    VectorExtensionUnavailable,
    init_db,
    init_default_databases,
    open_connection,
)
from .operations import Database, SearchResult
from .router import DatabaseRouter, db_path_for_corpus

__all__ = [
    "Database",
    "DatabaseRouter",
    "SearchResult",
    "VectorExtensionUnavailable",
    "db_path_for_corpus",
    "init_db",
    "init_default_databases",
    "open_connection",
]
