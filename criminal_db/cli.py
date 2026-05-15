"""Command-line entry point for criminal-db."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional, Union

import click
from rich.console import Console

from . import config
from .catalog import (
    CatalogEntry,
    IngestReport,
    Manifest,
    ensure_catalog_dirs,
    ingest_paths,
)
from .cli_output import emit_json, print_analyze, print_search_results
from .retrieval import case_to_export_json, format_case_text, normalize_canlii_ref
from .db import Database, DatabaseRouter, init_default_databases
from .db.schema import init_db
from .curation.rules import classify_case
from .harvester import (
    CanLIIFetcher,
    CanLIIParser,
    export_case_to_json,
    extract_case_links,
)


console = Console()
Backend = Union[Database, DatabaseRouter]


def _ctx_json(ctx: click.Context) -> bool:
    return bool(ctx.obj and ctx.obj.get("json"))


def _resolve_single_db(db_path: Optional[str]) -> Path:
    path = Path(db_path) if db_path else config.DEFAULT_DB
    init_db(path)
    return path.resolve()


def _open_backend(db_path: Optional[str]) -> Backend:
    if db_path:
        return Database(_resolve_single_db(db_path))
    init_default_databases()
    return DatabaseRouter()


def _close_backend(backend: Backend) -> None:
    backend.close()


def _manifest_record_html(
    path: Path,
    *,
    status: str = "pending",
    canlii_ref: Optional[str] = None,
    corpus: Optional[str] = None,
    case_id: Optional[int] = None,
    store: Optional[str] = None,
    source_url: Optional[str] = None,
    parse_error: Optional[str] = None,
) -> None:
    from .catalog.ingest import _sha256_file
    from datetime import datetime, timezone

    ensure_catalog_dirs()
    manifest = Manifest.load()
    key = Manifest.entry_key(path)
    existing = manifest.entries.get(key)
    entry = CatalogEntry(
        source_path=key,
        status=status,  # type: ignore[arg-type]
        canlii_ref=canlii_ref,
        corpus=corpus,
        sha256=_sha256_file(path) if path.exists() else None,
        fetched_at=existing.fetched_at if existing else None,
        parsed_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
        if status == "ok"
        else None,
        parse_error=parse_error,
        case_id=case_id,
        store=store,  # type: ignore[arg-type]
        source_url=source_url,
    )
    if not entry.fetched_at:
        entry.fetched_at = entry.parsed_at
    manifest.upsert(entry)
    manifest.save()


# ── Group ──────────────────────────────────────────────────────────────────


@click.group()
@click.option(
    "--json",
    "as_json",
    is_flag=True,
    help="Emit machine-readable JSON on stdout (for scripts and LLM agents).",
)
@click.version_option(package_name="criminal-db", prog_name="criminal-db")
@click.pass_context
def cli(ctx: click.Context, as_json: bool) -> None:
    """Canadian criminal-law case database CLI."""
    ctx.ensure_object(dict)
    ctx.obj["json"] = as_json


# ── init ───────────────────────────────────────────────────────────────────


@cli.command("init")
@click.pass_context
def init_cmd(ctx: click.Context) -> None:
    """Create databases, data directories, and an empty catalog manifest."""
    headnotes, fulltext = init_default_databases()
    ensure_catalog_dirs()
    if _ctx_json(ctx):
        emit_json(
            {
                "headnotes_db": str(headnotes),
                "fulltext_db": str(fulltext),
                "manifest": str(config.MANIFEST_PATH),
            }
        )
        return
    console.print(f"[green]ok[/]  headnotes db: {headnotes}")
    console.print(f"[green]ok[/]  fulltext  db: {fulltext}")
    console.print(f"[green]ok[/]  manifest:   {config.MANIFEST_PATH}")


# ── ingest ─────────────────────────────────────────────────────────────────


@cli.command("ingest")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.option("--force", is_flag=True, help="Re-parse even when SHA-256 is unchanged")
@click.option(
    "--criminal-only",
    is_flag=True,
    help="Skip cases that fail criminal-law curation rules",
)
@click.pass_context
def ingest_cmd(
    ctx: click.Context,
    paths: tuple[str, ...],
    force: bool,
    criminal_only: bool,
) -> None:
    """Parse HTML under PATHS and store cases via the dual-database router.

    With no PATHS, ingests ``data/cases/fulltext``, ``data/cases/headnotes``,
    and ``data/raw`` when those directories exist.
    """
    if paths:
        roots = [Path(p) for p in paths]
    else:
        roots = [
            config.CASES_DIR / "fulltext",
            config.CASES_DIR / "headnotes",
            config.RAW_DIR,
        ]
        roots = [r for r in roots if r.exists()]
        if not roots:
            raise click.UsageError(
                "no paths given and no default data/ directories found; "
                "run `criminal-db init` or pass explicit PATHS"
            )

    router = DatabaseRouter()
    try:
        report = ingest_paths(
            roots, router=router, force=force, criminal_only=criminal_only
        )
    finally:
        router.close()

    if _ctx_json(ctx):
        emit_json(report.to_dict())
        return
    parts = [
        f"[green]{report.ok} ok[/]",
        f"[yellow]{report.skipped} skipped[/]",
        f"[red]{report.failed} failed[/]",
    ]
    if report.excluded:
        parts.append(f"[dim]{report.excluded} excluded (non-criminal)[/]")
    console.print(", ".join(parts))


# ── catalog index ──────────────────────────────────────────────────────────


@cli.command("index")
@click.option(
    "--status",
    type=click.Choice(["pending", "ok", "failed", "skipped", "excluded"]),
    default=None,
)
@click.option("--court", default=None, help="Filter by substring in citation")
@click.pass_context
def index_cmd(
    ctx: click.Context,
    status: Optional[str],
    court: Optional[str],
) -> None:
    """List catalog manifest entries (ingest / harvest bookkeeping)."""
    ensure_catalog_dirs()
    manifest = Manifest.load()
    entries = manifest.list_entries(
        status=status,  # type: ignore[arg-type]
        court_substr=court,
    )
    if _ctx_json(ctx):
        emit_json(
            {
                "manifest": str(manifest.path),
                "count": len(entries),
                "entries": [e.to_dict() for e in entries],
            }
        )
        return
    if not entries:
        console.print("[yellow]no catalog entries[/]")
        return
    from rich.table import Table

    table = Table()
    table.add_column("status")
    table.add_column("citation")
    table.add_column("store")
    table.add_column("source")
    for e in entries:
        table.add_row(
            e.status,
            e.canlii_ref or "—",
            e.store or "—",
            e.source_path,
        )
    console.print(table)


# ── curate ─────────────────────────────────────────────────────────────────


@cli.command("curate")
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (default: both fulltext and headnotes)",
)
@click.pass_context
def curate_cmd(ctx: click.Context, db_path: Optional[str]) -> None:
    """Re-apply criminal-law curation rules to all stored cases.

    Edits ``data/index/overrides.yaml`` to force-include or exclude specific
    citations. Exclude entries take precedence over heuristics.
    """
    from .curation.apply import curate_database

    backend = _open_backend(db_path)
    try:
        if isinstance(backend, DatabaseRouter):
            payload = backend.curate_all()
        else:
            payload = {"single": curate_database(backend).to_dict()}
    finally:
        _close_backend(backend)

    if _ctx_json(ctx):
        emit_json(payload)
        return
    if isinstance(payload, dict) and "stores" in payload:
        for store, rep in payload.items():
            console.print(
                f"[bold]{store}[/]: {rep['criminal']} criminal, "
                f"{rep['excluded']} excluded / {rep['total']} total"
            )
    else:
        rep = payload["single"]
        console.print(
            f"{rep['criminal']} criminal, {rep['excluded']} excluded / "
            f"{rep['total']} total"
        )


# ── parse (offline) ────────────────────────────────────────────────────────


@cli.command("parse")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (bypasses dual-database router)",
)
@click.option(
    "--no-store",
    is_flag=True,
    help="Print the parsed JSON instead of storing it in the database",
)
@click.option("--catalog/--no-catalog", default=True, help="Update manifest.json")
@click.option(
    "--criminal-only",
    is_flag=True,
    help="Do not store cases that fail criminal-law curation rules",
)
@click.pass_context
def parse_cmd(
    ctx: click.Context,
    paths: tuple[str, ...],
    db_path: Optional[str],
    no_store: bool,
    catalog: bool,
    criminal_only: bool,
) -> None:
    """Parse CanLII HTML files that you've already downloaded."""
    if not paths:
        raise click.UsageError("at least one path is required")

    if no_store:
        from .catalog.ingest import collect_html_files

        rows: list[dict] = []
        for path in collect_html_files([Path(p) for p in paths]):
            html = path.read_text(encoding="utf-8", errors="replace")
            case = CanLIIParser(html, source_url=path.resolve().as_uri()).parse()
            rows.append(export_case_to_json(case))
        if _ctx_json(ctx):
            emit_json({"cases": rows, "count": len(rows)})
        else:
            for row in rows:
                console.print_json(data=row)
        return

    backend = _open_backend(db_path)
    parsed_ok = 0
    parsed_fail = 0
    results: list[dict] = []
    try:
        from .catalog.ingest import collect_html_files

        for path in collect_html_files([Path(p) for p in paths]):
            try:
                html = path.read_text(encoding="utf-8", errors="replace")
                case = CanLIIParser(
                    html, source_url=path.resolve().as_uri()
                ).parse()
                payload = export_case_to_json(case)
                if case.canlii_ref == "UNKNOWN":
                    if catalog:
                        _manifest_record_html(
                            path,
                            status="skipped",
                            parse_error="no citation detected",
                        )
                    parsed_fail += 1
                    results.append(
                        {"path": str(path), "status": "skipped", "error": "no citation"}
                    )
                    continue
                decision = classify_case(
                    payload["meta"], payload.get("paragraphs") or []
                )
                if criminal_only and not decision.is_criminal:
                    if catalog:
                        _manifest_record_html(
                            path,
                            status="excluded",
                            canlii_ref=case.canlii_ref,
                            parse_error=decision.reason,
                        )
                    parsed_fail += 1
                    results.append(
                        {
                            "path": str(path),
                            "status": "excluded",
                            "reason": decision.reason,
                        }
                    )
                    if not _ctx_json(ctx):
                        console.print(
                            f"[dim]exclude[/] {path.name}: {decision.reason}"
                        )
                    continue
                if isinstance(backend, DatabaseRouter):
                    case_id, store = backend.store_case(payload)
                else:
                    case_id = backend.store_case(payload)
                    store = case.corpus
                if catalog:
                    _manifest_record_html(
                        path,
                        status="ok",
                        canlii_ref=case.canlii_ref,
                        corpus=case.corpus,
                        case_id=case_id,
                        store=store,  # type: ignore[arg-type]
                        source_url=case.source_url,
                    )
                parsed_ok += 1
                results.append(
                    {
                        "path": str(path),
                        "status": "ok",
                        "canlii_ref": case.canlii_ref,
                        "case_id": case_id,
                        "store": store,
                        "paragraphs": len(case.paragraphs),
                    }
                )
                if not _ctx_json(ctx):
                    console.print(
                        f"[green]ok[/] {path.name} -> case_id={case_id} "
                        f"({case.canlii_ref}, {store}, {len(case.paragraphs)} paras)"
                    )
            except Exception as exc:
                if catalog:
                    _manifest_record_html(
                        path, status="failed", parse_error=str(exc)
                    )
                parsed_fail += 1
                results.append(
                    {"path": str(path), "status": "failed", "error": str(exc)}
                )
                if not _ctx_json(ctx):
                    console.print(f"[red]err[/] {path.name}: {exc}")
    finally:
        _close_backend(backend)

    if _ctx_json(ctx):
        emit_json({"ok": parsed_ok, "failed": parsed_fail, "results": results})
    else:
        console.print(
            f"\n[green]{parsed_ok} ok[/], [red]{parsed_fail} failed[/]."
        )


