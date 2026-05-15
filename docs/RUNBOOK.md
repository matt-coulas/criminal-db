# Production runbook

Operator guide for a local **criminal-db** deployment. See
[COPYRIGHT_AND_REDISTRIBUTION.md](COPYRIGHT_AND_REDISTRIBUTION.md) for content
licensing.

## Prerequisites

- Python 3.11+ with SQLite extension loading (for vector/hybrid search)
- `pip install -e ".[embed,dev]"` and optional `criminal-db[pdf]`
- Permitted case HTML/PDF and Justice Canada statute HTML

## Initial setup

```bash
cp .env.example .env   # optional; export vars you need
criminal-db init
# Add sources → criminal-db import / ingest / statutes parse
criminal-db curate --json
criminal-db embed --scope all
criminal-db verify
```

## Routine operations

| Task | Command |
|------|---------|
| Parser QA (no DB) | `criminal-db validate path/to/file.html` |
| Ingest new cases | `criminal-db ingest --criminal-only` |
| Re-embed new paragraphs | `criminal-db embed` (skips existing vectors) |
| Curation QA report | `criminal-db curate --report` (add `--dry-run` to preview) |
| Consistency check | `criminal-db verify` |
| Backup | `criminal-db backup db/backups` |
| Restore | `criminal-db restore db/backups/criminal-db-backup-*.tar.gz` |
| Stats | `criminal-db analyze` / `criminal-db statutes analyze` |

## HTTP API (agents)

```bash
export CRIMINAL_DB_API_TOKEN=local-dev-secret   # optional
criminal-db serve --host 127.0.0.1 --port 8765
```

Endpoints:

- `GET /health`
- `GET /search?q=...&scope=cases|statutes|all&type=fts|hybrid&limit=10`
- `GET /get?citation=2024%20SCC%201`
- `POST /search` with JSON body `{"q": "...", "type": "fts", "limit": 5}`

Bind to localhost unless you add TLS, authentication, and a terms-of-use layer
for any network exposure.

## Disk and memory

| Component | Rough size |
|-----------|------------|
| `db/fulltext.db` | Depends on corpus; FTS + vec grow with paragraph count |
| Embedding model cache | ~130 MB under `models/embeddings/` |
| RAM during `embed` | Model + batch (default batch 32) |

Use WAL mode (default). Run `criminal-db backup` before schema upgrades.

## Upgrades

1. `criminal-db backup db/backups`
2. Pull new software; `pip install -e ".[embed,dev]"`
3. `criminal-db init` (applies idempotent migrations)
4. `pytest -q` on your machine
5. `criminal-db verify`

## CI / quality

```bash
pytest -q
pytest tests/test_eval.py -q
ruff check criminal_db tests   # if ruff installed
```

## Limits

- Default max search query length: 500 chars (`CRIMINAL_DB_MAX_QUERY_LEN`)
- SQLite: single writer; multiple readers OK
- Do not bulk-scrape CanLII (see README)

## Troubleshooting

| Symptom | Action |
|---------|--------|
| Vector search disabled | Use python.org/homebrew Python with extension loading |
| `manifest_case_missing` | Re-ingest or fix manifest; `criminal-db verify` |
| FTS drift | Rare; restore from backup or re-ingest affected cases |
| PDF import fails | `pip install 'criminal-db[pdf]'` |
