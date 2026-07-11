# Sri Lanka Acts (Sinhala Only)

This repository publishes a Sinhala-only Sri Lanka Acts dataset, maintained independently by scraping the official Sri Lankan government documents website directly.

## What is included

- Acts only (no bills or gazettes)
- Sinhala documents only (`lang=si`)
- Folder layout: `{decade}/{year}/{doc_id}/`
- Typical files per act: `doc.json`, `doc.pdf`

> Note: PDF-to-HTML conversion is intentionally disabled for now because the current `pdfstruct` HTML parser does not support Sinhala. It will be re-enabled once Sinhala parsing is supported.

## Source

- Primary source website: [documents.gov.lk](https://documents.gov.lk)
- Metadata pages pattern: `https://documents.gov.lk/view/acts/acts_<YEAR>.html`
- PDF links are captured only for Sinhala acts (`*_S.pdf`)

## Automatic updates

This repository auto-scrapes and updates using GitHub Actions:

- Workflow: `.github/workflows/update-acts-si.yml` (`Update Sinhala Acts Dataset`)
- Schedule: daily
- Manual trigger: Actions -> "Update Sinhala Acts Dataset" -> Run workflow

## Local update command

```bash
python scripts/sync_sinhala_acts.py
```

The sync script scrapes directly from `documents.gov.lk`, upserts Sinhala acts metadata, and removes noisy generated files like `docs_*.tsv`, chart images, and per-document `README.md` files.
