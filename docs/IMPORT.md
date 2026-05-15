# Importing cases without CanLII scraping

Use `criminal-db import` when you have saved HTML or PDF decisions and cannot (or should not) harvest from CanLII. Files are staged under `data/import/`, parsed, stored via the dual-database router, and tracked in `data/index/manifest.json`.

## Setup

```bash
criminal-db init
```

This creates `data/import/html/` and `data/import/pdf/` as drop zones.

## Drop files

1. Copy saved CanLII-style HTML (`.html`, `.htm`) into `data/import/html/`.
2. Copy decision PDFs into `data/import/pdf/`.
3. Run:

```bash
criminal-db import
```

Or pass explicit paths (files or directories):

```bash
criminal-db import ~/Downloads/decision.pdf
criminal-db import data/import/html/my-case.html --force
```

Files outside `data/import/` are copied into the appropriate subfolder before parsing.

## HTML vs PDF

| Format | Behaviour |
|--------|-----------|
| **HTML** | Parsed with `CanLIIParser` (same pipeline as `criminal-db ingest`). |
| **PDF** | Text extracted per page; paragraphs heuristically split (`[1]`, `1.`, blank lines). Wrapped as minimal CanLII-style HTML, then parsed. Requires optional dependency: `pip install 'criminal-db[pdf]'` (PyMuPDF). |

## Flags

- `--force` — re-parse even when the file SHA-256 is unchanged.
- `--criminal-only` — skip cases that fail criminal-law curation rules (manifest status `excluded`).
- `--json` — machine-readable report on stdout (for scripts and agents).

Example agent-friendly run:

```bash
criminal-db --json import data/import/pdf/ --criminal-only
```

## Manifest fields

Each import adds or updates a catalog entry with:

- `source_type`: `html` or `pdf`
- `original_filename`: name of the file you provided (before staging)
- `status`: `ok`, `skipped`, `failed`, or `excluded`
- `parse_error`: e.g. `no citation detected; manual review needed (PDF import)` when a neutral citation could not be found

Skipped PDFs are not stored in the databases until you fix metadata or add a proper HTML source.

## PDF install error

If PyMuPDF is not installed:

```
PDF import requires PyMuPDF. Install with: pip install 'criminal-db[pdf]'
```

HTML import works without that extra.
