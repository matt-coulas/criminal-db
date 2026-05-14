# criminal-db

A local-first Canadian criminal-law case database with hybrid full-text (FTS5)
and semantic (sqlite-vec) search over paragraph-level case content.

> **Status:** under active development. Schema and CLI may change.

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

## Quick start

```bash
# Initialise the SQLite databases
criminal-db init

# Parse a CanLII HTML file that you've already downloaded (offline)
criminal-db parse path/to/case.html

# Harvest a single CanLII case URL (respects ~5s delay, single User-Agent)
criminal-db harvest https://www.canlii.org/en/ca/scc/doc/2024/2024scc1/2024scc1.html

# Compute embeddings for any paragraphs that don't have one yet
criminal-db embed

# Search
criminal-db search "section 8 charter unreasonable search" --type hybrid
criminal-db search "voir dire admissibility" --court SCC --year 2024

# Stats
criminal-db analyze
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
    config.py             # Single source of truth for paths + settings
    cli.py                # Click CLI (`criminal-db ...`)
    embedding.py          # Sentence-transformer wrapper
    db/
        schema.py         # Schema DDL (cases, paragraphs, FTS5, vec0)
        operations.py     # Database facade
    harvester/
        fetcher.py        # aiohttp HTTP client with retries
        parser.py         # CanLII HTML -> CaseData
        listing.py        # Extract case URLs from listing pages
tests/
    fixtures/             # Saved CanLII-like HTML for offline testing
    test_*.py             # pytest suite
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

## License

MIT.
