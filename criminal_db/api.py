"""Stable Python entry points for scripts and LLM tool wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .db import Database, DatabaseRouter
from .db.schema import init_default_databases
from .retrieval import case_to_export_json, normalize_canlii_ref


def open_router() -> DatabaseRouter:
    """Initialise default databases and return a router."""
    init_default_databases()
    return DatabaseRouter()


def get_case(
    citation: str,
    *,
    router: Optional[DatabaseRouter] = None,
    criminal_only: bool = True,
) -> Optional[dict]:
    """Return export-shaped case JSON or ``None``."""
    own = router is None
    r = router or open_router()
    try:
        found = r.get_case(citation, criminal_only=criminal_only)
        if not found:
            return None
        case, store = found
        return case_to_export_json(case, store=store)
    finally:
        if own:
            r.close()


def search(
    query: str,
    *,
    mode: str = "fts",
    limit: int = 10,
    offset: int = 0,
    router: Optional[DatabaseRouter] = None,
    criminal_only: bool = True,
):
    """Search and return :class:`~criminal_db.db.SearchResult` list."""
    own = router is None
    r = router or open_router()
    try:
        if mode == "fts":
            return r.search_fts(
                query, limit=limit, offset=offset, criminal_only=criminal_only
            )
        if mode == "vector":
            from .embedding import Embedder

            vec = Embedder().encode_one(query)
            return r.search_vector(
                vec, limit=limit, offset=offset, criminal_only=criminal_only
            )
        from .embedding import Embedder

        vec = Embedder().encode_one(query)
        return r.search_hybrid(
            query, vec, limit=limit, offset=offset, criminal_only=criminal_only
        )
    finally:
        if own:
            r.close()
