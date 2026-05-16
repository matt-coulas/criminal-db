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
    import_paths,
    ingest_paths,
)
from .catalog.markdown_export import export_markdown
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
    from .statutes.schema import init_statutes_db

    headnotes, fulltext = init_default_databases()
    statutes = init_statutes_db()
    ensure_catalog_dirs()
    config.CRIMINAL_CODE_DIR.mkdir(parents=True, exist_ok=True)
    if _ctx_json(ctx):
        emit_json(
            {
                "headnotes_db": str(headnotes),
                "fulltext_db": str(fulltext),
                "statutes_db": str(statutes),
                "manifest": str(config.MANIFEST_PATH),
                "import_dir": str(config.IMPORT_DIR),
                "cases_md_dir": str(config.CASES_MD_DIR),
            }
        )
        return
    console.print(f"[green]ok[/]  headnotes db: {headnotes}")
    console.print(f"[green]ok[/]  fulltext  db: {fulltext}")
    console.print(f"[green]ok[/]  statutes  db: {statutes}")
    console.print(f"[green]ok[/]  manifest:   {config.MANIFEST_PATH}")
    console.print(f"[green]ok[/]  import dir: {config.IMPORT_DIR}")
    console.print(f"[green]ok[/]  cases md:   {config.CASES_MD_DIR}")


