"""Stable Python entry points for scripts and LLM tool wrappers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Union

from .db import DatabaseRouter
from .db.schema import init_default_databases
from .retrieval import case_to_export_json
from .search_unified import UnifiedSearchHit, search_all_fts, search_all_hybrid
from .statutes import StatutesDatabase

SearchScope = Literal["cases", "statutes", "all"]
SearchMode = Literal["fts", "vector", "hybrid"]


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


def get_statute(
    section: str,
    *,
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    """Return a statute section row or ``None``."""
    db = StatutesDatabase(db_path) if db_path else StatutesDatabase()
    try:
        row = db.get_section(section)
        return row
    finally:
        db.close()


def search(
    query: str,
    *,
    mode: str = "fts",
    limit: int = 10,
    offset: int = 0,
    scope: SearchScope = "cases",
    router: Optional[DatabaseRouter] = None,
    criminal_only: bool = True,
    court: Optional[str] = None,
    year: Optional[int] = None,
    corpus: Optional[str] = None,
) -> Union[list, list[UnifiedSearchHit]]:
    """Search cases, statutes, or both (``scope='all'``)."""
    st = mode.lower()
    sc = scope.lower()

    if sc == "statutes":
        db = StatutesDatabase()
        try:
            if st == "fts":
                return db.search_fts(query, limit=limit)
            if st == "vector":
                from .embedding import Embedder

                vec = Embedder().encode_one(query)
                return db.search_vector(vec, limit=limit)
            from .embedding import Embedder

            vec = Embedder().encode_one(query)
            return db.search_hybrid(query, vec, limit=limit)
        finally:
            db.close()

    own = router is None
    r = router or open_router()
    try:
        if sc == "all":
            statutes = StatutesDatabase(auto_init=False)
            try:
                if st == "fts":
                    return search_all_fts(
                        query,
                        router=r,
                        statutes=statutes,
                        limit=limit,
                        offset=offset,
                        court=court,
                        year=year,
                        corpus=corpus,
                        criminal_only=criminal_only,
                    )
                from .embedding import Embedder

                vec = Embedder().encode_one(query)
                return search_all_hybrid(
                    query,
                    vec,
                    router=r,
                    statutes=statutes,
                    limit=limit,
                    offset=offset,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=criminal_only,
                )
            finally:
                statutes.close()

        common = dict(
            limit=limit,
            offset=offset,
            court=court,
            year=year,
            corpus=corpus,
            criminal_only=criminal_only,
        )
        if st == "fts":
            return r.search_fts(query, **common)
        if st == "vector":
            from .embedding import Embedder

            vec = Embedder().encode_one(query)
            return r.search_vector(vec, **common)
        from .embedding import Embedder

        vec = Embedder().encode_one(query)
        return r.search_hybrid(query, vec, **common)
    finally:
        if own:
            r.close()
