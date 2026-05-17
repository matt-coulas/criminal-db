#!/usr/bin/env python3
"""End-to-end example: parse synthetic CanLII fixtures, embed them, and run
FTS5 / vector / hybrid searches side-by-side over the same corpus.

Run from the repo root::

    python examples/hybrid_search.py                # default 5 example queries
    python examples/hybrid_search.py "your query"   # one custom query

The script creates a throwaway SQLite database under ``./tmp_hybrid.db`` and
populates it from ``tests/fixtures/real/*.html``.  It does not touch the
project ``db/criminal.db``.

Requires the ``embed`` extra::

    pip install -e ".[embed,dev]"

Vector and hybrid search additionally require a SQLite build with
``--enable-loadable-sqlite-extensions``.  On macOS the system Python ships
without that flag; use ``uv``/``brew``/``pyenv`` Python instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from criminal_db import config  # noqa: E402
from criminal_db.db import Database, VectorExtensionUnavailable  # noqa: E402
from criminal_db.harvester.parser import (  # noqa: E402
    CanLIIParser,
    export_case_to_json,
)


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "real"

DEFAULT_QUERIES = [
    "warrantless aerial thermal imaging of a residence",
    "breath analyser readings impaired driving",
    "Vavilov reasonableness review",
    "air of reality self defence",
    "section 8 Charter unreasonable search",
]


console = Console()


def seed_corpus(db: Database) -> None:
    files = sorted(FIXTURES.glob("*.html"))
    if not files:
        console.print(
            f"[red]No fixture HTML files found under {FIXTURES}.[/]"
        )
        sys.exit(1)
    for path in files:
        html = path.read_text(encoding="utf-8")
        case = CanLIIParser(html, source_url=path.resolve().as_uri()).parse()
        if case.canlii_ref == "UNKNOWN":
            console.print(f"[yellow]skip[/] {path.name}: no citation")
            continue
        case_id = db.store_case(export_case_to_json(case))
        console.print(
            f"[green]+[/] {case.canlii_ref:<20} "
            f"case_id={case_id:<3} paras={len(case.paragraphs):<3} "
            f"corpus={case.corpus}"
        )


def embed_pending(db: Database) -> bool:
    """Embed any paragraphs missing a vector.  Returns True on success."""
    try:
        from criminal_db.embedding import Embedder, chunked
    except RuntimeError as exc:
        console.print(f"[yellow]embed skipped:[/] {exc}")
        return False
    missing = db.paragraphs_missing_embeddings()
    if not missing:
        return True
    try:
        embedder = Embedder()
        for batch in chunked(missing, config.EMBEDDING_BATCH_SIZE):
            ids = [pid for pid, _ in batch]
            texts = [text for _, text in batch]
            vectors = embedder.encode(texts)
            db.store_embeddings(zip(ids, vectors))
        console.print(
            f"[green]embedded[/] {len(missing)} paragraphs with "
            f"{config.EMBEDDING_MODEL}"
        )
        return True
    except VectorExtensionUnavailable as exc:
        console.print(f"[yellow]vector store unavailable:[/] {exc}")
        return False


def render(title: str, results) -> None:
    table = Table(title=title, show_lines=False, expand=True)
    table.add_column("#", justify="right", style="dim", width=3)
    table.add_column("citation", style="cyan", width=14)
    table.add_column("¶", justify="right", width=3)
    table.add_column("score", justify="right", width=6)
    table.add_column("excerpt")
    if not results:
        console.print(Panel("no results", title=title, expand=False))
        return
    for i, r in enumerate(results, 1):
        excerpt = r.text if len(r.text) <= 160 else r.text[:157] + "..."
        para = "" if r.paragraph_num is None else str(r.paragraph_num)
        table.add_row(str(i), r.canlii_ref, para, f"{r.score:.3f}", excerpt)
    console.print(table)


def run_query(db: Database, query: str, vector=None, limit: int = 3) -> None:
    console.print()
    console.rule(f"[bold]{query}[/]")
    fts = db.search_fts(query, limit=limit)
    render("FTS5", fts)
    if vector is None:
        return
    try:
        vec_results = db.search_vector(vector, limit=limit)
        render("Vector", vec_results)
        hybrid = db.search_hybrid(query, vector, limit=limit)
        render("Hybrid (BM25 OR + cosine)", hybrid)
    except VectorExtensionUnavailable as exc:
        console.print(f"[yellow]vector path skipped:[/] {exc}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "queries",
        nargs="*",
        help="One or more search queries (defaults to a built-in set).",
    )
    ap.add_argument(
        "--db",
        default=str(REPO_ROOT / "tmp_hybrid.db"),
        help="Path to the SQLite file (will be created).",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Max results per search type.",
    )
    args = ap.parse_args()

    db_path = Path(args.db)
    if db_path.exists():
        db_path.unlink()

    console.rule(f"[bold]seeding {db_path.name}[/]")
    db = Database(db_path)
    try:
        seed_corpus(db)
        has_vector = embed_pending(db)

        embedder = None
        if has_vector:
            from criminal_db.embedding import Embedder

            embedder = Embedder()

        queries = args.queries or DEFAULT_QUERIES
        for query in queries:
            vector = embedder.encode_one(query) if embedder else None
            run_query(db, query, vector=vector, limit=args.limit)
    finally:
        db.close()


if __name__ == "__main__":
    main()
