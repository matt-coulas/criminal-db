"""Backup and restore local databases and catalog metadata."""

from __future__ import annotations

import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .. import config

DEFAULT_ARTIFACTS = (
    config.FULLTEXT_DB,
    config.HEADNOTES_DB,
    config.STATUTES_DB,
    config.MANIFEST_PATH,
    config.OVERRIDES_PATH,
)


def backup_data(
    destination: Path,
    *,
    include_statutes: bool = True,
) -> Path:
    """Create a timestamped ``.tar.gz`` of databases and catalog files.

    Returns the path to the archive written.
    """
    destination = Path(destination)
    if destination.suffix not in {".gz", ".tgz"} and not str(destination).endswith(
        ".tar.gz"
    ):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        destination = destination / f"criminal-db-backup-{stamp}.tar.gz"
    destination.parent.mkdir(parents=True, exist_ok=True)

    paths = [config.FULLTEXT_DB, config.HEADNOTES_DB, config.MANIFEST_PATH]
    if config.OVERRIDES_PATH.exists():
        paths.append(config.OVERRIDES_PATH)
    if include_statutes and config.STATUTES_DB.exists():
        paths.append(config.STATUTES_DB)

    with tarfile.open(destination, "w:gz") as tar:
        for path in paths:
            if path.exists():
                tar.add(path, arcname=path.name)
    return destination.resolve()


def restore_data(
    archive: Path,
    *,
    target_dir: Optional[Path] = None,
) -> list[Path]:
    """Extract a backup archive into ``target_dir`` (default: project db/index dirs)."""
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(archive)

    restored: list[Path] = []
    name_map = {
        "fulltext.db": config.FULLTEXT_DB,
        "headnotes.db": config.HEADNOTES_DB,
        "statutes.db": config.STATUTES_DB,
        "manifest.json": config.MANIFEST_PATH,
        "overrides.yaml": config.OVERRIDES_PATH,
    }

    with tarfile.open(archive, "r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            dest = name_map.get(Path(member.name).name)
            if dest is None and target_dir is not None:
                dest = Path(target_dir) / member.name
            elif dest is None:
                continue
            dest = Path(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            extracted = tar.extractfile(member)
            if extracted is None:
                continue
            dest.write_bytes(extracted.read())
            restored.append(dest.resolve())
    return restored
