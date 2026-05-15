# Parser validation (QA)

Before ingesting a batch of saved HTML, dry-run the parser:

```bash
criminal-db validate data/import/html/
criminal-db validate path/to/case.html
criminal-db --json validate data/cases/fulltext/
```

No database writes. Exit code is **1** if any file has errors.

## Checks

| Code | Level | Meaning |
|------|-------|---------|
| `unknown_citation` | error | No neutral citation found |
| `no_paragraphs` | error | Parser returned zero paragraphs |
| `duplicate_paragraph_nums` | warn | Repeated paragraph numbers |
| `headnote_with_numbers` | warn | Headnote corpus but numbered paras |
| `fulltext_without_numbers` | warn | Fulltext but no ¶ numbers |
| `no_judges` | warn | No judges in panel metadata |
| `many_short_paragraphs` | warn | Possible PDF/OCR fragment |

## Recommended workflow

1. Drop files in `data/import/html/` or `data/import/pdf/`
2. `criminal-db validate …`
3. Fix HTML or add `data/index/overrides.yaml` if needed
4. `criminal-db import` or `criminal-db ingest --criminal-only`
