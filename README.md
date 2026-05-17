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

## Development setup

Requires **Python 3.11+** (3.12 recommended) with SQLite loadable extensions for
vector/hybrid search. On macOS, prefer Homebrew or [python.org](https://www.python.org/)
over the Xcode-bundled Python if `embed` fails.

```bash
git clone https://github.com/matt-coulas/criminal-db.git
cd criminal-db
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -e ".[embed,dev,tui,pdf]"
```

| Extra | Purpose |
|-------|---------|
| `embed` | Sentence-transformers + hybrid/vector search |
| `dev` | pytest, ruff |
| `tui` | `criminal-db tui` (Textual) |
| `pdf` | PDF import (PyMuPDF) |

FTS-only workflows work without `embed`. Optional env vars: copy
[.env.example](.env.example) and `export` what you need.

```bash
criminal-db init
pytest -q
```

Optional JSON HTTP API (separate terminal):

```bash
criminal-db serve --host 127.0.0.1 --port 8765
curl -s http://127.0.0.1:8765/health
```

See [docs/RUNBOOK.md](docs/RUNBOOK.md) for operations and
[docs/CORPUS.md](docs/CORPUS.md) for building a corpus.

## Quick start

```bash
# Initialise databases, data/ layout, and catalog manifest (creates db/criminal.db)
criminal-db init

# Offline workflow (recommended): copy HTML into data/cases/… then ingest
cp my-case.html data/cases/fulltext/
criminal-db ingest                    # or: criminal-db ingest data/cases/fulltext

# Or parse individual files (routes headnotes vs fulltext automatically)
criminal-db parse path/to/case.html

# Harvest (only when permitted; blocked by CanLII robots.txt by default)
criminal-db harvest URL --save-html data/raw

# Embeddings + search (default: db/criminal.db)
criminal-db embed
criminal-db search "section 8 charter unreasonable search" --type hybrid

# Catalog and stats
criminal-db index                     # list manifest entries
criminal-db analyze                   # case DB + statutes stats
```

### LLM / agent use

Pass `--json` for machine-readable stdout (see [docs/AGENTS.md](docs/AGENTS.md)):

```bash
criminal-db --json ingest
criminal-db --json search "voir dire" --type hybrid --limit 5
```

## Case database

By default all cases live in one SQLite file, **`db/criminal.db`**, with a
`corpus` column distinguishing fulltext vs headnote paragraphs.

`parse`, `ingest`, and `harvest` (without `--db`) store each case in that
file. `search`, `embed`, and `analyze` (without `--db`) query it once.

Legacy split layout (two files) is still supported when **both**
`CRIMINAL_DB_FULLTEXT_DB` and `CRIMINAL_DB_HEADNOTES_DB` point at different
paths. Set a single legacy var to use one file at that path. Override the
unified default with `CRIMINAL_DB_CASE_DB`.

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
        router.py         # Case DB routing + multi-store search
    harvester/            # CanLII fetch + parse + listing links
data/
    cases/{fulltext,headnotes}/   # Offline HTML (gitignored)
    index/manifest.json           # Ingest catalog
    raw/                          # Optional harvest output
db/
    criminal.db
    statutes.db
docs/
    AGENTS.md             # LLM / automation guide
    CORPUS.md             # Offline ingest workflow
    RUNBOOK.md            # Operations
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
