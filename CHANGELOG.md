# Changelog

All notable changes to the **criminal-db** software are documented here. Corpus
content in `data/` and `db/` is not part of releases.

## [0.3.1] - 2026-05-16

### Added

- README: full Docker install guide, env var table, annotated `compose.yaml` example
- [docs/GITHUB_ACTIONS_DOCKER.md](docs/GITHUB_ACTIONS_DOCKER.md) and GHCR/Docker Hub publish workflows
- `criminal-db seed-build` with `--db` for a single output file; `CRIMINAL_DB_CASE_DB` env var

### Changed

- **Default case database is one file:** `db/criminal.db` (fulltext + headnotes via `corpus` column).
  Legacy split layout remains when `CRIMINAL_DB_FULLTEXT_DB` and `CRIMINAL_DB_HEADNOTES_DB` point at different paths.
- Docker entrypoint and Compose set `CRIMINAL_DB_CASE_DB=/app/db/criminal.db`.

## [0.3.0] - 2026-05-16

### Added

- Docker image, `compose.yaml`, and [docs/DOCKER.md](docs/DOCKER.md)
- `criminal-db tui` — Textual terminal UI (`criminal-db[tui]`)
- `CRIMINAL_DB_DATA_DIR`, `CRIMINAL_DB_DB_DIR`, `CRIMINAL_DB_MODELS_DIR` path overrides
- `/health` exempt from API token auth (Docker healthchecks)

## [0.2.0] - 2026-05-15

### Added

- `criminal-db verify` — manifest ↔ database consistency checks
- `criminal-db backup` / `restore` — tarball of databases and catalog
- `criminal-db serve` — local JSON HTTP API (`/health`, `/search`, `/get`)
- `search --scope all` — merged case + statute FTS/hybrid results
- `embed --scope statutes|all` — Criminal Code section embeddings
- Statute vector and hybrid search
- Versioned schema migrations (`schema_version` table)
- [docs/COPYRIGHT_AND_REDISTRIBUTION.md](docs/COPYRIGHT_AND_REDISTRIBUTION.md)
- [docs/RUNBOOK.md](docs/RUNBOOK.md), [docs/MCP_TOOLS.json](docs/MCP_TOOLS.json)
- Citation lookup variants (`citation_lookup_variants`)
- `.env.example` for operator configuration

### Changed

- `normalize_canlii_ref` accepts more neutral citation shapes
- FTS queries truncated at `CRIMINAL_DB_MAX_QUERY_LEN` (default 500)
- README: copyright section; beta status clarified

## [0.1.0] - 2025

Initial beta: dual case databases, ingest/import, statutes, hybrid search, curation, eval suite.
