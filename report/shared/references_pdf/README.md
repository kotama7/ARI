# Reference PDFs

This directory holds local copies of papers cited in `../references.bib`.

- **PDFs themselves are gitignored** (copyright). Only metadata is committed.
- **Metadata files (`*.pdf.meta.yaml`) are committed** for reproducibility.

## Fetch all referenced PDFs

```bash
make pull-pdfs
```

This reads every `*.pdf.meta.yaml` and re-downloads from `source.preferred_url`.
Files are verified against the recorded sha256.

## Add a new reference + PDF

```bash
python scripts/fetch_bib.py "<arxiv-id-or-doi-or-url>" --with-pdf
```

This:

1. Fetches the BibTeX from a primary source (arXiv / DOI / OpenReview).
2. Verifies the entry against Semantic Scholar (title / authors / year edit-distance).
3. Appends to `../references.bib` and `../references.log.yaml`.
4. Downloads the PDF (S2 `openAccessPdf` → arXiv → OpenReview → DOI).
5. Writes `<citekey>.pdf.meta.yaml` with provenance.

## Closed-access papers

When `meta.yaml` shows `closed_access: true`:

1. Download the PDF via your institutional access.
2. Place it as `<citekey>.pdf` in this directory.
3. Run `python scripts/verify_pdf.py <citekey>` to populate `sha256` and `page_count` in the meta file.

## Why we keep PDFs locally (and metadata in git)

- **No-citation-without-reading rule**: encourages authors to actually read the paper.
- **Reviewer verification**: PR reviewers can spot-check claims against the source.
- **LLM-assisted translation**: a paragraph from the PDF can be passed to the translator if a passage is ambiguous.
- **Offline editing**: the report can be drafted on flights / air-gapped HPC nodes.

The metadata file (committed) is the redistributable contract; the PDF is not.
