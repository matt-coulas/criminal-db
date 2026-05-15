"""JSON manifest tracking source files and parse status."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .. import config

EntryStatus = Literal["pending", "ok", "failed", "skipped", "excluded"]
StoreName = Literal["fulltext", "headnotes"]
SourceType = Literal["html", "pdf"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_catalog_dirs() -> None:
    """Create ``data/index`` and an empty manifest if missing."""
    from ..curation.overrides import ensure_overrides_template

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    config.IMPORT_DIR.mkdir(parents=True, exist_ok=True)
    (config.IMPORT_DIR / "html").mkdir(parents=True, exist_ok=True)
    (config.IMPORT_DIR / "pdf").mkdir(parents=True, exist_ok=True)
    (config.CASES_DIR / "fulltext").mkdir(parents=True, exist_ok=True)
    (config.CASES_DIR / "headnotes").mkdir(parents=True, exist_ok=True)
    config.CASES_MD_DIR.mkdir(parents=True, exist_ok=True)
    if not config.MANIFEST_PATH.exists():
        Manifest().save()
    ensure_overrides_template()


@dataclass
class CatalogEntry:
    """One source HTML file tracked in the catalog."""

    source_path: str
    status: EntryStatus = "pending"
    canlii_ref: Optional[str] = None
    corpus: Optional[str] = None
    sha256: Optional[str] = None
    fetched_at: Optional[str] = None
    parsed_at: Optional[str] = None
    parse_error: Optional[str] = None
    case_id: Optional[int] = None
    store: Optional[StoreName] = None
    source_url: Optional[str] = None
    source_type: Optional[SourceType] = None
    original_filename: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogEntry":
        return cls(
            source_path=str(data["source_path"]),
            status=data.get("status", "pending"),
            canlii_ref=data.get("canlii_ref"),
            corpus=data.get("corpus"),
            sha256=data.get("sha256"),
            fetched_at=data.get("fetched_at"),
            parsed_at=data.get("parsed_at"),
            parse_error=data.get("parse_error"),
            case_id=data.get("case_id"),
            store=data.get("store"),
            source_url=data.get("source_url"),
            source_type=data.get("source_type"),
            original_filename=data.get("original_filename"),
        )


class Manifest:
    """Load/save ``data/index/manifest.json``."""

    def __init__(
        self,
        path: Optional[Path] = None,
        *,
        entries: Optional[dict[str, CatalogEntry]] = None,
    ) -> None:
        self.path = Path(path or config.MANIFEST_PATH)
        self.entries: dict[str, CatalogEntry] = entries if entries is not None else {}

    @staticmethod
    def entry_key(source_path: Path) -> str:
        """Stable manifest key (repo-relative when possible)."""
        path = source_path.resolve()
        try:
            return str(path.relative_to(config.BASE_DIR))
        except ValueError:
            return str(path)

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Manifest":
        p = Path(path or config.MANIFEST_PATH)
        if not p.exists():
            return cls(p)
        raw = json.loads(p.read_text(encoding="utf-8"))
        entries = {
            key: CatalogEntry.from_dict(val)
            for key, val in (raw.get("entries") or {}).items()
        }
        return cls(p, entries=entries)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "updated_at": _now_iso(),
            "entries": {k: e.to_dict() for k, e in sorted(self.entries.items())},
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def get(self, source_path: Path) -> Optional[CatalogEntry]:
        return self.entries.get(self.entry_key(source_path))

    def upsert(self, entry: CatalogEntry) -> None:
        self.entries[self.entry_key(Path(entry.source_path))] = entry

    def list_entries(
        self,
        *,
        status: Optional[EntryStatus] = None,
        court_substr: Optional[str] = None,
    ) -> list[CatalogEntry]:
        rows = list(self.entries.values())
        if status is not None:
            rows = [e for e in rows if e.status == status]
        if court_substr:
            needle = court_substr.lower()
            rows = [
                e
                for e in rows
                if e.canlii_ref and needle in e.canlii_ref.lower()
            ]
        return sorted(rows, key=lambda e: e.source_path)
