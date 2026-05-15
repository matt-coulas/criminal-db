"""Parse Justice Canada statute HTML (Criminal Code)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup, Tag


@dataclass
class SectionData:
    section_number: str
    heading: Optional[str] = None
    text: str = ""
    part: Optional[str] = None
    act: str = "criminal_code"


def normalize_section_ref(ref: str) -> str:
    """Normalise ``s. 8``, ``section 8``, ``8`` → ``8`` (keeps subsections)."""
    raw = (ref or "").strip().lower()
    if raw.startswith("section "):
        raw = raw[len("section ") :]
    elif raw.startswith("s.") or raw.startswith("s "):
        raw = re.sub(r"^s\.?\s*", "", raw)
    return raw.strip()


class JusticeCanadaParser:
    """Parse Criminal Code HTML saved from laws-lois.justice.gc.ca."""

    def __init__(self, html: str, *, act: str = "criminal_code") -> None:
        self.html = html or ""
        self.soup = BeautifulSoup(self.html, "lxml")
        self.act = act
        self._current_part: Optional[str] = None

    def parse(self) -> list[SectionData]:
        for part in self.soup.find_all(class_=re.compile(r"\bPart\b", re.I)):
            self._current_part = part.get_text(" ", strip=True)

        blocks = self.soup.find_all(class_=re.compile(r"\bSection\b"))
        if not blocks:
            blocks = [
                t
                for t in self.soup.find_all(["section", "div"], id=re.compile(r"^s-", re.I))
            ]
        sections: list[SectionData] = []
        seen: set[str] = set()
        for block in blocks:
            sec = self._parse_block(block)
            if sec and sec.section_number not in seen and sec.text.strip():
                seen.add(sec.section_number)
                sections.append(sec)
        if not sections:
            for sec in self._parse_heading_fallback():
                if sec.section_number not in seen:
                    seen.add(sec.section_number)
                    sections.append(sec)
        return sections

    def _parse_block(self, tag: Tag) -> Optional[SectionData]:
        num = None
        label = tag.find(class_=re.compile(r"SectionLabel|sectionLabel", re.I))
        if label:
            num = label.get_text(strip=True)
        if not num:
            sid = tag.get("id") or ""
            m = re.search(r"s-?(\d[\d.\(\)]*)", sid, re.I)
            if m:
                num = m.group(1)
        if not num:
            h = tag.find(["h2", "h3", "h4"])
            if h:
                m = re.search(r"^(\d[\d.\(\)]*)\b", h.get_text(strip=True))
                if m:
                    num = m.group(1)
        if not num:
            return None

        heading = None
        marginal = tag.find(class_=re.compile(r"MarginalNote|marginal", re.I))
        if marginal:
            heading = marginal.get_text(" ", strip=True)

        paras = [
            p.get_text(" ", strip=True)
            for p in tag.find_all("p")
            if p.get_text(strip=True)
            and "MarginalNote" not in " ".join(p.get("class") or [])
        ]
        text = " ".join(paras) if paras else tag.get_text(" ", strip=True)
        return SectionData(
            section_number=normalize_section_ref(num),
            heading=heading,
            text=text,
            part=self._current_part,
            act=self.act,
        )

    def _parse_heading_fallback(self) -> list[SectionData]:
        out: list[SectionData] = []
        for h in self.soup.find_all(["h2", "h3"]):
            title = h.get_text(" ", strip=True)
            m = re.match(r"^(\d[\d.\(\)]*)\s*[-–.]?\s*(.*)$", title)
            if not m:
                continue
            num, rest = m.group(1), m.group(2).strip()
            paras: list[str] = []
            for sib in h.find_next_siblings():
                if sib.name in {"h1", "h2", "h3", "h4"}:
                    break
                if sib.name == "p":
                    t = sib.get_text(" ", strip=True)
                    if t:
                        paras.append(t)
            if paras:
                out.append(
                    SectionData(
                        section_number=normalize_section_ref(num),
                        heading=rest or None,
                        text=" ".join(paras),
                        act=self.act,
                    )
                )
        return out