# ── harvest (online) ───────────────────────────────────────────────────────


@cli.command("harvest")
@click.argument("url")
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (bypasses dual-database router)",
)
@click.option(
    "--save-html",
    type=click.Path(file_okay=False, dir_okay=True),
    default=None,
    help="Directory to save raw HTML (also registers paths in the catalog)",
)
@click.option(
    "--listing/--single",
    default=False,
    help="Treat URL as a listing page and follow each case link",
)
@click.option("--limit", default=10, type=int, help="Max cases from a listing")
@click.pass_context
def harvest_cmd(
    ctx: click.Context,
    url: str,
    db_path: Optional[str],
    save_html: Optional[str],
    listing: bool,
    limit: int,
) -> None:
    """Fetch one or more cases from CanLII (subject to robots.txt)."""
    asyncio.run(
        _run_harvest(
            url,
            db_path=db_path,
            save_html=Path(save_html) if save_html else None,
            listing=listing,
            limit=limit,
            as_json=_ctx_json(ctx),
        )
    )


async def _run_harvest(
    url: str,
    *,
    db_path: Optional[str],
    save_html: Optional[Path],
    listing: bool,
    limit: int,
    as_json: bool,
) -> None:
    backend = _open_backend(db_path)
    harvested: list[dict] = []
    try:
        async with CanLIIFetcher() as fetcher:
            if not listing:
                row = await _harvest_single(
                    fetcher, url, backend=backend, save_html=save_html
                )
                if row:
                    harvested.append(row)
            else:
                if not as_json:
                    console.print(f"[cyan]listing[/] {url}")
                index = await fetcher.fetch(url)
                if index is None:
                    if as_json:
                        emit_json({"error": "failed to fetch listing", "harvested": []})
                    else:
                        console.print("[red]failed to fetch listing[/]")
                    return
                links = extract_case_links(index.html)[:limit]
                if save_html:
                    save_html.mkdir(parents=True, exist_ok=True)
                    index_path = save_html / "_index.html"
                    index_path.write_text(index.html, encoding="utf-8")
                    _manifest_record_html(index_path, status="skipped")
                if not as_json:
                    console.print(f"  found [bold]{len(links)}[/] case link(s)")
                for case_url in links:
                    row = await _harvest_single(
                        fetcher, case_url, backend=backend, save_html=save_html
                    )
                    if row:
                        harvested.append(row)
    finally:
        _close_backend(backend)

    if as_json:
        emit_json({"harvested": harvested, "count": len(harvested)})


