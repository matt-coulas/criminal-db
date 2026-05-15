"""Extract decision text from PDFs and wrap as CanLII-style HTML."""

from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Optional

from ..harvester.parser import _CITATION_RE, _clean

_PARA_NUM_RE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d+)\]|(?P<dot>\d+)\.)\s*(?P<rest>.*)$",
)


def _require_pymupdf():
    try:
        import fitz  # type: ignore[import-untyped]  # PyMuPDF
    except ImportError as exc:
        raise ImportError(
            "PDF import requires PyMuPDF. Install with: pip install 'criminal-db[pdf]'"
        ) from exc
    return fitz


def extract_pdf_page_texts(path: Path) -> list[str]:
    """Return stripped text for each page (empty pages omitted)."""
    fitz = _require_pymupdf()
    doc = fitz.open(path)
    try:
        pages: list[str] = []
        for page in doc:
            text = (page.get_text("text") or "").strip()
            if text:
                pages.append(text)
        return pages
    finally:
        doc.close()


def extract_citation_from_text(text: str) -> Optional[str]:
    """Find the first neutral citation in *text*."""
    m = _CITATION_RE.search(_clean(text))
    if m:
        return f"{m.group('year')} {m.group('court')} {m.group('num')}"
    return None


def detect_paragraphs(full_text: str) -> list[tuple[Optional[int], str]]:
    """Split decision text into numbered paragraphs when possible."""
    text = (full_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    lines = text.split("\n")
    blocks: list[tuple[Optional[int], str]] = []
    current_num: Optional[int] = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_num, current_lines
        if not current_lines:
            return
        body = _clean(" ".join(current_lines))
        if body:
            blocks.append((current_num, body))
        current_num = None
        current_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_lines:
                _flush()
            continue
        m = _PARA_NUM_RE.match(stripped)
        if m:
            _flush()
            num_s = m.group("bracket") or m.group("dot")
            current_num = int(num_s) if num_s else None
            rest = (m.group("rest") or "").strip()
            if rest:
                current_lines.append(rest)
            continue
        current_lines.append(stripped)

    _flush()

    if blocks:
        return blocks

    chunks = [c.strip() for c in re.split(r"\n\s*\n", text) if c.strip()]
    if len(chunks) <= 1 and chunks:
        chunks = [
            s.strip()
            for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", chunks[0])
            if s.strip()
        ]
    return [(i + 1 if len(chunks) > 1 else None, _clean(c)) for i, c in enumerate(chunks)]


def pdf_to_canlii_html(path: Path) -> tuple[str, Optional[str]]:
    """Build minimal CanLII-style HTML from a PDF decision."""
    pages = extract_pdf_page_texts(path)
    full_text = "\n\n".join(pages)
    citation = extract_citation_from_text(
        "\n".join(pages[:2]) if pages else full_text
    )
    paragraphs = detect_paragraphs(full_text)

    title = citation or path.stem
    parts = [
        "<!doctype html>",
        '<html lang="en"><head>',
        f"<title>{html.escape(title)}</title>",
        "</head><body>",
        '<div class="header">',
    ]
    if citation:
        parts.append(f'<span class="citation">{html.escape(citation)}</span>')
    parts.append("</div>")
    parts.append('<div class="document">')
    seq = 0
    for num, body in paragraphs:
        if num is None:
            seq += 1
            num = seq
        parts.append(f'<p class="number">{num}</p>')
        parts.append(f'<p class="text">{html.escape(body)}</p>')
    parts.extend(["</div>", "</body></html>"])
    return "\n".join(parts), citation
