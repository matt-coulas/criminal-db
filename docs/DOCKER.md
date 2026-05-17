# Docker and Docker Compose

The container image ships the **criminal-db** CLI with optional extras preinstalled:

| Extra | In image? | Purpose |
|-------|-----------|---------|
| `embed` | yes | `sentence-transformers` + hybrid/vector search |
| `pdf` | yes | PDF import via PyMuPDF |
| `tui` | yes | `criminal-db tui` (Textual) |

The image does **not** include case law HTML, SQLite databases, or downloaded embedding weights.
Mount host directories for `data/`, `db/`, and `models/` (see [Copyright](../COPYRIGHT_AND_REDISTRIBUTION.md)).

There is **no browser web UI** yet. Compose publishes the JSON HTTP API (`criminal-db serve`).
Use the TUI interactively (`docker compose run --rm tui`) or the CLI on the host.

## Prerequisites

- Docker Engine 24+ and Docker Compose v2
- Host directories (create if missing):

```bash
mkdir -p data db models
cp .env.docker.example .env   # optional; edit ports and paths
```

## Build locally

```bash
docker build -t criminal-db:local .
```

## Run with Compose

```bash
docker compose up -d api
curl -s "http://127.0.0.1:8765/health"
```

Default service: **`api`** — runs `criminal-db serve` after `init` when `db/*.db` are missing.

### Interactive TUI

```bash
docker compose --profile tui run --rm tui
```

Requires a TTY (`stdin_open` / `tty` in `compose.yaml`).

### One-off CLI

```bash
docker compose run --rm api criminal-db analyze
docker compose run --rm api criminal-db ingest data/cases/fulltext
```

## Volume and corpus layout

| Host path (default) | Container path | Contents |
|---------------------|------------------|----------|
| `./data` | `/app/data` | HTML corpus, `index/manifest.json`, `cases/md/`, statutes HTML |
| `./db` | `/app/db` | `criminal.db`, `statutes.db`, backups |
| `./models` | `/app/models` | Cached embedding models (`models/embeddings/`) |

Workflow:

1. Place permitted HTML under `data/cases/fulltext`, `data/import`, etc.
2. `docker compose run --rm api criminal-db ingest` (or use the TUI).
3. `docker compose run --rm api criminal-db embed` (downloads model into `./models` on first run).
4. Search via API or CLI.

SQLite and the manifest persist on the host across container restarts.

## Environment variables

See `.env.docker.example`. Common settings:

| Variable | Default | Description |
|----------|---------|-------------|
| `CRIMINAL_DB_HOST_PORT` | `8765` | Host port → API |
| `CRIMINAL_DB_DATA_DIR` | `./data` | Host corpus mount (→ `/app/data`) |
| `CRIMINAL_DB_DB_DIR` | `./db` | Host database mount (→ `/app/db`) |
| `CRIMINAL_DB_CASE_DB` | `/app/db/criminal.db` | Unified case SQLite file |
| `CRIMINAL_DB_MODELS_DIR` | `./models` | Host model cache mount (→ `/app/models`) |
| `CRIMINAL_DB_API_HOST` | `0.0.0.0` | Bind address inside container |
| `CRIMINAL_DB_API_PORT` | `8765` | API port inside container |
| `CRIMINAL_DB_API_TOKEN` | (empty) | Optional Bearer token |
| `CRIMINAL_DB_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Hugging Face model id |
| `CRIMINAL_DB_EMBEDDING_DIM` | `384` | Vector dimension |
| `CRIMINAL_DB_RESPECT_ROBOTS` | `1` | CanLII harvester robots.txt |
| `CRIMINAL_DB_USER_AGENT` | (built-in) | Harvester User-Agent |
| `CRIMINAL_DB_DELAY_MIN` / `MAX` | `5.0` / `9.0` | Harvest delay bounds |
| `CRIMINAL_DB_MAX_QUERY_LEN` | `500` | API search query cap |

## Publish images (GitHub Actions)

**Step-by-step guide:** [GITHUB_ACTIONS_DOCKER.md](GITHUB_ACTIONS_DOCKER.md)

Workflows in `.github/workflows/`:

- `docker-publish-ghcr.yml` — pushes to `ghcr.io/<owner>/criminal-db` (no extra secrets)
- `docker-publish-dockerhub.yml` — pushes to Docker Hub (needs `DOCKERHUB_USERNAME` + `DOCKERHUB_TOKEN` secrets)

Quick start: push to `main` or tag `v0.3.0`, then pull `ghcr.io/OWNER/criminal-db:latest`.

### Manual push (optional)

```bash
echo "$GITHUB_TOKEN" | docker login ghcr.io -u OWNER --password-stdin
docker build -t ghcr.io/OWNER/criminal-db:latest .
docker push ghcr.io/OWNER/criminal-db:latest
```

Do not bake copyrighted CanLII HTML or full corpora into the image or registry layer cache.