async def _harvest_single(
    fetcher: CanLIIFetcher,
    url: str,
    *,
    backend: Backend,
    save_html: Optional[Path],
) -> Optional[dict]:
    console.print(f"[cyan]fetch[/] {url}")
    result = await fetcher.fetch(url)
    if result is None:
        console.print("[red]  failed[/]")
        return None
    case = CanLIIParser(result.html, source_url=url).parse()
    if case.canlii_ref == "UNKNOWN":
        console.print("[yellow]  no citation detected; not storing[/]")
        return None

    html_path: Optional[Path] = None
    if save_html:
        save_html.mkdir(parents=True, exist_ok=True)
        safe = case.canlii_ref.replace(" ", "_").replace("/", "_")
        html_path = save_html / f"{safe}.html"
        html_path.write_text(result.html, encoding="utf-8")

    if isinstance(backend, DatabaseRouter):
        case_id, store = backend.store_case(export_case_to_json(case))
    else:
        case_id = backend.store_case(export_case_to_json(case))
        store = case.corpus

    if html_path is not None:
        _manifest_record_html(
            html_path,
            status="ok",
            canlii_ref=case.canlii_ref,
            corpus=case.corpus,
            case_id=case_id,
            store=store,  # type: ignore[arg-type]
            source_url=url,
        )

    console.print(
        f"[green]  ok[/] {case.canlii_ref} -> case_id={case_id} "
        f"({len(case.paragraphs)} paras, {store})"
    )
    return {
        "url": url,
        "canlii_ref": case.canlii_ref,
        "case_id": case_id,
        "store": store,
        "paragraphs": len(case.paragraphs),
        "html_path": str(html_path) if html_path else None,
    }