@cli.command("seed-build")
@click.option(
    "-i",
    "--input",
    "input_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="HTML/PDF tree to ingest (default: fixtures/seed_corpus/incoming)",
)
@click.option(
    "-o",
    "--output",
    "db_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory for fulltext.db and headnotes.db (default: db/seed)",
)
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Catalog + markdown tree (default: data/seed)",
)
@click.option("--force", is_flag=True, help="Re-parse and replace existing seed DBs")
@click.option(
    "--criminal-only",
    is_flag=True,
    help="Skip cases that fail criminal-law curation rules",
)
@click.option("--no-md", is_flag=True, help="Do not write per-case markdown under data/")
@click.option(
    "--install",
    is_flag=True,
    help="After build, copy seed DB files into db/ (project default)",
)
@click.pass_context
def seed_build_cmd(
    ctx: click.Context,
    input_dir: Optional[Path],
    db_dir: Optional[Path],
    data_dir: Optional[Path],
    force: bool,
    criminal_only: bool,
    no_md: bool,
    install: bool,
) -> None:
    """Build a starter database from HTML/PDF for local dev, Docker, and tests."""
    from .seed import build_seed_database, install_seed_database

    root = config.BASE_DIR
    incoming = input_dir or (root / "fixtures" / "seed_corpus" / "incoming")
    try:
        result = build_seed_database(
            incoming,
            db_dir=db_dir,
            data_dir=data_dir,
            criminal_only=criminal_only,
            force=force,
            write_md=not no_md,
        )
    except (FileNotFoundError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    installed: list[Path] = []
    if install:
        installed = install_seed_database(result.db_dir)

    if _ctx_json(ctx):
        payload = result.to_dict()
        if installed:
            payload["installed"] = [str(p) for p in installed]
        emit_json(payload)
        return

    parts = []
    if result.html_files:
        parts.append(f"{result.html_files} HTML")
    if result.pdf_files:
        parts.append(f"{result.pdf_files} PDF")
    label = " + ".join(parts) if parts else "0"
    console.print(f"[green]ok[/]  {result.report.ok} case(s) from {label} file(s)")
    if result.report.skipped:
        console.print(f"[yellow]skipped[/] {result.report.skipped}")
    if result.report.failed:
        console.print(f"[red]failed[/] {result.report.failed}")
    if result.report.excluded:
        console.print(f"[dim]excluded[/] {result.report.excluded}")
    console.print(f"[green]ok[/]  fulltext:  {result.fulltext_db}")
    console.print(f"[green]ok[/]  headnotes: {result.headnotes_db}")
    console.print(f"[green]ok[/]  manifest:  {result.manifest_path}")
    if installed:
        for p in installed:
            console.print(f"[green]ok[/]  installed: {p}")


# ── validate ───────────────────────────────────────────────────────────────


@cli.command("validate")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.pass_context
def validate_cmd(ctx: click.Context, paths: tuple[str, ...]) -> None:
    """Dry-run parser QA on HTML files (no database writes).

    Use on saved CanLII or import HTML before ``ingest`` / ``import``.
    """
    from .validate import validate_paths

    if not paths:
        raise click.UsageError("at least one path is required")
    results = validate_paths([Path(p) for p in paths])
    if _ctx_json(ctx):
        emit_json(
            {
                "count": len(results),
                "ok": sum(1 for r in results if r.ok),
                "failed": sum(1 for r in results if not r.ok),
                "files": [r.to_dict() for r in results],
            }
        )
        if any(not r.ok for r in results):
            raise SystemExit(1)
        return
    for r in results:
        flag = "[green]ok[/]" if r.ok else "[red]fail[/]"
        console.print(
            f"{flag} {r.path}: {r.canlii_ref} ({r.paragraph_count} paras, {r.corpus})"
        )
        for issue in r.issues:
            colour = "red" if issue.level == "error" else "yellow"
            console.print(f"  [{colour}]{issue.code}[/] {issue.message}")
    failed = sum(1 for r in results if not r.ok)
    if failed:
        raise SystemExit(1)


# ── verify (DB / catalog) ──────────────────────────────────────────────────


@cli.command("verify")
@click.option(
    "--no-statutes",
    is_flag=True,
    help="Skip statutes database checks",
)
@click.pass_context
def verify_cmd(ctx: click.Context, no_statutes: bool) -> None:
    """Check manifest ↔ database consistency and FTS index drift."""
    from .verify import run_verify

    report = run_verify(include_statutes=not no_statutes)
    if _ctx_json(ctx):
        emit_json(report.to_dict())
        if not report.ok:
            raise SystemExit(1)
        return
    for issue in report.issues:
        colour = {"error": "red", "warning": "yellow", "info": "cyan"}.get(
            issue.level, "white"
        )
        console.print(f"[{colour}]{issue.level}[/] {issue.code}: {issue.message}")
    if report.ok:
        console.print("[green]ok[/] verification passed")
    else:
        console.print("[red]failed[/] verification found errors")
        raise SystemExit(1)


# ── backup / restore ───────────────────────────────────────────────────────


@cli.command("backup")
@click.argument(
    "destination",
    required=False,
    type=click.Path(dir_okay=True, file_okay=True),
)
@click.option("--no-statutes", is_flag=True, help="Omit statutes.db from archive")
@click.pass_context
def backup_cmd(
    ctx: click.Context, destination: Optional[str], no_statutes: bool
) -> None:
    """Create a .tar.gz of local databases and catalog metadata."""
    from .ops.backup import backup_data

    dest = Path(destination) if destination else config.DB_DIR / "backups"
    archive = backup_data(dest, include_statutes=not no_statutes)
    if _ctx_json(ctx):
        emit_json({"archive": str(archive)})
    else:
        console.print(f"[green]ok[/] wrote {archive}")


@cli.command("restore")
@click.argument("archive", type=click.Path(exists=True, dir_okay=False))
@click.pass_context
def restore_cmd(ctx: click.Context, archive: str) -> None:
    """Restore databases and catalog files from a backup archive."""
    from .ops.backup import restore_data

    paths = restore_data(Path(archive))
    if _ctx_json(ctx):
        emit_json({"restored": [str(p) for p in paths]})
    else:
        for p in paths:
            console.print(f"[green]ok[/] restored {p}")


@cli.command("tui")
def tui_cmd() -> None:
    """Interactive terminal menu (requires ``criminal-db[tui]``)."""
    try:
        from .tui import run_tui
    except ImportError as exc:
        raise click.ClickException(
            "TUI dependencies missing. Install with: pip install 'criminal-db[tui]'"
        ) from exc
    run_tui()


@cli.command("serve")
@click.option("--host", default=None, help=f"Bind host (default: {config.API_HOST})")
@click.option("--port", default=None, type=int, help="Bind port")
@click.pass_context
def serve_cmd(ctx: click.Context, host: Optional[str], port: Optional[int]) -> None:
    """Run a local JSON HTTP API for search and get (localhost by default)."""
    from .server import serve

    if _ctx_json(ctx):
        raise click.UsageError("serve does not support --json")
    h = host or config.API_HOST
    p = port or config.API_PORT
    console.print(f"[cyan]listening[/] http://{h}:{p}/  (Ctrl+C to stop)")
    if config.API_TOKEN:
        console.print("[dim]API token required (Authorization: Bearer …)[/]")
    serve(host=h, port=p)


# ── ingest ─────────────────────────────────────────────────────────────────


@cli.command("ingest")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.option("--force", is_flag=True, help="Re-parse even when SHA-256 is unchanged")
@click.option(
    "--criminal-only",
    is_flag=True,
    help="Skip cases that fail criminal-law curation rules",
)
@click.option(
    "--no-md",
    is_flag=True,
    help="Do not write data/cases/md/*.md files when storing cases",
)
@click.pass_context
def ingest_cmd(
    ctx: click.Context,
    paths: tuple[str, ...],
    force: bool,
    criminal_only: bool,
    no_md: bool,
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
            roots,
            router=router,
            force=force,
            criminal_only=criminal_only,
            write_md=not no_md,
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


# ── import ─────────────────────────────────────────────────────────────────


@cli.command("import")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.option("--force", is_flag=True, help="Re-parse even when SHA-256 is unchanged")
@click.option(
    "--criminal-only",
    is_flag=True,
    help="Skip cases that fail criminal-law curation rules",
)
@click.option(
    "--no-md",
    is_flag=True,
    help="Do not write data/cases/md/*.md files when storing cases",
)
@click.pass_context
def import_cmd(
    ctx: click.Context,
    paths: tuple[str, ...],
    force: bool,
    criminal_only: bool,
    no_md: bool,
) -> None:
    """Import saved HTML or PDF decisions (no CanLII scraping).

    With no PATHS, imports everything under ``data/import/`` (html/ and pdf/).
    Originals are staged under ``data/import/`` when given paths elsewhere.
    """
    if paths:
        roots = [Path(p) for p in paths]
    else:
        roots = [config.IMPORT_DIR]
        if not roots[0].exists():
            raise click.UsageError(
                "no paths given and data/import/ does not exist; "
                "run `criminal-db init` or pass explicit PATHS"
            )

    router = DatabaseRouter()
    try:
        report = import_paths(
            roots,
            router=router,
            force=force,
            criminal_only=criminal_only,
            write_md=not no_md,
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
@click.option(
    "--report",
    is_flag=True,
    help="Print excluded and borderline cases for manual QA review",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="With --report, classify without updating is_criminal in the database",
)
@click.pass_context
def curate_cmd(
    ctx: click.Context,
    db_path: Optional[str],
    report: bool,
    dry_run: bool,
) -> None:
    """Re-apply criminal-law curation rules to all stored cases.

    Edits ``data/index/overrides.yaml`` to force-include or exclude specific
    citations. Exclude entries take precedence over heuristics.

    Use ``--report`` to list excluded cases and borderline hits (possible false
  positives/negatives). Add ``--dry-run`` to preview without writing flags.
    """
    backend = _open_backend(db_path)
    as_json = _ctx_json(ctx)
    apply = not (report and dry_run)
    try:
        if report:
            from .curation.report import audit_database, audit_router

            if isinstance(backend, DatabaseRouter):
                payload = audit_router(backend, apply=apply)
            else:
                rep = audit_database(backend, store="single", apply=apply)
                payload = {
                    "stores": {"single": rep.to_dict()},
                    "total": {
                        "total": rep.total,
                        "criminal": rep.criminal,
                        "excluded": rep.excluded,
                        "borderline_excluded": rep.borderline_excluded,
                        "borderline_included": rep.borderline_included,
                        "status_changed": rep.status_changed,
                    },
                    "override_include": rep.override_include,
                    "override_exclude": rep.override_exclude,
                    "applied": apply,
                }
        else:
            from .curation.apply import curate_database

            if isinstance(backend, DatabaseRouter):
                payload = backend.curate_all()
            else:
                payload = {"single": curate_database(backend).to_dict()}
    finally:
        _close_backend(backend)

    if as_json:
        emit_json(payload)
        return

    if report:
        _print_curation_qa_report(payload, applied=apply)
        return

    if isinstance(payload, dict) and "stores" in payload and "total" not in payload:
        for store, rep in payload.items():
            console.print(
                f"[bold]{store}[/]: {rep['criminal']} criminal, "
                f"{rep['excluded']} excluded / {rep['total']} total"
            )
    else:
        rep = payload.get("single", payload)
        console.print(
            f"{rep['criminal']} criminal, {rep['excluded']} excluded / "
            f"{rep['total']} total"
        )


def _print_curation_qa_report(payload: dict, *, applied: bool) -> None:
    """Rich tables for ``curate --report``."""
    from rich.table import Table

    totals = payload.get("total", {})
    mode = "applied" if applied else "dry-run (no DB writes)"
    console.print(
        f"[bold]Curation QA[/] ({mode}): "
        f"{totals.get('criminal', 0)} criminal, "
        f"{totals.get('excluded', 0)} excluded / {totals.get('total', 0)} total"
    )
    console.print(
        f"  borderline excluded (review for include): "
        f"{totals.get('borderline_excluded', 0)}"
    )
    console.print(
        f"  borderline included (review for exclude): "
        f"{totals.get('borderline_included', 0)}"
    )
    if totals.get("status_changed"):
        console.print(
            f"  [yellow]status changed:[/] {totals['status_changed']} case(s)"
        )
    inc = payload.get("override_include") or []
    exc = payload.get("override_exclude") or []
    if inc:
        console.print(f"  override include: {', '.join(inc)}")
    if exc:
        console.print(f"  override exclude: {', '.join(exc)}")

    stores = payload.get("stores", {})
    for store_name, store in stores.items():
        if not isinstance(store, dict):
            continue
        borderline = store.get("borderline_cases") or []
        excluded = store.get("excluded_cases") or []
        changes = store.get("status_changes") or []
        if not borderline and not excluded and not changes:
            continue
        console.print(f"\n[bold underline]{store_name}[/]")

        if changes:
            table = Table(title="Status changes")
            table.add_column("citation")
            table.add_column("was")
            table.add_column("now")
            table.add_column("reason")
            for row in changes:
                was = "criminal" if row.get("previous_is_criminal") else "excluded"
                now = "criminal" if row.get("is_criminal") else "excluded"
                table.add_row(
                    row["canlii_ref"],
                    was,
                    now,
                    row["reason"],
                )
            console.print(table)

        if borderline:
            table = Table(title="Borderline (manual review)")
            table.add_column("citation")
            table.add_column("kind")
            table.add_column("court")
            table.add_column("decision")
            table.add_column("reason")
            for row in borderline:
                decision = "criminal" if row.get("is_criminal") else "excluded"
                table.add_row(
                    row["canlii_ref"],
                    row.get("borderline_kind") or "—",
                    row.get("court_code") or row.get("court") or "—",
                    decision,
                    row["reason"],
                )
            console.print(table)

        if excluded and len(excluded) <= 40:
            table = Table(title="Excluded")
            table.add_column("citation")
            table.add_column("court")
            table.add_column("reason")
            for row in excluded:
                table.add_row(
                    row["canlii_ref"],
                    row.get("court_code") or row.get("court") or "—",
                    row["reason"],
                )
            console.print(table)
        elif excluded:
            console.print(
                f"  excluded: {len(excluded)} cases "
                f"(use --json for full list)"
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
@click.option(
    "--no-md",
    is_flag=True,
    help="Do not write data/cases/md/*.md files when storing cases",
)
@click.pass_context
def parse_cmd(
    ctx: click.Context,
    paths: tuple[str, ...],
    db_path: Optional[str],
    no_store: bool,
    catalog: bool,
    criminal_only: bool,
    no_md: bool,
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
                write_md = not no_md
                if isinstance(backend, DatabaseRouter):
                    case_id, store = backend.store_case(
                        payload, write_md=write_md
                    )
                else:
                    case_id = backend.store_case(payload, write_md=write_md)
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
@click.option(
    "--no-md",
    is_flag=True,
    help="Do not write data/cases/md/*.md files when storing cases",
)
@click.pass_context
def harvest_cmd(
    ctx: click.Context,
    url: str,
    db_path: Optional[str],
    save_html: Optional[str],
    listing: bool,
    limit: int,
    no_md: bool,
) -> None:
    """Fetch one or more cases from CanLII (subject to robots.txt)."""
    asyncio.run(
        _run_harvest(
            url,
            db_path=db_path,
            save_html=Path(save_html) if save_html else None,
            listing=listing,
            limit=limit,
            write_md=not no_md,
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
    write_md: bool = True,
    as_json: bool,
) -> None:
    backend = _open_backend(db_path)
    harvested: list[dict] = []
    try:
        async with CanLIIFetcher() as fetcher:
            if not listing:
                row = await _harvest_single(
                    fetcher,
                    url,
                    backend=backend,
                    save_html=save_html,
                    write_md=write_md,
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
                        fetcher,
                        case_url,
                        backend=backend,
                        save_html=save_html,
                        write_md=write_md,
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
    write_md: bool = True,
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

    payload = export_case_to_json(case)
    if isinstance(backend, DatabaseRouter):
        case_id, store = backend.store_case(payload, write_md=write_md)
    else:
        case_id = backend.store_case(payload, write_md=write_md)
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
@click.option(
    "--scope",
    type=click.Choice(["cases", "statutes", "all"], case_sensitive=False),
    default="cases",
    help="Embed case paragraphs, statute sections, or both",
)
@click.option("--batch-size", default=None, type=int)
@click.option("--limit", default=None, type=int)
@click.pass_context
def embed_cmd(
    ctx: click.Context,
    db_path: Optional[str],
    scope: str,
    batch_size: Optional[int],
    limit: Optional[int],
) -> None:
    """Compute embeddings for paragraphs or sections missing vectors."""
    from .embedding import Embedder, chunked
    from .statutes import StatutesDatabase

    as_json = _ctx_json(ctx)
    sc = scope.lower()
    total = 0

    def _embed_statutes() -> int:
        db = StatutesDatabase()
        try:
            missing = db.sections_missing_embeddings(limit=limit)
            if not missing:
                return 0
            if not as_json:
                console.print(f"[cyan]embedding[/] {len(missing)} statute sections")
            embedder = Embedder()
            size = batch_size or config.EMBEDDING_BATCH_SIZE
            written = 0
            for batch in chunked(missing, size):
                ids = [sid for sid, _ in batch]
                texts = [text for _, text in batch]
                vectors = embedder.encode(texts)
                db.store_embeddings(list(zip(ids, vectors)))
                written += len(batch)
                if not as_json:
                    console.print(f"  +{len(batch)} ({written}/{len(missing)})")
            return written
        finally:
            db.close()

    if sc in ("statutes", "all"):
        total += _embed_statutes()
    if sc == "statutes":
        if as_json:
            emit_json({"embedded": total, "scope": "statutes"})
        elif total == 0:
            console.print("[green]all statute sections already embedded[/]")
        else:
            console.print(f"[green]ok[/] embedded {total} statute sections")
        return
    if sc == "all" and db_path:
        raise click.UsageError("--db applies to case stores only; omit for --scope all")

    backend = _open_backend(db_path)
    try:
        if isinstance(backend, Database):
            missing = [
                (pid, text, "fulltext")  # type: ignore[misc]
                for pid, text in backend.paragraphs_missing_embeddings(limit=limit)
            ]
        else:
            missing = backend.paragraphs_missing_embeddings(limit=limit)

        if not missing and sc == "cases":
            if as_json:
                emit_json({"embedded": total, "scope": "cases"})
            else:
                console.print("[green]all paragraphs already embedded[/]")
            return

        if missing:
            if not as_json:
                console.print(f"[cyan]embedding[/] {len(missing)} paragraphs")
            embedder = Embedder()
            size = batch_size or config.EMBEDDING_BATCH_SIZE
            case_total = 0
            for batch in chunked(missing, size):
                if isinstance(backend, DatabaseRouter):
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
                case_total += len(batch)
                if not as_json:
                    console.print(f"  +{len(batch)} ({case_total}/{len(missing)})")
            total += case_total
        if sc == "all":
            total += _embed_statutes()
        if as_json:
            emit_json({"embedded": total, "scope": sc})
        elif total:
            console.print(f"[green]ok[/] embedded {total} item(s)")
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
@click.option(
    "--scope",
    type=click.Choice(["cases", "statutes", "all"], case_sensitive=False),
    default="cases",
    help="Search case law, Criminal Code sections, or both (FTS/hybrid)",
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
    scope: str,
) -> None:
    """Search with FTS5, vector similarity, or hybrid fusion."""
    as_json = _ctx_json(ctx)
    sc = scope.lower()
    st = search_type.lower()

    if sc == "all":
        if st == "vector":
            raise click.UsageError("scope=all supports --type fts or hybrid only")
        from .search_unified import search_all_fts, search_all_hybrid
        from .statutes import StatutesDatabase

        router = _open_backend(db_path)
        if not isinstance(router, DatabaseRouter):
            raise click.UsageError("scope=all requires default dual-database layout")
        statutes_db = StatutesDatabase()
        try:
            if st == "hybrid":
                from .embedding import Embedder

                vec = Embedder().encode_one(query)
                hits = search_all_hybrid(
                    query,
                    vec,
                    router=router,
                    statutes=statutes_db,
                    limit=limit,
                    offset=offset,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=not include_all,
                )
            else:
                hits = search_all_fts(
                    query,
                    router=router,
                    statutes=statutes_db,
                    limit=limit,
                    offset=offset,
                    court=court,
                    year=year,
                    corpus=corpus,
                    criminal_only=not include_all,
                )
        finally:
            statutes_db.close()
            _close_backend(router)
        if as_json:
            emit_json(
                {
                    "query": query,
                    "scope": "all",
                    "type": st,
                    "results": [h.to_dict() for h in hits],
                    "count": len(hits),
                }
            )
        elif not hits:
            console.print("[yellow]no results[/]")
        else:
            from rich.table import Table

            table = Table()
            table.add_column("kind")
            table.add_column("ref")
            table.add_column("score", justify="right")
            table.add_column("excerpt")
            for h in hits:
                if h.kind == "case" and h.case:
                    ref = h.case.canlii_ref
                    text = h.case.text
                elif h.statute:
                    ref = f"s. {h.statute.section_number}"
                    text = h.statute.text
                else:
                    ref = "—"
                    text = ""
                excerpt = text if len(text) <= 120 else text[:117] + "..."
                table.add_row(h.kind, ref, f"{h.score:.3f}", excerpt)
            console.print(table)
        return

    if sc == "statutes":
        from .statutes import StatutesDatabase

        db = StatutesDatabase()
        try:
            if st == "fts":
                results = db.search_fts(query, limit=limit)
            elif st == "vector":
                from .embedding import Embedder

                vec = Embedder().encode_one(query)
                results = db.search_vector(vec, limit=limit)
            elif st == "hybrid":
                from .embedding import Embedder

                vec = Embedder().encode_one(query)
                results = db.search_hybrid(query, vec, limit=limit)
            else:
                raise click.UsageError(f"unknown search type: {search_type}")
        finally:
            db.close()
        if as_json:
            emit_json(
                {
                    "query": query,
                    "scope": "statutes",
                    "results": [
                        {
                            "section": r.section_number,
                            "heading": r.heading,
                            "text": r.text,
                            "score": r.score,
                        }
                        for r in results
                    ],
                    "count": len(results),
                }
            )
        elif not results:
            console.print("[yellow]no results[/]")
        else:
            from rich.table import Table

            table = Table()
            table.add_column("s.")
            table.add_column("heading")
            table.add_column("score", justify="right")
            table.add_column("excerpt")
            for r in results:
                excerpt = r.text if len(r.text) <= 160 else r.text[:157] + "..."
                table.add_row(
                    r.section_number,
                    r.heading or "—",
                    f"{r.score:.3f}",
                    excerpt,
                )
            console.print(table)
        return

    backend = _open_backend(db_path)
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


@cli.command("export-md")
@click.option(
    "--output",
    "-o",
    type=click.Path(file_okay=False, dir_okay=True),
    default=None,
    help=f"Directory for .md files (default: {config.CASES_MD_DIR})",
)
@click.option("--db", "db_path", default=None)
@click.option("--court", default=None)
@click.option("--year", default=None, type=int)
@click.option("--include-all", is_flag=True)
@click.pass_context
def export_md_cmd(
    ctx: click.Context,
    output: Optional[str],
    db_path: Optional[str],
    court: Optional[str],
    year: Optional[int],
    include_all: bool,
) -> None:
    """Export cases from the database(s) as one Markdown file per decision."""
    out_dir = Path(output) if output else config.CASES_MD_DIR
    backend = _open_backend(db_path)
    try:
        count = export_markdown(
            backend,
            out_dir,
            court=court,
            year=year,
            criminal_only=not include_all,
        )
    finally:
        _close_backend(backend)

    if _ctx_json(ctx):
        emit_json({"count": count, "output_dir": str(out_dir)})
        return
    console.print(f"[green]ok[/] wrote {count} markdown file(s) to {out_dir}")


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


# ── statutes (Criminal Code) ───────────────────────────────────────────────


@cli.group()
def statutes() -> None:
    """Criminal Code sections from Justice Canada HTML."""


@statutes.command("parse")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=True))
@click.pass_context
def statutes_parse_cmd(ctx: click.Context, paths: tuple[str, ...]) -> None:
    """Parse Justice Canada HTML files into ``db/statutes.db``.

    Save offline copies under ``data/statutes/criminal_code/`` then run
    ``criminal-db statutes parse`` with no paths to ingest that directory.
    """
    from .catalog.ingest import collect_html_files
    from .statutes import JusticeCanadaParser, StatutesDatabase

    if paths:
        roots = [Path(p) for p in paths]
    else:
        roots = [config.CRIMINAL_CODE_DIR]
        if not roots[0].exists():
            raise click.UsageError(
                "no paths given and data/statutes/criminal_code/ is missing; "
                "run criminal-db init and add HTML files"
            )

    db = StatutesDatabase()
    total = 0
    files_ok = 0
    try:
        for path in collect_html_files(roots):
            html = path.read_text(encoding="utf-8", errors="replace")
            sections = JusticeCanadaParser(html).parse()
            if not sections:
                if not _ctx_json(ctx):
                    console.print(f"[yellow]skip[/] {path.name}: no sections")
                continue
            n = db.store_sections(sections)
            total += n
            files_ok += 1
            if not _ctx_json(ctx):
                console.print(f"[green]ok[/] {path.name}: {n} sections")
    finally:
        db.close()

    if _ctx_json(ctx):
        emit_json({"files": files_ok, "sections_stored": total})
    else:
        console.print(f"[green]ok[/] {total} sections from {files_ok} file(s)")


@statutes.command("get")
@click.argument("section")
@click.pass_context
def statutes_get_cmd(ctx: click.Context, section: str) -> None:
    """Retrieve one Criminal Code section by number (e.g. ``8`` or ``s. 8``)."""
    from .statutes import StatutesDatabase, normalize_section_ref

    db = StatutesDatabase()
    try:
        row = db.get_section(section)
    finally:
        db.close()
    ref = normalize_section_ref(section)
    if row is None:
        if _ctx_json(ctx):
            emit_json({"error": "not_found", "section": ref})
        else:
            console.print(f"[yellow]not found:[/] s. {ref}")
        raise SystemExit(1)
    if _ctx_json(ctx):
        emit_json(dict(row))
    else:
        console.print(f"[bold]s. {row['section_number']}[/] {row.get('heading') or ''}")
        console.print(row["text"])


@statutes.command("search")
@click.argument("query")
@click.option("-n", "--limit", default=config.DEFAULT_SEARCH_LIMIT, type=int)
@click.pass_context
def statutes_search_cmd(ctx: click.Context, query: str, limit: int) -> None:
    """FTS search over Criminal Code section text."""
    from .statutes import StatutesDatabase

    db = StatutesDatabase()
    try:
        results = db.search_fts(query, limit=limit)
    finally:
        db.close()
    if _ctx_json(ctx):
        emit_json(
            {
                "query": query,
                "results": [
                    {
                        "section": r.section_number,
                        "heading": r.heading,
                        "text": r.text,
                        "score": r.score,
                    }
                    for r in results
                ],
                "count": len(results),
            }
        )
        return
    if not results:
        console.print("[yellow]no results[/]")
        return
    from rich.table import Table

    table = Table()
    table.add_column("s.")
    table.add_column("heading")
    table.add_column("score", justify="right")
    for r in results:
        table.add_row(r.section_number, r.heading or "—", f"{r.score:.3f}")
    console.print(table)


@statutes.command("analyze")
@click.pass_context
def statutes_analyze_cmd(ctx: click.Context) -> None:
    """Print Criminal Code corpus statistics."""
    from .statutes import StatutesDatabase

    db = StatutesDatabase()
    try:
        count = db.section_count()
    finally:
        db.close()
    if _ctx_json(ctx):
        emit_json({"sections": count, "db": str(config.STATUTES_DB)})
    else:
        console.print(f"[bold]sections:[/] {count}")
        console.print(f"  db: {config.STATUTES_DB}")


def main() -> None:  # pragma: no cover
    cli(prog_name="criminal-db")


if __name__ == "__main__":  # pragma: no cover
    main()
