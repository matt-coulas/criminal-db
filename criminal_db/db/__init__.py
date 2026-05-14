"""Database layer for criminal-db."""

from .schema import (
    VectorExtensionUnavailable,
    init_db,
    init_default_databases,
    open_connection,
)
from .operations import Database, SearchResult

__all__ = [
    "Database",
    "SearchResult",
    "VectorExtensionUnavailable",
    "init_db",
    "init_default_databases",
    "open_connection",
]
