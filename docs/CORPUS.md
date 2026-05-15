# Building the criminal-law corpus

This guide covers populating **criminal-db** on a local machine for research
and LLM agents. It assumes you have permitted sources — not bulk CanLII
scraping (see README robots.txt section).

## 1. Initialise

```bash
python3 -m venv venv && source venv/bin/activate
pip install -e ".[embed,dev]"
criminal-db init
```

Creates:

- `db/fulltext.db`, `db/headnotes.db`, `db/statutes.db`
- `data/cases/{fulltext,headnotes}/`, `data/raw/`, `data/statutes/criminal_code/`
- `data/index/manifest.json`, `data/index/overrides.yaml`

## 2. Case law (offline HTML)

1. Save CanLII-style case HTML into:
   - `data/cases/fulltext/` — numbered decisions
   - `data/cases/headnotes/` — summary-only pages
2. Ingest and apply curation:

```bash
criminal-db ingest --criminal-only
criminal-db curate --json
criminal-db analyze
```

Re-runs skip unchanged files (SHA-256). Use `--force` to re-parse.

**Overrides:** edit `data/index/overrides.yaml` to force-include or exclude
citations that heuristics get wrong.

## 3. Criminal Code (Justice Canada)

1. Download or save HTML from [laws-lois.justice.gc.ca](https://laws-lois.justice.gc.ca/)
   (Criminal Code sections) into `data/statutes/criminal_code/`.
2. Parse:

```bash
criminal-db statutes parse
criminal-db statutes analyze
```

## 4. Embeddings (optional)

Requires a Python build with SQLite extension loading and `pip install -e ".[embed]"`:

```bash
criminal-db embed
```

## 5. Agent / script workflow

```bash
criminal-db --json search "voir dire admissibility" --type hybrid --limit 5
criminal-db --json get "2023 ONCA 712"
criminal-db --json search "unreasonable search" --scope statutes
criminal-db --json statutes get 8
```

Python API: `criminal_db.api.open_router`, `search`, `get_case`.

## 6. Regression eval

After changing parser or search logic:

```bash
pytest tests/test_eval.py -q
```

Uses synthetic fixtures only; extend `tests/eval/queries.json` as your corpus grows.

## 7. Export snapshot

```bash
criminal-db export -o snapshot/cases.json
```

JSON array suitable for **private backup or migration** on your machine. Do not
publish exports as an open dataset without rights to the underlying works. See
[COPYRIGHT_AND_REDISTRIBUTION.md](COPYRIGHT_AND_REDISTRIBUTION.md).
