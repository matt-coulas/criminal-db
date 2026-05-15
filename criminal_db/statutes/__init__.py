"""Criminal Code and other statute ingestion (Justice Canada HTML)."""

from .db import StatuteSearchResult, StatutesDatabase
from .parser import JusticeCanadaParser, SectionData, normalize_section_ref

__all__ = [
    "JusticeCanadaParser",
    "SectionData",
    "StatuteSearchResult",
    "StatutesDatabase",
    "normalize_section_ref",
]
