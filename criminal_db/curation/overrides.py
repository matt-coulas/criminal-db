"""Manual include/exclude lists for curation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .. import config


@dataclass
class Overrides:
    include: set[str] = field(default_factory=set)
    exclude: set[str] = field(default_factory=set)

    def normalised(self) -> "Overrides":
        return Overrides(
            include={_norm_ref(r) for r in self.include},
            exclude={_norm_ref(r) for r in self.exclude},
        )


def _norm_ref(ref: str) -> str:
    return " ".join(ref.split())


def _parse_yaml_lists(text: str) -> dict[str, list[str]]:
    """Parse a minimal YAML subset: top-level ``include`` / ``exclude`` lists."""
    sections: dict[str, list[str]] = {"include": [], "exclude": []}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.endswith(":") and not line.startswith(" "):
            key = line[:-1].strip().lower()
            if key in sections:
                current = key
            continue
        if line.strip().startswith("- ") and current:
            item = line.strip()[2:].strip().strip("'\"")
            if item:
                sections[current].append(item)
    return sections


def load_overrides(path: Optional[Path] = None) -> Overrides:
    """Load overrides from ``overrides.yaml`` or ``overrides.json``."""
    base = path or config.OVERRIDES_PATH
    json_path = base.with_suffix(".json")
    yaml_path = base if base.suffix else base.with_suffix(".yaml")
    if not yaml_path.suffix:
        yaml_path = base.with_name("overrides.yaml")

    if yaml_path.exists():
        data = _parse_yaml_lists(yaml_path.read_text(encoding="utf-8"))
        return Overrides(
            include=set(data.get("include") or []),
            exclude=set(data.get("exclude") or []),
        ).normalised()
    if json_path.exists():
        raw = json.loads(json_path.read_text(encoding="utf-8"))
        return Overrides(
            include=set(raw.get("include") or []),
            exclude=set(raw.get("exclude") or []),
        ).normalised()
    return Overrides()


def ensure_overrides_template() -> Path:
    """Create ``data/index/overrides.yaml`` with comments if missing."""
    path = config.OVERRIDES_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and not path.with_suffix(".json").exists():
        path.write_text(
            "# Manual curation overrides (neutral citations).\n"
            "# include: force a case into the criminal corpus\n"
            "# exclude: force a case out (wins over rules)\n"
            "include: []\n"
            "exclude: []\n",
            encoding="utf-8",
        )
    return path