# ── embed ──────────────────────────────────────────────────────────────────


@cli.command("embed")
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (default: embed both fulltext and headnotes)",
)
@click.option("--batch-size", default=None, type=int)
@click.option("--limit", default=None, type=int)
@click.pass_context
def embed_cmd(
    ctx: click.Context,
    db_path: Optional[str],
    batch_size: Optional[int],
    limit: Optional[int],
) -> None:
    """Compute embeddings for paragraphs that don't have one yet."""
    from .embedding import Embedder, chunked

    backend = _open_backend(db_path)
    as_json = _ctx_json(ctx)
    try:
        if isinstance(backend, Database):
            missing = [
                (pid, text, "fulltext")  # type: ignore[misc]
                for pid, text in backend.paragraphs_missing_embeddings(limit=limit)
            ]
        else:
            missing = backend.paragraphs_missing_embeddings(limit=limit)

        if not missing:
            if as_json:
                emit_json({"embedded": 0, "message": "all paragraphs already embedded"})
            else:
                console.print("[green]all paragraphs already embedded[/]")
            return

        if not as_json:
            console.print(f"[cyan]embedding[/] {len(missing)} paragraphs")
        embedder = Embedder()
        size = batch_size or config.EMBEDDING_BATCH_SIZE
        total = 0
        for batch in chunked(missing, size):
            if isinstance(backend, DatabaseRouter):
                ids = [pid for pid, _, _ in batch]
                texts = [text for _, text, _ in batch]
                vectors = embedder.encode(texts)
                items = [
                    (pid, vec, store)
                    for (pid, _, store), vec in zip(batch, vectors)
                ]
                backend.store_embeddings(items)
            else:
                ids = [pid for pid, _, _ in batch]
                texts = [text for _, text, _ in batch]
                vectors = embedder.encode(texts)
                backend.store_embeddings(zip(ids, vectors))
            total += len(batch)
            if not as_json:
                console.print(f"  +{len(batch)} ({total}/{len(missing)})")
        if as_json:
            emit_json({"embedded": total})
        else:
            console.print(f"[green]ok[/] embedded {total} paragraphs")
    finally:
        _close_backend(backend)


