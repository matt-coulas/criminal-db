"""Human tables and machine-readable JSON for CLI commands."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from typing import Any, Optional

from rich.console import Console
from rich.table import Table

from .db.operations import SearchResult

console = Console()


def emit_json(payload: Any) -> None:
    """Write JSON to stdout (for agents and scripts)."""
    json.dump(payload, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    sys.stdout.flush()


def search_result_dict(r: SearchResult) -> dict[str, Any]:
    d = asdict(r)
    return d


def print_search_results(
    results: list[SearchResult],
    *,
    as_json: bool,
    meta: Optional[dict[str, Any]] = None,
) -> None:
    if as_json:
        payload = dict(meta or {})
        payload["results"] = [search_result_dict(r) for r in results]
        payload["count"] = len(results)
        emit_json(payload)
        return
    if not results:
        console.print("[yellow]no results[/]")
        return
    table = Table(show_lines=True)
    table.add_column("#", justify="right", style="dim")
    table.add_column("citation", style="cyan")
    table.add_column("store", style="dim")
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
            r.store,
            para,
            f"{r.court or '—'}\n{r.decided_date or '—'}",
            f"{r.score:.3f}",
            excerpt,
        )
    console.print(table)


def print_analyze(stats: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        emit_json(stats)
        return
    total = stats["total"]
    console.print(f"[bold]cases (total):[/]     {total['cases']}")
    console.print(f"[bold]paragraphs (total):[/] {total['paragraphs']}")
    console.print(f"  ratio:       {total['ratio_paragraphs']}")
    console.print(f"  headnote:    {total['headnote_paragraphs']}")
    console.print(f"  embeddings:  {total['embeddings']}/{total['paragraphs']}")
    for store, s in stats["stores"].items():
        console.print(f"\n[bold]{store}[/] ({s['path']})")
        console.print(f"  cases: {s['cases']}  paragraphs: {s['paragraphs']}")
        if s["by_court"]:
            table = Table()
            table.add_column("court")
            table.add_column("n", justify="right")
            for name, n in sorted(s["by_court"].items(), key=lambda kv: -kv[1]):
                table.add_row(name, str(n))
            console.print(table)
