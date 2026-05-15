# Agent / LLM integration

`criminal-db` is designed to run **locally** and be driven by scripts, shell tools, or LLM agents (Cursor, Claude Code, custom MCP servers, etc.).

## Machine-readable output

Pass **`--json`** immediately after the program name so subcommands emit JSON on stdout (no Rich tables):

```bash
criminal-db --json init
criminal-db --json ingest data/cases/fulltext
criminal-db --json index --status ok
criminal-db --json search "section 8 charter" --type hybrid
criminal-db --json analyze
criminal-db --json parse path/to/case.html --no-store
```

Human-readable tables are the default when `--json` is omitted.

## Recommended agent workflow

```bash
# 1. One-time setup
criminal-db init

# 2. Place permitted HTML under data/cases/fulltext or data/cases/headnotes
# 3. Ingest (updates manifest + routes to the correct SQLite file)
criminal-db --json ingest

# 4. Embeddings (requires pip install -e ".[embed]")
criminal-db --json embed

# 5. Search
criminal-db --json search "voir dire admissibility" --type hybrid --limit 5
```

## Dual databases

| Store | File | Contents |
|-------|------|----------|
| `fulltext` | `db/fulltext.db` | Numbered decision paragraphs |
| `headnotes` | `db/headnotes.db` | Headnote / summary paragraphs |

`parse`, `ingest`, and `harvest` (without `--db`) route cases by parsed `corpus`. `search` and `embed` (without `--db`) query **both** stores and merge ranks.

Override with `--db path/to/one.db` for single-database mode.

## Catalog manifest

`data/index/manifest.json` tracks every ingested HTML file:

- `status`: `pending` | `ok` | `failed` | `skipped`
- `sha256`: skip unchanged files on re-ingest
- `store`, `case_id`, `canlii_ref`

```bash
criminal-db --json index
criminal-db --json index --status failed
```

## Retrieve full cases after search

```bash
criminal-db --json get "2024 SCC 1"
criminal-db get "2024 SCC 1" --format text
criminal-db --json export -o corpus.json
```

## Python API (same semantics as CLI)

```python
from criminal_db.api import get_case, open_router, search

router = open_router()
hits = search("unreasonable search", mode="hybrid", limit=5, router=router)
full = get_case(hits[0].canlii_ref, router=router)
router.close()
```

## Criminal-law curation

By default, **search only returns criminal cases** (`is_criminal = 1`). Cases are
classified at ingest/parse time using court codes, caption heuristics (`R. v.`,
etc.), and manual overrides in `data/index/overrides.yaml`.

```bash
criminal-db --json curate
criminal-db search "query" --include-all    # include non-criminal cases
criminal-db ingest --criminal-only          # skip non-criminal at ingest
```

Override example (`data/index/overrides.yaml`):

```yaml
include:
  - "2024 FCA 88"
exclude:
  - "2024 SCC 999"
```

## Constraints for agents

- Do **not** disable `CRIMINAL_DB_RESPECT_ROBOTS=0` to bulk-scrape CanLII.
- Prefer `ingest` / `parse` on local HTML obtained lawfully.
- Vector search requires a Python build with SQLite extension loading (see README).

## Criminal Code (statutes)

```bash
criminal-db statutes parse data/statutes/criminal_code/
criminal-db --json statutes get 8
criminal-db --json search "unreasonable search" --scope statutes
```

Case search and statute search are separate corpora; use `--scope cases` (default)
or `--scope statutes`.
