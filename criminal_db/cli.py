"""Command-line entry point for criminal-db."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.table import Table

from . import config
from .db import Database, init_default_databases
from .db.schema import init_db
from .harvester import (
    CanLIIFetcher,
    CanLIIParser,
    export_case_to_json,
    extract_case_links,
)


console = Console()


def _resolve_db(db_path: Optional[str]) -> Path:
    path = Path(db_path) if db_path else config.DEFAULT_DB
    init_db(path)
    return path.resolve()


# ── Group ──────────────────────────────────────────────────────────────────


@click.group()
@click.version_option(package_name="criminal-db", prog_name="criminal-db")
def cli() -> None:
    """Canadian criminal-law case database CLI."""


# ── init ───────────────────────────────────────────────────────────────────


@cli.command("init")
def init_cmd() -> None:
    """Create the default SQLite databases under ``db/`` if missing."""
    headnotes, fulltext = init_default_databases()
    console.print(f"[green]ok[/]  headnotes db: {headnotes}")
    console.print(f"[green]ok[/]  fulltext  db: {fulltext}")


# ── parse (offline) ────────────────────────────────────────────────────────


@cli.command("parse")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option(
    "--no-store",
    is_flag=True,
    help="Print the parsed JSON instead of storing it in the database",
)
def parse_cmd(paths: tuple[str, ...], db_path: Optional[str], no_store: bool) -> None:
    """Parse CanLII HTML files that you've already downloaded.

    ``PATHS`` may be individual ``.html`` files or directories.
    """
    if not paths:
        raise click.UsageError("at least one path is required")
    files: list[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            files.extend(sorted(p.rglob("*.html")))
        else:
            files.append(p)
    if not files:
        console.print("[yellow]no .html files found[/]")
        return

    db: Optional[Database] = None
    if not no_store:
        db = Database(_resolve_db(db_path))

    parsed_ok = 0
    parsed_fail = 0
    try:
        for path in files:
            try:
                html = path.read_text(encoding="utf-8", errors="replace")
                case = CanLIIParser(
                    html, source_url=path.resolve().as_uri()
                ).parse()
                payload = export_case_to_json(case)
                if no_store:
                    console.print_json(data=payload)
                else:
                    assert db is not None
                    if case.canlii_ref == "UNKNOWN":
                        console.print(f"[yellow]skip[/] {path.name}: no citation detected")
                        parsed_fail += 1
                        continue
                    case_id = db.store_case(payload)
                    console.print(
                        f"[green]ok[/] {path.name} -> case_id={case_id} "
                        f"({case.canlii_ref}, {len(case.paragraphs)} paras)"
                    )
                parsed_ok += 1
            except Exception as exc:  # pragma: no cover - error surface
                console.print(f"[red]err[/] {path.name}: {exc}")
                parsed_fail += 1
    finally:
        if db is not None:
            db.close()

    console.print(
        f"\n[green]{parsed_ok} ok[/], [red]{parsed_fail} failed[/]."
    )


# ── harvest (online) ───────────────────────────────────────────────────────


@cli.command("harvest")
@click.argument("url")
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option(
    "--save-html",
    type=click.Path(file_okay=False, dir_okay=True),
    default=None,
    help="Directory to save raw HTML",
)
@click.option(
    "--listing/--single",
    default=False,
    help="Treat URL as a listing page and follow each case link",
)
@click.option("--limit", default=10, type=int, help="Max cases to fetch from a listing")
def harvest_cmd(
    url: str,
    db_path: Optional[str],
    save_html: Optional[str],
    listing: bool,
    limit: int,
) -> None:
    """Fetch one or more cases from CanLII.

    By default, ``URL`` is treated as a single case-detail page.  Use
    ``--listing`` to treat it as a search-results / index page and follow
    every case link on it (up to ``--limit``).
    """
    db_resolved = _resolve_db(db_path)
    asyncio.run(
        _run_harvest(
            url,
            db_path=db_resolved,
            save_html=Path(save_html) if save_html else None,
            listing=listing,
            limit=limit,
        )
    )


async def _run_harvest(
    url: str,
    *,
    db_path: Path,
    save_html: Optional[Path],
    listing: bool,
    limit: int,
) -> None:
    async with CanLIIFetcher() as fetcher:
        if not listing:
            await _harvest_single(fetcher, url, db_path=db_path, save_html=save_html)
            return

        console.print(f"[cyan]listing[/] {url}")
        index = await fetcher.fetch(url)
        if index is None:
            console.print("[red]failed to fetch listing[/]")
            return
        links = extract_case_links(index.html)[:limit]
        if save_html:
            save_html.mkdir(parents=True, exist_ok=True)
            (save_html / "_index.html").write_text(index.html, encoding="utf-8")
        console.print(f"  found [bold]{len(links)}[/] case link(s)")
        for case_url in links:
            await _harvest_single(
                fetcher, case_url, db_path=db_path, save_html=save_html
            )


async def _harvest_single(
    fetcher: CanLIIFetcher,
    url: str,
    *,
    db_path: Path,
    save_html: Optional[Path],
) -> None:
    console.print(f"[cyan]fetch[/] {url}")
    result = await fetcher.fetch(url)
    if result is None:
        console.print("[red]  failed[/]")
        return
    case = CanLIIParser(result.html, source_url=url).parse()
    if case.canlii_ref == "UNKNOWN":
        console.print("[yellow]  no citation detected; not storing[/]")
        return

    if save_html:
        save_html.mkdir(parents=True, exist_ok=True)
        safe = case.canlii_ref.replace(" ", "_").replace("/", "_")
        (save_html / f"{safe}.html").write_text(result.html, encoding="utf-8")

    with Database(db_path) as db:
        case_id = db.store_case(export_case_to_json(case))
    console.print(
        f"[green]  ok[/] {case.canlii_ref} -> case_id={case_id} "
        f"({len(case.paragraphs)} paras, {case.corpus})"
    )


# ── embed ──────────────────────────────────────────────────────────────────


@cli.command("embed")
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option(
    "--batch-size", default=None, type=int, help="Override embedder batch size"
)
@click.option("--limit", default=None, type=int, help="Max paragraphs to process")
def embed_cmd(
    db_path: Optional[str],
    batch_size: Optional[int],
    limit: Optional[int],
) -> None:
    """Compute embeddings for paragraphs that don't have one yet."""
    from .embedding import Embedder, chunked

    db = Database(_resolve_db(db_path))
    try:
        missing = db.paragraphs_missing_embeddings(limit=limit)
        if not missing:
            console.print("[green]all paragraphs already embedded[/]")
            return
        console.print(f"[cyan]embedding[/] {len(missing)} paragraphs")
        embedder = Embedder()
        size = batch_size or config.EMBEDDING_BATCH_SIZE
        total = 0
        for batch in chunked(missing, size):
            ids = [pid for pid, _ in batch]
            texts = [text for _, text in batch]
            vectors = embedder.encode(texts)
            db.store_embeddings(zip(ids, vectors))
            total += len(batch)
            console.print(f"  +{len(batch)} ({total}/{len(missing)})")
        console.print(f"[green]ok[/] embedded {total} paragraphs")
    finally:
        db.close()


