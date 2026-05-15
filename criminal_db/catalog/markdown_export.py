"""Write per-case Markdown files derived from stored paragraph text."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

from .. import config
from ..db.operations import Database
from ..db.router import DatabaseRouter
from ..retrieval import format_case_markdown, normalize_canlii_ref

PathLike = Union[str, Path]
Backend = Union[Database, DatabaseRouter]


def case_markdown_filename(canlii_ref: str) -> str:
    safe = canlii_ref.replace(" ", "_").replace("/", "_")
    return f"{safe}.md"


def markdown_path_for_ref(
    canlii_ref: str, *, output_dir: Optional[PathLike] = None
) -> Path:
    root = Path(output_dir or config.CASES_MD_DIR)
    return root / case_markdown_filename(canlii_ref)


def write_case_markdown_file(
    case: dict,
    *,
    store: Optional[str] = None,
    output_dir: Optional[PathLike] = None,
) -> Path:
    """Write one case dict (from :meth:`Database.get_case`) to a ``.md`` file."""
    ref = case.get("canlii_ref") or "UNKNOWN"
    out_dir = Path(output_dir or config.CASES_MD_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / case_markdown_filename(ref)
    path.write_text(format_case_markdown(case, store=store), encoding="utf-8")
    return path


def export_markdown(
    backend: Backend,
    output_dir: PathLike,
    *,
    court: Optional[str] = None,
    year: Optional[int] = None,
    criminal_only: bool = True,
) -> int:
    """Export all matching cases from the database(s) to ``output_dir``."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    if isinstance(backend, DatabaseRouter):
        rows = backend.export_cases(
            court=court, year=year, criminal_only=criminal_only
        )
        for case, store in rows:
            write_case_markdown_file(case, store=store, output_dir=out)
            count += 1
    else:
        for ref in backend.list_case_refs(
            court=court, year=year, criminal_only=criminal_only
        ):
            case = backend.get_case(normalize_canlii_ref(ref))
            if not case:
                continue
            store = (
                "headnotes"
                if case.get("corpus") == "headnote"
                else "fulltext"
            )
            write_case_markdown_file(case, store=store, output_dir=out)
            count += 1
    return count
