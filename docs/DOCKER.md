# Docker and Compose

Run **criminal-db** with persistent corpus volumes and an optional JSON API + TUI.

## Quick start

```bash
cp .env.docker.example .env
mkdir -p data db models

docker compose build
docker compose up -d api

# One-time / after adding files to ./data
docker compose run --rm cli init
docker compose run --rm cli import --criminal-only
docker compose run --rm cli embed --scope all

# Interactive TUI
docker compose run --rm tui
```

## Services

| Service | Purpose |
|---------|---------|
| `api` | HTTP JSON API (`criminal-db serve`) on port **API_PORT** (default 8765) |
| `tui` | Full-screen terminal UI (`criminal-db-tui`) — profile `tui` |
| `cli` | One-off CLI commands — profile `cli` |

```bash
docker compose run --rm cli search "voir dire" --type hybrid
docker compose run --rm cli curate --report
```

## Volume layout

| Host env | Container | Contents |
|----------|-----------|----------|
| `CORPUS_DATA_PATH` | `/data` | HTML, import drop zone, manifest, statutes |
| `CORPUS_DB_PATH` | `/db` | `fulltext.db`, `headnotes.db`, `statutes.db` |
| `CORPUS_MODELS_PATH` | `/models` | Embedding model cache |

Set paths in `.env` to absolute directories on the host, e.g.:

```env
CORPUS_DATA_PATH=/srv/criminal-db/data
CORPUS_DB_PATH=/srv/criminal-db/db
```

## Ports

| Variable | Default | Notes |
|----------|---------|--------|
| `API_PORT` | 8765 | Maps to API `GET /health`, `/search`, `/get` |
| `WEB_UI_PORT` | 8080 | Reserved for a future web UI (not used yet) |

## Environment

| Variable | Description |
|----------|-------------|
| `API_TOKEN` | If set, API requires `Authorization: Bearer …` or `X-API-Token` |
| `EMBEDDING_MODEL` | Sentence-transformers model name |
| `MAX_QUERY_LEN` | FTS query length cap |
| `RESPECT_ROBOTS` | `1` = obey CanLII robots.txt (default) |

Internal paths are set via `CRIMINAL_DB_DATA_DIR`, `CRIMINAL_DB_DB_DIR`, `CRIMINAL_DB_MODELS_DIR` in `compose.yaml`.

## TUI

The TUI exposes init, import, ingest, parse, search, get, curate (incl. QA report), validate, verify, embed, analyze, backup, restore, export, and catalog index.

```bash
docker compose run --rm tui
```

Requires an interactive terminal (`-it` is set via `stdin_open` / `tty`).

## API examples

```bash
curl "http://localhost:8765/health"
curl "http://localhost:8765/search?q=section+8&scope=all&type=fts"
curl "http://localhost:8765/get?citation=2024+SCC+1"
```

With token:

```bash
curl -H "Authorization: Bearer $API_TOKEN" "http://localhost:8765/search?q=charter"
```

## Legal note

Mount only corpus files you have rights to use. See [COPYRIGHT_AND_REDISTRIBUTION.md](COPYRIGHT_AND_REDISTRIBUTION.md).