# ── search ─────────────────────────────────────────────────────────────────


@cli.command("search")
@click.argument("query")
@click.option(
    "--type",
    "search_type",
    type=click.Choice(["fts", "vector", "hybrid"], case_sensitive=False),
    default="fts",
    help="Search strategy",
)
@click.option("--db", "db_path", default=None, help="SQLite database path")
@click.option("--limit", "-n", default=config.DEFAULT_SEARCH_LIMIT, type=int)
@click.option("--court", default=None, help="Filter by court name")
@click.option("--year", default=None, type=int, help="Filter by court_year")
@click.option(
    "--corpus",
    default=None,
    type=click.Choice(["fulltext", "headnote"], case_sensitive=False),
)
def search_cmd(
    query: str,
    search_type: str,
    db_path: Optional[str],
    limit: int,
    court: Optional[str],
    year: Optional[int],
    corpus: Optional[str],
) -> None:
    """Search the database with FTS5, vector similarity, or a hybrid of both."""
    db = Database(_resolve_db(db_path))
    try:
        st = search_type.lower()
        if st == "fts":
            results = db.search_fts(
                query, limit=limit, court=court, year=year, corpus=corpus
            )
        elif st == "vector":
            from .embedding import Embedder
            vector = Embedder().encode_one(query)
            results = db.search_vector(
                vector, limit=limit, court=court, year=year, corpus=corpus
            )
        else:
            from .embedding import Embedder
            vector = Embedder().encode_one(query)
            results = db.search_hybrid(
                query, vector, limit=limit, court=court, year=year, corpus=corpus
            )
    finally:
        db.close()

    if not results:
        console.print("[yellow]no results[/]")
        return

    table = Table(show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("citation", style="cyan")
    table.add_column("¶", justify="right")
    table.add_column("court / date", style="green")
    table.add_column("score", justify="right")
    table.add_column("excerpt")
    for idx, r in enumerate(results, 1):
        para = "" if r.paragraph_num is None else str(r.paragraph_num)
        excerpt = r.text if len(r.text) <= 220 else r.text[:217] + "..."
        table.add_row(
            str(idx),
            r.canlii_ref,
            para,
            f"{r.court or '—'}\n{r.decided_date or '—'}",
            f"{r.score:.3f}",
            excerpt,
        )
    console.print(table)


# ── analyze ────────────────────────────────────────────────────────────────


@cli.command("analyze")
@click.option("--db", "db_path", default=None, help="SQLite database path")
def analyze_cmd(db_path: Optional[str]) -> None:
    """Print database statistics."""
    db = Database(_resolve_db(db_path))
    try:
        cases = db.case_count()
        paragraphs = db.paragraph_count()
        ratios = db.ratio_paragraph_count()
        headnotes = db.headnote_paragraph_count()
        embeddings = db.embedding_count()
        console.print(f"[bold]cases:[/]        {cases}")
        console.print(f"[bold]paragraphs:[/]   {paragraphs}")
        console.print(f"  ratio:       {ratios}")
        console.print(f"  headnote:    {headnotes}")
        console.print(f"  embeddings:  {embeddings}/{paragraphs}")

        by_court = db.court_distribution()
        if by_court:
            console.print("\n[bold]by court[/]")
            table = Table()
            table.add_column("court")
            table.add_column("n", justify="right")
            for name, n in sorted(by_court.items(), key=lambda kv: -kv[1]):
                table.add_row(name, str(n))
            console.print(table)

        by_year = db.year_distribution()
        if by_year:
            console.print("\n[bold]by year[/]")
            table = Table()
            table.add_column("year")
            table.add_column("n", justify="right")
            for year, n in sorted(by_year.items()):
                table.add_row(str(year), str(n))
            console.print(table)
    finally:
        db.close()


def main() -> None:  # pragma: no cover - CLI entry
    cli(prog_name="criminal-db")


if __name__ == "__main__":  # pragma: no cover
    main()