# ── search ─────────────────────────────────────────────────────────────────


@cli.command("search")
@click.argument("query")
@click.option(
    "--type",
    "search_type",
    type=click.Choice(["fts", "vector", "hybrid"], case_sensitive=False),
    default="fts",
)
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (default: search both databases)",
)
@click.option("--limit", "-n", default=config.DEFAULT_SEARCH_LIMIT, type=int)
@click.option("--offset", default=0, type=int, help="Skip this many merged hits")
@click.option("--court", default=None)
@click.option("--year", default=None, type=int)
@click.option(
    "--corpus",
    default=None,
    type=click.Choice(["fulltext", "headnote"], case_sensitive=False),
)
@click.option(
    "--include-all",
    is_flag=True,
    help="Include cases marked non-criminal by curation rules",
)
@click.pass_context
def search_cmd(
    ctx: click.Context,
    query: str,
    search_type: str,
    db_path: Optional[str],
    limit: int,
    offset: int,
    court: Optional[str],
    year: Optional[int],
    corpus: Optional[str],
    include_all: bool,
) -> None:
    """Search with FTS5, vector similarity, or hybrid fusion."""
    backend = _open_backend(db_path)
    as_json = _ctx_json(ctx)
    try:
        st = search_type.lower()
        common = dict(
            limit=limit,
            court=court,
            year=year,
            corpus=corpus,
            offset=offset,
            criminal_only=not include_all,
        )
        if isinstance(backend, DatabaseRouter):
            if st == "fts":
                results = backend.search_fts(query, **common)
            elif st == "vector":
                from .embedding import Embedder

                vector = Embedder().encode_one(query)
                results = backend.search_vector(vector, **common)
            else:
                from .embedding import Embedder

                vector = Embedder().encode_one(query)
                results = backend.search_hybrid(query, vector, **common)
        else:
            criminal_only = not include_all
            if st == "fts":
                results = backend.search_fts(
                    query,
                    limit=limit,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=criminal_only,
                )
            elif st == "vector":
                from .embedding import Embedder

                vector = Embedder().encode_one(query)
                results = backend.search_vector(
                    vector,
                    limit=limit,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=criminal_only,
                )
            else:
                from .embedding import Embedder

                vector = Embedder().encode_one(query)
                results = backend.search_hybrid(
                    query,
                    vector,
                    limit=limit,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=criminal_only,
                )
    finally:
        _close_backend(backend)

    print_search_results(
        results,
        as_json=as_json,
        meta={
            "query": query,
            "type": st,
            "limit": limit,
            "offset": offset,
            "corpus": corpus,
            "criminal_only": not include_all,
        },
    )


# ── get ────────────────────────────────────────────────────────────────────


