# Copyright and redistribution policy

This document defines what **criminal-db** (the software) may be shared versus what
**corpus content** (case law, statutes, exports, embeddings) may be copied,
published, or served to others. It is written for operators building a local or
hosted deployment — not as legal advice. Confirm your sources and use case with
qualified counsel.

## Summary

| Asset | Typical rights holder | Shipped in this Git repo? | Redistribution |
|-------|----------------------|---------------------------|----------------|
| **Source code** (Python, docs, tests) | Project contributors (MIT) | Yes | Allowed under [LICENSE](../LICENSE) |
| **Synthetic test fixtures** | Project (original) | Yes | Allowed under MIT |
| **Case HTML/PDF you ingest** | Courts, authors, publishers; often via CanLII | No (`data/` gitignored) | **Your** obligation — see §3 |
| **SQLite databases** (`db/*.db`) | Extracted third-party text | No (gitignored) | **Not** for public republication without permission |
| **Markdown exports** (`data/cases/md/`) | Same as underlying decisions | No (gitignored) | Same as case text |
| **Criminal Code HTML** (Justice Canada) | His Majesty the King in Right of Canada | No (gitignored) | Often allowed under Open Government Licence — see §4 |
| **Embedding vectors** | Derived from text you had rights to process | No (in `db/*.db`) | Treat as sensitive as source text for external sharing |

**Default rule:** You may run criminal-db for **private research and internal
automation** on content you obtained lawfully. You may **not** treat
`criminal-db export`, `export-md`, or `get` output as a freely redistributable
dataset unless you have independent rights to every underlying work.

---

## 1. Two separate layers

1. **Software** — CLI, parsers, schema, tests, and documentation in this
   repository are licensed under the **MIT License** ([LICENSE](../LICENSE)).
   You may fork, modify, and redistribute the software subject to the MIT
   notice.

2. **Content** — Judgments, headnotes, and statute text loaded into
   `data/` and `db/` remain protected by **third-party copyright and licence
   terms**. MIT does **not** grant any rights to that content. The project
   maintainers do not supply a case corpus with the software.

---

## 2. What this repository contains

**Included in git**

- Application source, CI config, and operator docs.
- **Synthetic** HTML fixtures under `tests/fixtures/` that mimic CanLII layout
  shapes only. They do not reproduce real decisions from CanLII or courts.

**Excluded from git (see [.gitignore](../.gitignore))**

- `db/*.db` — parsed paragraphs, FTS indexes, optional vector embeddings.
- `data/raw/`, `data/cases/**` HTML/JSON, `data/import/**`, `data/cases/md/`,
  `data/statutes/criminal_code/**`, `data/index/manifest.json`.
- Downloaded embedding model weights under `models/`.

Operators are responsible for backups of local `data/` and `db/`; those backups
are subject to the same content rules as the live files.

---

## 3. Case law (HTML, PDF, harvest, import)

### 3.1 Rights in judgments

Canadian court decisions are often publicly available, but **availability is not
the same as an unlimited licence to copy, bulk download, or republish**. Rights
may rest with the court, the Crown, authors of reasons, and/or aggregators such
as the Canadian Legal Information Institute (CanLII).

### 3.2 CanLII and the harvester

