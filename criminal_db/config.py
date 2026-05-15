"""Single source of truth for paths, settings, and tunables."""

from __future__ import annotations

import os
from pathlib import Path

# ── Paths ───────────────────────────────────────────────────────────────────

BASE_DIR: Path = Path(__file__).resolve().parent.parent
DATA_DIR: Path = BASE_DIR / "data"
RAW_DIR: Path = DATA_DIR / "raw"
CASES_DIR: Path = DATA_DIR / "cases"
STATUTES_DIR: Path = DATA_DIR / "statutes"
DB_DIR: Path = BASE_DIR / "db"
MODELS_DIR: Path = BASE_DIR / "models"

# The two SQLite databases below sit in DB_DIR.  They share the same schema;
# `headnotes.db` stores only summary paragraphs, `fulltext.db` stores the
# entire decision body.  Most users only need `fulltext.db`.
HEADNOTES_DB: Path = DB_DIR / "headnotes.db"
FULLTEXT_DB: Path = DB_DIR / "fulltext.db"

# Default database used by the CLI when --db targets a single file.
DEFAULT_DB: Path = FULLTEXT_DB

# Catalog manifest (ingest / harvest bookkeeping).
INDEX_DIR: Path = DATA_DIR / "index"
MANIFEST_PATH: Path = INDEX_DIR / "manifest.json"
OVERRIDES_PATH: Path = INDEX_DIR / "overrides.yaml"

# ── Harvester ───────────────────────────────────────────────────────────────

CANLII_BASE = "https://www.canlii.org"

# A single honest User-Agent.  Override per-deployment via env var.
CANLII_USER_AGENT: str = os.environ.get(
    "CRIMINAL_DB_USER_AGENT",
    "criminal-db/0.1 (+https://github.com/your-org/criminal-db; research)",
)

# Polite delays.  ≥5s minimum is the lower bound; we add jitter on top.
CANLII_DELAY_MIN: float = float(os.environ.get("CRIMINAL_DB_DELAY_MIN", "5.0"))
CANLII_DELAY_MAX: float = float(os.environ.get("CRIMINAL_DB_DELAY_MAX", "9.0"))

CANLII_TIMEOUT_S: float = 30.0
CANLII_MAX_RETRIES: int = 4
CANLII_MAX_CONCURRENCY: int = 1  # be polite by default

# Whether to consult robots.txt before fetching.
CANLII_RESPECT_ROBOTS: bool = (
    os.environ.get("CRIMINAL_DB_RESPECT_ROBOTS", "1").lower()
    not in {"0", "false", "no"}
)

# ── Embeddings ──────────────────────────────────────────────────────────────

# bge-small-en-v1.5: 384 dim, ~130MB, CPU-friendly, strong on legal text.
# Override via env var if you want to swap in a larger model.
EMBEDDING_MODEL: str = os.environ.get(
    "CRIMINAL_DB_EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"
)
EMBEDDING_DIM: int = int(os.environ.get("CRIMINAL_DB_EMBEDDING_DIM", "384"))
EMBEDDING_BATCH_SIZE: int = 32

# Cache directory passed to sentence-transformers.
EMBEDDING_CACHE_DIR: Path = MODELS_DIR / "embeddings"

# ── CLI defaults ────────────────────────────────────────────────────────────

DEFAULT_SEARCH_LIMIT: int = 10
DEFAULT_PAGE_SIZE: int = 20

# Hybrid search weighting: convex combination of normalised FTS rank and
# vector cosine similarity.  0.0 = pure vector, 1.0 = pure FTS.
HYBRID_FTS_WEIGHT: float = 0.4
