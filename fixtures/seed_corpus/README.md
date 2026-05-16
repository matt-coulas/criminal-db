# Seed corpus (starter database)

Drop **CanLII-style HTML** or **decision PDFs** here to build a reusable test
database (`criminal-db[pdf]` / PyMuPDF required for PDF).

## Layout

Any nested tree works; the ingest step scans recursively. Recommended:

```text
incoming/
  uploads/            # put your HTML or PDF here (gitignored)
  SCC/2024/…          # synthetic smoke-test samples (in repo)
  FCA/2023/…
  real/ONCA/2022/…
  fulltext/…          # optional: path segment selects fulltext.db
  headnotes/…         # optional: path segment selects headnotes.db
```

Files must parse to a neutral citation (`2024 SCC 1`, etc.) or they are skipped.

## Build

From the repo root:

```bash
# Default: read incoming/, write db/seed/ and data/seed/
criminal-db seed-build

# Custom folders
criminal-db seed-build -i /path/to/your/html -o db/seed

# Copy seed DBs into db/ for Docker / local API
criminal-db seed-build --install
```

## Use with Docker

```bash
criminal-db seed-build --install   # copies into ./db/
docker compose up -d api
```

Or mount `db/seed` explicitly in `compose.yaml` volume paths.

## Starter files

The repo may ship a few **synthetic** HTML files under `incoming/` for CI and
local smoke tests. Replace or add your licensed research corpus in the same tree.