- CanLII’s [`robots.txt`](https://www.canlii.org/robots.txt) disallows automated
  fetching for typical clients. **criminal-db** defaults to `respect_robots=True`
  and will refuse CanLII URLs for the default User-Agent.
- **Do not** set `CRIMINAL_DB_RESPECT_ROBOTS=0` to scrape CanLII at scale. That
  conflicts with CanLII’s terms and robots policy (see README).
- Lawful alternatives: **CanLII API or bulk feed with a written licence**,
  **explicit permission** for your volume, or **files you already obtained through
  permitted means** (e.g. court e-filing, paid services, your own saved HTML).

### 3.3 Offline ingest and import (recommended path)

These commands process **files you place on disk**; they do not grant rights to
the files:

- `criminal-db ingest` — HTML under `data/cases/`
- `criminal-db import` — HTML/PDF under `data/import/` ([IMPORT.md](IMPORT.md))
- `criminal-db parse` — arbitrary paths

**You must ensure** each file was obtained and retained in compliance with its
source’s terms (CanLII, court website, publisher PDF, etc.). PDF import uses
heuristic text extraction; quality and citation metadata may require manual
review — that does not change copyright status.

### 3.4 What you may do with stored cases (typical research use)

Generally appropriate **without** extra permission (subject to your source
licence):

- Private study and legal research on your own machine.
- Internal firm or team use behind access controls, without publishing full
  text to the public internet.
- LLM agents calling the **local** CLI (`--json`) against **your** databases,
  with retrieval limited to what your licence allows (often short excerpts in
  prompts rather than bulk republication of judgments).

### 3.5 What you must not do without separate permission

- Publish `db/*.db`, full `criminal-db export` JSON, or `export-md` trees as an
  open dataset, Hugging Face corpus, or commercial product.
- Operate a **public** search API or MCP server that returns full paragraph text
  to unauthenticated users.
- Strip attribution (neutral citation, court, date, source URL where known).
- Use the harvester to circumvent CanLII or court access controls.

### 3.6 Attribution

When citing or displaying retrieved text, use the case’s **neutral citation**
(e.g. `2024 SCC 1`) and, where stored, `source_url` from the database. For
CanLII-sourced HTML, CanLII’s terms may require specific attribution — follow
your source agreement.

---

## 4. Statutes (Justice Canada / Criminal Code)

Federal statute HTML from
[laws-lois.justice.gc.ca](https://laws-lois.justice.gc.ca/) is commonly made
available under the
[Open Government Licence – Canada](https://open.canada.ca/en/open-government-licence-canada)
(OGL-Canada), which permits use, reproduction, and publication with conditions
(including attribution and no endorsement misrepresentation).

**criminal-db** only stores text you download or save locally
(`criminal-db statutes parse`). Operators should:

- Keep a record of **which snapshot date** of the Criminal Code was ingested.
- Apply OGL-Canada terms when **republishing** statute text or large extracts
  outside a private database.
- Not assume OGL-Canada covers **case law** or **commentary** on third-party
  sites.

If you redistribute parsed statute sections from `db/statutes.db` or exports,
include appropriate Crown copyright / OGL-Canada notice per current Justice
Canada guidance.

---

## 5. Local artifacts and sensitivity

| Path | Contents | Share outside your org? |
|------|----------|-------------------------|
| `data/cases/**/*.html` | Original or saved HTML | Only if source licence allows |
| `data/import/**` | Staged import files | Same as source |
| `data/raw/` | Harvest output (if used) | Same as source |
| `db/criminal.db` | Full paragraph text + search indexes (cases) | **No** public redistribution by default |
| `db/statutes.db` | Criminal Code sections | OGL-Canada may allow with conditions |
| `data/cases/md/*.md` | Optional markdown mirror of cases | Same as case text |
| `data/index/manifest.json` | Paths, hashes, citations (metadata) | Low risk alone; may still identify corpus |
| Embedding tables in `db/*.db` | Numerical vectors derived from text | Do not publish as a substitute for licensed text |

---

## 6. CLI exports and agent output

Commands that **copy text out** of the database:

| Command | Output | Redistribution note |
|---------|--------|---------------------|
| `criminal-db get` | One case (text or JSON) | Fine for internal/agent use; do not bulk-post online |
| `criminal-db export` | Many cases as JSON | **Backup / migration only** unless you have rights to all cases |
| `criminal-db export-md` | One `.md` per case | Same as underlying decisions |
| `criminal-db search` | Snippets + metadata | Snippets may be acceptable for research; check source terms for scale |
| `criminal-db --json …` | Machine-readable stdout | Same rules as the underlying command |

[docs/CORPUS.md](CORPUS.md) describes corpus build; exports are for **your**
backups and tooling, not for shipping a third-party case law package with the
software.

---

## 7. Hosted, multi-user, and MCP deployments

If you expose criminal-db beyond a single user’s laptop:

1. **Authentication and access control** — restrict who can run search/export.
2. **Rate and volume limits** — avoid de facto republication via repeated `get`
   or large `export` calls.
3. **Terms of use** — tell users they may not scrape your endpoint to rebuild the
   corpus.
4. **Logging** — avoid logging full paragraph text if logs are widely accessible.
5. **Data residency** — `db/` and `data/` remain your compliance boundary; MIT
   does not transfer CanLII or court rights to your users.

A future HTTP or MCP wrapper must inherit this policy; the maintainers do not
endorse public full-text mirrors built with this tool without proper licences.

---

## 8. Embeddings and derived indexes

Vector embeddings (`criminal-db embed`, `paragraph_embeddings` in SQLite) are
**mathematical derivatives** of paragraph text. They are not a substitute for a
text licence:

- **Private search** on your own machine: generally aligned with private research
  use of the source text.
- **Publishing** embedding files or a vector index built from unlicensed bulk
  CanLII HTML may still raise copyright and contractual issues. Treat published
  embeddings like published text unless counsel advises otherwise.

---

## 9. Software distribution (PyPI, Docker, forks)

You may distribute **the criminal-db package** under MIT. If you publish a Docker
image or installer:

- **Do not** bundle `db/*.db`, `data/cases/`, or sample real judgments.
- **Do** document that users must supply their own permitted sources.
- **Do** link to this policy and the README CanLII section.

Forks that pre-load a corpus into the image violate this policy unless every
included work is clearly licensed for redistribution.

---

## 10. Operator compliance checklist

Before calling a deployment “production”:

- [ ] Written basis for **each** source (CanLII licence/API, court permission,
      OGL-Canada for statutes, owned PDFs, etc.).
- [ ] `data/` and `db/` **not** committed to git and **not** in public artifacts.
- [ ] Harvester robots respect **left enabled** unless a specific URL is
      explicitly allowed by the site owner.
- [ ] `export` / `export-md` outputs classified (internal backup vs public dataset).
- [ ] Hosted endpoints (if any) have auth, ToS, and no open full-text bulk download.
- [ ] Attribution practice documented for your team (citation + source URL).
- [ ] Backup encryption and retention policy if databases contain client matter.

---

## 11. Questions and updates

- Software licence: [LICENSE](../LICENSE)
- CanLII / robots: [README](../README.md#canlii-terms-of-use-and-robotstxt)
- Offline cases: [IMPORT.md](IMPORT.md), [CORPUS.md](CORPUS.md)
- Parser QA (no DB): [VALIDATION.md](VALIDATION.md)

If you believe bundled material in this repository infringes copyright, open an
issue with the path and nature of the work; synthetic fixtures only are intended
to ship in git.

**Last updated:** 2026-05-15 (policy version 1.0)
