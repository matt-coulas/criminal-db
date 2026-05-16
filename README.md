# criminal-db

A local-first Canadian criminal-law case database with hybrid full-text (FTS5)
and semantic (sqlite-vec) search over paragraph-level case content.

> **Status:** 0.3 — local-first research tool. See [docs/RUNBOOK.md](docs/RUNBOOK.md)
> for operations and [CHANGELOG.md](CHANGELOG.md) for releases.

## What it does

1. **Harvest** case HTML from CanLII (one URL at a time, or a listing page).
2. **Parse** each decision into structured paragraphs with citation, court,
   date, judges, and paragraph numbers preserved.
3. **Store** everything in SQLite: one row per case, one row per paragraph.
4. **Embed** paragraphs with a small sentence-transformer model and persist the
   vectors in a `sqlite-vec` virtual table.
5. **Search** with FTS5, vector similarity, or a hybrid of both, with optional
   filters by court / year.

## Install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e ".[embed,dev]"
```

Embeddings are optional — the CLI works fine for FTS5-only workflows without
the `embed` extra.

Optional terminal UI: `pip install -e ".[tui]"` then `criminal-db tui`.

## Install with Docker

The image includes the CLI with **embed**, **pdf**, and **tui** extras. Your
**corpus and SQLite files stay on the host** (mounted volumes)—the image does not
ship case law HTML or databases.

Compose runs the **JSON HTTP API** (`criminal-db serve`) on port **8765** by
default. There is no browser web UI yet; use the API, `docker compose run …`
CLI commands, or the **TUI** (`docker compose --profile tui run --rm tui`).

More detail: [docs/DOCKER.md](docs/DOCKER.md) · CI publish:
[docs/GITHUB_ACTIONS_DOCKER.md](docs/GITHUB_ACTIONS_DOCKER.md)

### Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Empty host directories (or your existing corpus):

```bash
mkdir -p data db models
```

### Quick start (build from this repo)

```bash
git clone https://github.com/matt-coulas/criminal-db.git
cd criminal-db
cp .env.docker.example .env   # edit paths and ports if needed
docker compose up -d api
curl -s http://127.0.0.1:8765/health
```

First start runs `criminal-db init` automatically when `db/*.db` are missing.

### Quick start (pull a published image)

Replace `OWNER` with your GitHub username/org or Docker Hub username:

```bash
docker pull ghcr.io/OWNER/criminal-db:latest
# or: docker pull OWNER/criminal-db:latest
```

Use `image:` instead of `build:` in the compose example below.

### Corpus workflow in Docker

```bash
# Copy permitted HTML into ./data/cases/fulltext or ./data/import/html
docker compose run --rm api criminal-db ingest --criminal-only
docker compose run --rm api criminal-db embed --scope all
docker compose run --rm api criminal-db search "section 8 charter" --type hybrid
```

API examples:

```bash
curl "http://127.0.0.1:8765/search?q=voir+dire&scope=all&type=fts"
curl -H "Authorization: Bearer YOUR_TOKEN" "http://127.0.0.1:8765/get?citation=2024+SCC+1"
```

Set `CRIMINAL_DB_API_TOKEN` in `.env` when exposing the API beyond localhost.

### Environment variables

Copy [.env.docker.example](.env.docker.example) to `.env` beside `compose.yaml`.
Compose substitutes `${VAR:-default}` into the file below.

| Variable | Default | Description |
|----------|---------|-------------|
| `CRIMINAL_DB_HOST_PORT` | `8765` | Host port published to the API |
| `CRIMINAL_DB_DATA_DIR` | `./data` | Host path → `/app/data` (HTML, manifest, import) |
| `CRIMINAL_DB_DB_DIR` | `./db` | Host path → `/app/db` (SQLite files) |
| `CRIMINAL_DB_MODELS_DIR` | `./models` | Host path → `/app/models` (embedding cache) |
| `CRIMINAL_DB_API_HOST` | `0.0.0.0` | Bind address inside the container |
| `CRIMINAL_DB_API_PORT` | `8765` | Listen port inside the container |
| `CRIMINAL_DB_API_TOKEN` | *(empty)* | If set, requires `Authorization: Bearer …` or `X-API-Token` |
| `CRIMINAL_DB_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Sentence-transformers model id |
| `CRIMINAL_DB_EMBEDDING_DIM` | `384` | Vector size (must match model) |
| `CRIMINAL_DB_MAX_QUERY_LEN` | `500` | Max API / FTS query length |
| `CRIMINAL_DB_RESPECT_ROBOTS` | `1` | `1` = obey CanLII `robots.txt` for harvest |
| `CRIMINAL_DB_USER_AGENT` | *(built-in)* | Harvester User-Agent string |
| `CRIMINAL_DB_DELAY_MIN` | `5.0` | Minimum delay between harvest requests (seconds) |
| `CRIMINAL_DB_DELAY_MAX` | `9.0` | Maximum harvest delay (seconds) |

Use absolute host paths in production, e.g. `CRIMINAL_DB_DATA_DIR=/srv/criminal-db/data`.

### Example `compose.yaml` (all customization options)

Save as `compose.yaml` next to `.env`, or merge with the
[compose.yaml](compose.yaml) shipped in this repo.

```yaml
# criminal-db — full Compose example with every documented option.
# Requires .env (see .env.docker.example) or export the variables below.

services:
  api:
    # --- Image source (use ONE of build or image) ---
    build: .                                    # build from Dockerfile in repo root
    image: criminal-db:local                   # local tag after build
    # image: ghcr.io/OWNER/criminal-db:latest  # published GHCR image
    # image: OWNER/criminal-db:latest          # published Docker Hub image

    restart: unless-stopped

    ports:
      # host:container — container port must match CRIMINAL_DB_API_PORT
      - "${CRIMINAL_DB_HOST_PORT:-8765}:${CRIMINAL_DB_API_PORT:-8765}"

    environment:
      CRIMINAL_DB_API_HOST: ${CRIMINAL_DB_API_HOST:-0.0.0.0}
      CRIMINAL_DB_API_PORT: ${CRIMINAL_DB_API_PORT:-8765}
      CRIMINAL_DB_API_TOKEN: ${CRIMINAL_DB_API_TOKEN:-}
      CRIMINAL_DB_EMBEDDING_MODEL: ${CRIMINAL_DB_EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}
      CRIMINAL_DB_EMBEDDING_DIM: ${CRIMINAL_DB_EMBEDDING_DIM:-384}
      CRIMINAL_DB_MAX_QUERY_LEN: ${CRIMINAL_DB_MAX_QUERY_LEN:-500}
      CRIMINAL_DB_RESPECT_ROBOTS: ${CRIMINAL_DB_RESPECT_ROBOTS:-1}
      CRIMINAL_DB_USER_AGENT: ${CRIMINAL_DB_USER_AGENT:-}
      CRIMINAL_DB_DELAY_MIN: ${CRIMINAL_DB_DELAY_MIN:-5.0}
      CRIMINAL_DB_DELAY_MAX: ${CRIMINAL_DB_DELAY_MAX:-9.0}

    volumes:
      - ${CRIMINAL_DB_DATA_DIR:-./data}:/app/data
      - ${CRIMINAL_DB_DB_DIR:-./db}:/app/db
      - ${CRIMINAL_DB_MODELS_DIR:-./models}:/app/models

    entrypoint: ["docker-entrypoint.sh"]
    command: ["criminal-db", "serve"]

    # Optional health check:
    # healthcheck:
    #   test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health')"]
    #   interval: 30s
    #   timeout: 5s
    #   retries: 3
    #   start_period: 40s

  tui:
    profiles: [tui]
    build: .
    image: criminal-db:local
    stdin_open: true
    tty: true
    environment:
      CRIMINAL_DB_API_HOST: ${CRIMINAL_DB_API_HOST:-127.0.0.1}
      CRIMINAL_DB_API_PORT: ${CRIMINAL_DB_API_PORT:-8765}
      CRIMINAL_DB_API_TOKEN: ${CRIMINAL_DB_API_TOKEN:-}
      CRIMINAL_DB_EMBEDDING_MODEL: ${CRIMINAL_DB_EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}
      CRIMINAL_DB_EMBEDDING_DIM: ${CRIMINAL_DB_EMBEDDING_DIM:-384}
      CRIMINAL_DB_RESPECT_ROBOTS: ${CRIMINAL_DB_RESPECT_ROBOTS:-1}
      CRIMINAL_DB_USER_AGENT: ${CRIMINAL_DB_USER_AGENT:-}
      CRIMINAL_DB_DELAY_MIN: ${CRIMINAL_DB_DELAY_MIN:-5.0}
      CRIMINAL_DB_DELAY_MAX: ${CRIMINAL_DB_DELAY_MAX:-9.0}
    volumes:
      - ${CRIMINAL_DB_DATA_DIR:-./data}:/app/data
      - ${CRIMINAL_DB_DB_DIR:-./db}:/app/db
      - ${CRIMINAL_DB_MODELS_DIR:-./models}:/app/models
    entrypoint: ["docker-entrypoint.sh"]
    command: ["criminal-db", "tui"]
```

**Commands:**

```bash
docker compose up -d api                              # API in background
docker compose --profile tui run --rm tui             # full-screen TUI
docker compose run --rm api criminal-db verify        # one-off CLI
docker compose pull && docker compose up -d api       # after publishing a new image
```

Mount only corpus you have rights to use. See
[docs/COPYRIGHT_AND_REDISTRIBUTION.md](docs/COPYRIGHT_AND_REDISTRIBUTION.md).

## Quick start

```bash
# Initialise databases, data/ layout, and catalog manifest
criminal-db init

# Offline workflow (recommended): copy HTML into data/cases/… then ingest
cp my-case.html data/cases/fulltext/
criminal-db ingest                    # or: criminal-db ingest data/cases/fulltext

# Or parse individual files (routes headnotes vs fulltext automatically)
criminal-db parse path/to/case.html

# Harvest (only when permitted; blocked by CanLII robots.txt by default)
criminal-db harvest URL --save-html data/raw

# Embeddings + search (searches both db/fulltext.db and db/headnotes.db)
criminal-db embed
criminal-db search "section 8 charter unreasonable search" --type hybrid

# Catalog and stats
criminal-db index                     # list manifest entries
criminal-db analyze                   # per-store + total counts
```

### LLM / agent use

Pass `--json` for machine-readable stdout (see [docs/AGENTS.md](docs/AGENTS.md)):

```bash
criminal-db --json ingest
criminal-db --json search "voir dire" --type hybrid --limit 5
```

## Dual databases

| Database | Path | Contents |
|----------|------|----------|
| Full text | `db/fulltext.db` | Numbered decision paragraphs |
| Headnotes | `db/headnotes.db` | Summary / headnote paragraphs |

`parse`, `ingest`, and `harvest` (without `--db`) store each case in the
database matching its parsed `corpus`. `search`, `embed`, and `analyze`
(without `--db`) operate on **both** files and merge results.

## Criminal Code (statutes)

Parse offline HTML from [Justice Canada](https://laws-lois.justice.gc.ca/) into
`db/statutes.db`:

```bash
# Save HTML under data/statutes/criminal_code/ then:
criminal-db statutes parse
criminal-db statutes get 8
criminal-db search "unreasonable search" --scope statutes
criminal-db --json statutes search "detention"
```

## Criminal-law curation

Cases are tagged `is_criminal` using court-code heuristics, caption patterns
(`R. v.`, `R. c.`, etc.), and optional overrides in
`data/index/overrides.yaml`. **Search excludes non-criminal cases by default.**

```bash
criminal-db curate                  # re-apply rules to stored cases
criminal-db ingest --criminal-only  # skip non-criminal at ingest
criminal-db search "query" --include-all
```

## Catalog (`data/index/manifest.json`)

The manifest tracks every HTML source: SHA-256, parse status, target store, and
`case_id`. Re-running `ingest` skips unchanged files unless you pass `--force`.

```bash
criminal-db index --status ok
criminal-db index --status failed
```

## CanLII Terms of Use and robots.txt

CanLII's [`robots.txt`](https://www.canlii.org/robots.txt) ends with a
catch-all `User-agent: * / Disallow: /` — every path is disallowed for any
crawler that isn't Googlebot or Bingbot. Our default `criminal-db/*`
User-Agent falls under that rule, so the harvester (which has
`respect_robots=True` by default) will refuse to fetch CanLII case URLs out
of the box. **Do not** disable robots.txt enforcement to scrape CanLII at
scale — that is also a Terms-of-Use violation.

To use this project lawfully you need one of the following:

- a licensed CanLII bulk-data feed,
- explicit permission for the volume you intend to fetch, or
- locally saved HTML files that you obtained through permitted means.

The test suite in `tests/fixtures/real/` consists entirely of **synthetic**
HTML that mimics the structural shapes we see across courts and eras. It
does not contain CanLII content.

The default harvester uses a single, honest `User-Agent` (configurable via
the `CRIMINAL_DB_USER_AGENT` env var), a 5-second minimum delay between
requests, and a single concurrent connection. If you want to harvest at
larger scale, please use the official CanLII API.

Full policy for case text, exports, and hosting:
[docs/COPYRIGHT_AND_REDISTRIBUTION.md](docs/COPYRIGHT_AND_REDISTRIBUTION.md).

## Search semantics

`criminal-db search` joins user tokens with `OR` by default and lets the
SQLite FTS5 BM25 ranker order results — paragraphs that match more tokens
score higher, but a paragraph need not contain every token. You can force
strict-AND retrieval programmatically via
`Database.search_fts(query, ...)` with a pre-sanitised query, or by passing
explicit `AND` / `OR` / `NOT` / `NEAR` operators in the query string.

## Project layout

```
criminal_db/
    cli.py                # Click CLI (`criminal-db ...`)
    tui/                  # Textual menu (`criminal-db tui`)
    cli_output.py         # Rich tables + JSON helpers
    config.py             # Paths and tunables
    embedding.py          # Sentence-transformer wrapper
    catalog/
        manifest.py       # data/index/manifest.json
        ingest.py         # Batch ingest + SHA-256 skip
    db/
        schema.py         # DDL (cases, paragraphs, FTS5, vec0)
        operations.py     # Single-database facade
        router.py         # Dual-DB routing + unified search
    harvester/            # CanLII fetch + parse + listing links
data/
    cases/{fulltext,headnotes}/   # Offline HTML (gitignored)
    index/manifest.json           # Ingest catalog
    raw/                          # Optional harvest output
db/
    fulltext.db
    headnotes.db
docs/
    AGENTS.md             # LLM / automation guide
    COPYRIGHT_AND_REDISTRIBUTION.md
```

## Schema (high level)

- `cases(id PK, canlii_ref UNIQUE, neutral_citation, reporter_citation,
   court, court_year, decided_date, judges, corpus, is_headnote_only,
   source_url, fetched_at)`
- `paragraphs(id PK, case_id FK, paragraph_num, heading, text, is_headnote,
   is_ratio, section_number)` — one row per paragraph.
- `paragraphs_fts` — FTS5 over `paragraphs.text` and `paragraphs.heading`,
  kept in sync via insert/update/delete triggers.
- `paragraph_embeddings` — `sqlite-vec` `vec0` virtual table keyed by
  `paragraph_id`, dimension driven by `config.EMBEDDING_DIM`.

## Corpus build

See [docs/CORPUS.md](docs/CORPUS.md) for the full offline ingest workflow,
[docs/VALIDATION.md](docs/VALIDATION.md) for parser QA on saved HTML, and
`pytest tests/test_eval.py` for a small search regression suite.

## Copyright and redistribution

- **Software:** MIT — [LICENSE](LICENSE).
- **Case law and exports:** not included in this repo. You are responsible for
  lawful sources and for how you use `export`, `export-md`, `get`, and any
  hosted API. See [docs/COPYRIGHT_AND_REDISTRIBUTION.md](docs/COPYRIGHT_AND_REDISTRIBUTION.md).

## License

MIT applies to the **criminal-db source code** only. See [LICENSE](LICENSE).
