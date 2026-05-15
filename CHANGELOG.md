# Changelog

All notable changes to the **criminal-db** software are documented here. Corpus
content in `data/` and `db/` is not part of releases.

## [0.3.0] - 2026-05-15

### Added

- Docker image, `compose.yaml`, and [docs/DOCKER.md](docs/DOCKER.md)
- Configurable host volumes: `CORPUS_DATA_PATH`, `CORPUS_DB_PATH`, `CORPUS_MODELS_PATH`
- Ports: `API_PORT`, `WEB_UI_PORT` (reserved for future web UI)
- `criminal-db-tui` — Textual terminal UI for all major operations
- `CRIMINAL_DB_*_DIR` env overrides for container paths
- `/health` exempt from API token auth (for Docker healthchecks)

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
