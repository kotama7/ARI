# scripts/fewshot

Tooling to fetch the few-shot review corpus into `ari-core/config/reviewer_rubrics/fewshot_examples/`.

## Contents

- `README.md` — this file.
- `fetch_arxiv.py` — per-source fetcher for arXiv.
- `fetch_github_raw.py` — per-source fetcher for raw GitHub URLs.
- `fetch_openreview.py` — per-source fetcher for OpenReview.
- `manifest.yaml` — corpus manifest (per entry: `id`, `source`, `license`, optional `note`).
- `sync.py` — reads the manifest and dispatches to the matching fetcher.
