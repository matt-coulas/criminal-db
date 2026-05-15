"""CanLII HTML parser.

Parses a single CanLII case-detail page into a :class:`CaseData` instance.
Paragraph numbers are the unit of legal citation, so the parser is built
around extracting and preserving them.

The CanLII layout varies subtly by court, era, and whether the decision is
full-text or headnote-only.  The parser tries a small ordered list of
extraction strategies and uses the first one that returns at least one
paragraph.  Heading association uses DOM proximity (previous sibling /
ancestor walk) rather than picking a single document-wide heading.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Optional

from bs4 import BeautifulSoup, NavigableString, Tag


# ── Data structures ────────────────────────────────────────────────────────


@dataclass
class Paragraph:
    paragraph_num: Optional[int] = None
    heading: Optional[str] = None
    text: str = ""
    is_headnote: bool = False
    is_ratio: bool = False
    section_number: Optional[str] = None


@dataclass
class CaseData:
    canlii_ref: str = "UNKNOWN"
    neutral_citation: str = ""
    reporter_citation: str = ""
    court: str = ""
    court_year: int = 0
    decided_date: str = ""
    judges: list[str] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    corpus: str = "fulltext"  # 'fulltext' | 'headnote'
    is_headnote_only: int = 0
    source_url: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────


_CITATION_RE = re.compile(
    r"\b(?P<year>\d{4})\s+"
    r"(?P<court>SCC|SCR|FCA|FC|TCC|ABCA|BCCA|MBCA|NBCA|NLCA|NSCA|"
    r"ONCA|ONSC|PECA|QCCA|SKCA|NWTCA|YKCA|NUCA|ABQB|BCSC|MBQB|NBQB|"
    r"NLSC|NSSC|ONCJ|PESC|QCCS|SKQB|NWTSC|YKSC|NUCJ)"
    r"\s+(?P<num>\d+)\b"
)

_DATE_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

_RATIO_KEYWORDS = re.compile(
    r"\b(ratio decidendi|the issue|the question|we conclude|we hold|"
    r"hold(?:s|ing)?|conclud(?:es|ing)|disposition|appeal (?:is )?(?:allowed|dismissed))\b",
    re.IGNORECASE,
)

_HEADNOTE_HEADINGS = {
    "headnote",
    "facts",
    "history",
    "judgment",
    "holding",
    "summary",
    "synopsis",
}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _classify_corpus(paragraphs: list[Paragraph]) -> str:
    """Decide whether a parsed case is a fulltext decision or a headnote summary.

    A case is treated as a headnote when *all* extracted paragraphs are
    flagged ``is_headnote`` (this covers the CanLII pattern of a numbered
    headnote summary) or when none of them carry paragraph numbers (the
    fallback path on minimal pages).  Otherwise it is treated as fulltext.
    """
    if not paragraphs:
        return "headnote"
    if all(p.is_headnote for p in paragraphs):
        return "headnote"
    if not any(p.paragraph_num is not None for p in paragraphs):
        # Unnumbered blocks from generic <p> extraction are still fulltext when
        # they look like a substantive decision (not a short headnote summary).
        if len(paragraphs) >= 2 and sum(len(p.text or "") for p in paragraphs) > 200:
            return "fulltext"
        return "headnote"
    return "fulltext"


def _looks_like_section_number(text: str) -> Optional[str]:
    m = re.search(r"\bs\.?\s*(\d{1,3}(?:\.\d+)?(?:\([^)]+\))?)\b", text)
    return m.group(1) if m else None


# ── Parser ─────────────────────────────────────────────────────────────────


class CanLIIParser:
    """Parse one CanLII case-detail HTML document into a :class:`CaseData`."""

    def __init__(self, html: str, *, source_url: str = "") -> None:
        self.html = html or ""
        self.soup = BeautifulSoup(self.html, "lxml")
        self.source_url = source_url

    # ── public API ─────────────────────────────────────────────────────────

    def parse(self) -> CaseData:
        case = CaseData(source_url=self.source_url)
        case.canlii_ref = self._extract_canlii_ref()
        case.neutral_citation = self._extract_neutral_citation()
        case.reporter_citation = self._extract_reporter_citation()
        case.court, case.court_year = self._extract_court_year(case.canlii_ref)
        case.decided_date = self._extract_date()
        case.judges = self._extract_judges()
        case.paragraphs = self._extract_paragraphs()
        case.corpus = _classify_corpus(case.paragraphs)
        case.is_headnote_only = 1 if case.corpus == "headnote" else 0
        # Annotate ratio paragraphs based on text content.
        for p in case.paragraphs:
            if _RATIO_KEYWORDS.search(p.text or ""):
                p.is_ratio = True
            if p.section_number is None:
                p.section_number = _looks_like_section_number(p.text or "")
        return case

    # ── citation extraction ───────────────────────────────────────────────

    def _extract_canlii_ref(self) -> str:
        # Strategy 1: explicit citation span.
        for cls in ("citation", "case-citation"):
            tag = self.soup.find("span", class_=cls)
            if tag:
                txt = _clean(tag.get_text())
                m = _CITATION_RE.search(txt)
                if m:
                    return f"{m.group('year')} {m.group('court')} {m.group('num')}"
                if txt:
                    return txt
        # Strategy 2: meta tags (some exports / saved pages).
        for tag in self.soup.find_all("meta"):
            content = tag.get("content") or ""
            m = _CITATION_RE.search(_clean(content))
            if m:
                return f"{m.group('year')} {m.group('court')} {m.group('num')}"
        # Strategy 3: page title / h1 / hgroup.
        for selector in ("title", "h1", "h2", "h3"):
            for tag in self.soup.find_all(selector):
                m = _CITATION_RE.search(_clean(tag.get_text()))
                if m:
                    return f"{m.group('year')} {m.group('court')} {m.group('num')}"
        # Strategy 4: anywhere in the document.
        m = _CITATION_RE.search(_clean(self.soup.get_text()))
        if m:
            return f"{m.group('year')} {m.group('court')} {m.group('num')}"
        return "UNKNOWN"

    def _extract_neutral_citation(self) -> str:
        for cls in ("neutral_citation", "neutral-citation"):
            tag = self.soup.find("span", class_=cls)
            if tag:
                return _clean(tag.get_text())
        return ""

    def _extract_reporter_citation(self) -> str:
        for cls in ("reporter", "reporter_citation", "reporter-citation"):
            tag = self.soup.find("span", class_=cls)
            if tag:
                return _clean(tag.get_text())
        return ""

    # ── court / year ───────────────────────────────────────────────────────

    _COURT_NAMES = {
        "SCC": "Supreme Court of Canada",
        "FCA": "Federal Court of Appeal",
        "FC": "Federal Court",
        "TCC": "Tax Court of Canada",
        "ONCA": "Court of Appeal for Ontario",
        "ONSC": "Ontario Superior Court of Justice",
        "ONCJ": "Ontario Court of Justice",
        "BCCA": "British Columbia Court of Appeal",
        "BCSC": "British Columbia Supreme Court",
        "ABCA": "Court of Appeal of Alberta",
        "ABQB": "Court of King's Bench of Alberta",
        "QCCA": "Cour d'appel du Québec",
        "QCCS": "Cour supérieure du Québec",
        "SKCA": "Court of Appeal for Saskatchewan",
        "MBCA": "Court of Appeal of Manitoba",
        "NSCA": "Nova Scotia Court of Appeal",
        "NBCA": "New Brunswick Court of Appeal",
        "NLCA": "Court of Appeal of Newfoundland and Labrador",
        "PECA": "Prince Edward Island Court of Appeal",
        "NWTCA": "Court of Appeal for the Northwest Territories",
        "YKCA": "Court of Appeal of Yukon",
        "NUCA": "Court of Appeal of Nunavut",
    }

    def _extract_court_year(self, canlii_ref: str) -> tuple[str, int]:
        # Prefer explicit element with class="court".
        tag = self.soup.find(class_="court")
        if tag is not None:
            text = _clean(tag.get_text())
            year_m = re.search(r"\b(\d{4})\b", text)
            year = int(year_m.group(1)) if year_m else 0
            name = re.sub(r"\b\d{4}\b", "", text).strip(" ,")
            if name:
                return name, year

        # Otherwise derive from canlii_ref.
        m = _CITATION_RE.search(canlii_ref or "")
        if m:
            year = int(m.group("year"))
            name = self._COURT_NAMES.get(m.group("court"), m.group("court"))
            return name, year
        return "UNKNOWN", 0

    # ── date ───────────────────────────────────────────────────────────────

    def _extract_date(self) -> str:
        # First: any element with class containing 'date' or data-type='date'.
        for tag in self.soup.find_all(True):
            classes = tag.get("class") or []
            data_type = tag.get("data-type") or ""
            if any("date" in cls.lower() for cls in classes) or data_type == "date":
                m = _DATE_RE.search(_clean(tag.get_text()))
                if m:
                    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        # Fallback: first ISO date in the document.
        m = _DATE_RE.search(self.soup.get_text())
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""

    # ── judges ─────────────────────────────────────────────────────────────

    def _extract_judges(self) -> list[str]:
        judges: list[str] = []
        seen: set[str] = set()

        def _push(name: str) -> None:
            cleaned = _clean(name)
            if not cleaned:
                return
            low = cleaned.lower()
            if low in {"judge", "judges", "justice", "justices"}:
                return
            if cleaned not in seen:
                seen.add(cleaned)
                judges.append(cleaned)

        # Scoped: look inside a panel/coram block first.
        for container in self.soup.find_all(class_=re.compile(r"\b(panel|coram|judges?)\b")):
            for span in container.find_all(["span", "li", "p"]):
                _push(span.get_text())

        # Class-tagged spans.
        for span in self.soup.find_all("span", class_=re.compile(r"\bjudges?\b")):
            _push(span.get_text())

        # data-type='judge'.
        for tag in self.soup.find_all(attrs={"data-type": "judge"}):
            _push(tag.get_text())

        return judges

    # ── paragraph extraction ──────────────────────────────────────────────

    def _extract_paragraphs(self) -> list[Paragraph]:
        # Try strategies in order; return on first hit that yields content.
        for extractor in (
            self._extract_paired_numbered,
            self._extract_inline_numbered,
            self._extract_headnote_blocks,
            self._extract_generic_paragraphs,
        ):
            paragraphs = extractor()
            if paragraphs:
                return paragraphs
        return []

    def _extract_paired_numbered(self) -> list[Paragraph]:
        """``<p class="number">N</p><p class="text">...</p>`` pattern."""
        numbers = self.soup.find_all(
            "p", class_=re.compile(r"\bnumber\b")
        )
        if not numbers:
            return []

        paragraphs: list[Paragraph] = []
        for num_el in numbers:
            num_txt = _clean(num_el.get_text())
            if not num_txt.isdigit():
                continue
            paragraph_num = int(num_txt)
            text_el = self._find_paired_text(num_el)
            if text_el is None:
                continue
            text = _clean(text_el.get_text(" ", strip=True))
            if not text:
                continue
            paragraphs.append(
                Paragraph(
                    paragraph_num=paragraph_num,
                    heading=self._nearest_heading(num_el),
                    text=text,
                    is_headnote=self._is_in_headnote(num_el),
                )
            )
        return paragraphs

    def _find_paired_text(self, num_el: Tag) -> Optional[Tag]:
        """Return the text paragraph paired with ``num_el``.

        First look at the immediate following sibling; fall back to the next
        ``p.text`` in document order to cope with whitespace text nodes.
        """
        sib = num_el.find_next_sibling()
        if isinstance(sib, Tag):
            classes = sib.get("class") or []
            if any("text" in cls for cls in classes):
                return sib
            if sib.name == "p":
                return sib
        return num_el.find_next("p", class_=re.compile(r"\btext\b"))

    def _extract_inline_numbered(self) -> list[Paragraph]:
        """``<span class="paragraph_number">[N]</span> ... text ...`` pattern."""
        paragraphs: list[Paragraph] = []
        for num_span in self.soup.find_all(
            "span", class_=re.compile(r"\bparagraph[_-]?number\b")
        ):
            num_txt = _clean(num_span.get_text()).strip("[](){}")
            if not num_txt.isdigit():
                continue
            parent = num_span.parent
            if parent is None:
                continue
            # Build the text by stripping the number span's own contents.
            parts: list[str] = []
            for child in parent.descendants:
                if child is num_span or (isinstance(child, Tag) and num_span in child.descendants):
                    continue
                if isinstance(child, NavigableString):
                    parts.append(str(child))
            text = _clean(" ".join(parts))
            if not text:
                continue
            paragraphs.append(
                Paragraph(
                    paragraph_num=int(num_txt),
                    heading=self._nearest_heading(num_span),
                    text=text,
                    is_headnote=self._is_in_headnote(num_span),
                )
            )
        return paragraphs

    def _extract_headnote_blocks(self) -> list[Paragraph]:
        """Headnote-style format with ``p.headnote-number`` + ``span.caseparagraph``."""
        numbers = self.soup.find_all(
            "p", class_=re.compile(r"\bheadnote[-_]?number\b")
        )
        paragraphs_spans = self.soup.find_all(
            "span", class_=re.compile(r"\bcaseparagraph\b")
        )
        if not numbers and not paragraphs_spans:
            return []

        paragraphs: list[Paragraph] = []
        # Pair by document order; if the lists differ in length, keep the
        # shorter prefix but log nothing (silent shorter-side truncation here
        # is acceptable because the layout doesn't carry orphaned numbers).
        for num_el, para_el in zip(numbers, paragraphs_spans):
            text = _clean(para_el.get_text(" ", strip=True))
            num_txt = _clean(num_el.get_text())
            paragraphs.append(
                Paragraph(
                    paragraph_num=int(num_txt) if num_txt.isdigit() else None,
                    heading=self._nearest_heading(para_el),
                    text=text,
                    is_headnote=True,
                )
            )

        # Standalone caseparagraph spans without paired numbers.
        if not numbers:
            for span in paragraphs_spans:
                text = _clean(span.get_text(" ", strip=True))
                if not text:
                    continue
                paragraphs.append(
                    Paragraph(
                        paragraph_num=None,
                        heading=self._nearest_heading(span),
                        text=text,
                        is_headnote=True,
                    )
                )
        return paragraphs

    def _extract_generic_paragraphs(self) -> list[Paragraph]:
        """Fallback: every <p> inside the main body."""
        body = (
            self.soup.find(class_=re.compile(r"\b(documentcontent|document-content)\b", re.I))
            or self.soup.find(class_=re.compile(r"\b(body|content|document|maincontent)\b", re.I))
            or self.soup.find("div", id=re.compile(r"\bdocument\b", re.I))
            or self.soup.body
            or self.soup
        )
        paragraphs: list[Paragraph] = []
        for tag in body.find_all("p"):
            text = _clean(tag.get_text(" ", strip=True))
            if not text:
                continue
            # Skip pure-number paragraphs (those are part of the paired pattern
            # we already tried and rejected).
            if text.isdigit():
                continue
            paragraphs.append(
                Paragraph(
                    paragraph_num=None,
                    heading=self._nearest_heading(tag),
                    text=text,
                    is_headnote=self._is_in_headnote(tag),
                )
            )
        return paragraphs

    # ── DOM neighbourhood helpers ──────────────────────────────────────────

    _HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6", "dt")

    def _nearest_heading(self, tag: Tag) -> Optional[str]:
        """Find the closest preceding heading or ancestor section title."""
        cursor: Optional[Tag] = tag
        while cursor is not None:
            prev = cursor.find_previous(self._HEADING_TAGS)
            if prev is None:
                return None
            text = _clean(prev.get_text())
            if text:
                return text.upper()
            cursor = prev
        return None

    def _is_in_headnote(self, tag: Tag) -> bool:
        for parent in tag.parents:
            classes = parent.get("class") or []
            if any(
                any(kw in (cls or "").lower() for kw in ("headnote", "summary", "synopsis"))
                for cls in classes
            ):
                return True
            heading_txt = (
                _clean(parent.get_text(separator=" ", strip=True))
                if parent.name in self._HEADING_TAGS
                else ""
            )
            if heading_txt.lower() in _HEADNOTE_HEADINGS:
                return True
        return False


# ── Export helpers ─────────────────────────────────────────────────────────


def export_case_to_json(case: CaseData) -> dict:
    """Serialise a :class:`CaseData` to a plain dict suitable for JSON."""
    return {
        "meta": {
            "canlii_ref": case.canlii_ref,
            "neutral_citation": case.neutral_citation,
            "reporter_citation": case.reporter_citation,
            "court": case.court,
            "court_year": case.court_year,
            "decided_date": case.decided_date,
            "judges": list(case.judges),
            "corpus": case.corpus,
            "is_headnote_only": case.is_headnote_only,
            "source_url": case.source_url,
        },
        "paragraphs": [asdict(p) for p in case.paragraphs],
    }


def write_case_json(case: CaseData, out_path: str) -> None:
    """Write the JSON export of ``case`` to ``out_path``."""
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(export_case_to_json(case), fh, ensure_ascii=False, indent=2)