@cli.command("get")
@click.argument("citation")
@click.option(
    "--format",
    "fmt",
    type=click.Choice(["json", "text"], case_sensitive=False),
    default="json",
    help="Output shape (default json for agents)",
)
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (default: search both databases)",
)
@click.option(
    "--include-all",
    is_flag=True,
    help="Allow retrieval of cases marked non-criminal",
)
@click.pass_context
def get_cmd(
    ctx: click.Context,
    citation: str,
    fmt: str,
    db_path: Optional[str],
    include_all: bool,
) -> None:
    """Retrieve a full case by neutral citation (e.g. ``2024 SCC 1``)."""
    ref = normalize_canlii_ref(citation)
    backend = _open_backend(db_path)
    as_json = _ctx_json(ctx) or fmt.lower() == "json"
    try:
        if isinstance(backend, DatabaseRouter):
            found = backend.get_case(ref, criminal_only=not include_all)
        else:
            case = backend.get_case(ref)
            if case and (include_all or case.get("is_criminal")):
                found = (case, "single")
            else:
                found = None
        if found is None:
            if as_json:
                emit_json({"error": "not_found", "citation": ref})
            else:
                console.print(f"[yellow]not found:[/] {ref}")
            raise SystemExit(1)
        case, store = found
        if as_json:
            emit_json(case_to_export_json(case, store=None if store == "single" else store))
            return
        console.print(format_case_text(case, store=None if store == "single" else store))
    finally:
        _close_backend(backend)


# ── export ─────────────────────────────────────────────────────────────────


@cli.command("export")
@click.option(
    "--output",
    "-o",
    type=click.Path(dir_okay=False),
    default="-",
    help="Write JSON array to FILE (default stdout)",
)
@click.option("--db", "db_path", default=None)
@click.option("--court", default=None)
@click.option("--year", default=None, type=int)
@click.option("--include-all", is_flag=True)
@click.pass_context
def export_cmd(
    ctx: click.Context,
    output: str,
    db_path: Optional[str],
    court: Optional[str],
    year: Optional[int],
    include_all: bool,
) -> None:
    """Export cases matching filters as a JSON array."""
    import json
    import sys

    backend = _open_backend(db_path)
    try:
        criminal_only = not include_all
        if isinstance(backend, DatabaseRouter):
            rows = backend.export_cases(
                court=court, year=year, criminal_only=criminal_only
            )
            payload = [
                case_to_export_json(c, store=s) for c, s in rows
            ]
        else:
            refs = backend.list_case_refs(
                court=court, year=year, criminal_only=criminal_only
            )
            payload = []
            for ref in refs:
                case = backend.get_case(ref)
                if case:
                    payload.append(case_to_export_json(case))
    finally:
        _close_backend(backend)

    text = json.dumps(
        {"count": len(payload), "cases": payload},
        ensure_ascii=False,
        indent=2,
    )
    if output == "-":
        sys.stdout.write(text + "\n")
    else:
        Path(output).write_text(text + "\n", encoding="utf-8")
        if not _ctx_json(ctx):
            console.print(f"[green]ok[/] wrote {len(payload)} cases to {output}")


# ── analyze ────────────────────────────────────────────────────────────────


@cli.command("analyze")
@click.option(
    "--db",
    "db_path",
    default=None,
    help="Single SQLite file (default: analyse both databases)",
)
@click.pass_context
def analyze_cmd(ctx: click.Context, db_path: Optional[str]) -> None:
    """Print database statistics."""
    backend = _open_backend(db_path)
    try:
        if isinstance(backend, DatabaseRouter):
            stats = backend.analyze()
        else:
            stats = {
                "stores": {
                    "single": {
                        "path": str(backend.db_path),
                        "cases": backend.case_count(),
                        "paragraphs": backend.paragraph_count(),
                        "ratio_paragraphs": backend.ratio_paragraph_count(),
                        "headnote_paragraphs": backend.headnote_paragraph_count(),
                        "embeddings": backend.embedding_count(),
                        "by_court": backend.court_distribution(),
                        "by_year": backend.year_distribution(),
                    }
                },
                "total": {
                    "cases": backend.case_count(),
                    "criminal_cases": backend.criminal_case_count(),
                    "excluded_cases": backend.excluded_case_count(),
                    "paragraphs": backend.paragraph_count(),
                    "ratio_paragraphs": backend.ratio_paragraph_count(),
                    "headnote_paragraphs": backend.headnote_paragraph_count(),
                    "embeddings": backend.embedding_count(),
                },
            }
            stats["stores"]["single"]["criminal_cases"] = backend.criminal_case_count()
            stats["stores"]["single"]["excluded_cases"] = backend.excluded_case_count()
        print_analyze(stats, as_json=_ctx_json(ctx))
    finally:
        _close_backend(backend)


def main() -> None:  # pragma: no cover
    cli(prog_name="criminal-db")


if __name__ == "__main__":  # pragma: no cover
    main()
