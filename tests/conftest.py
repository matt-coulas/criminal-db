"""Shared pytest fixtures for criminal-db tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# Add the repo root to sys.path so ``import criminal_db`` works without an
# editable install.  This is the same convention used by the CLI.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture(scope="session")
def fulltext_html() -> str:
    return (FIXTURES / "fulltext_scc.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def headnote_html() -> str:
    return (FIXTURES / "headnote_fca.html").read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def listing_html() -> str:
    return (FIXTURES / "listing_page.html").read_text(encoding="utf-8")


@pytest.fixture
def tmp_db(tmp_path: Path) -> Path:
    """Return a path for an isolated SQLite database file."""
    return tmp_path / "test.db"
