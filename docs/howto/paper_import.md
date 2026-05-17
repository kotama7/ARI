# Importing external papers

The paper registry (`~/.ari/paper_registry/`) holds external papers the
PaperBench wizard can run audits against. This page covers the four
import paths and license handling.

## Storage layout

```
{ARI_PAPER_REGISTRY_DIR or ~/.ari/paper_registry}/
├── manifest.jsonl            # one paper per line (JSON)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # source PDF (optional but recommended)
        ├── ad.pdf            # artifact description (optional)
        └── ae.pdf            # artifact evaluation (optional)
```

Override the root with `ARI_PAPER_REGISTRY_DIR`.

## Import paths

### arXiv ID

Most-used path. Fill the wizard with `source_type=arxiv` and
`source=2404.14193`. Auto-fetch of metadata + PDF from arXiv is
deferred to a follow-up release; for v0.7.2 you still need to type
title / authors / license by hand.

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv",
    "source": "2404.14193",
    "title": "LLAMP: assessing latency tolerance",
    "license": "CC BY 4.0",
    "authors": ["Alice", "Bob"],
    "year": 2024,
    "venue": "SC24",
    "artifact_url": "https://github.com/spcl/llamp"
  }'
```

### DOI

Same form as arXiv but `source_type=doi`, `source=10.1109/<conf>.YYYY.NNNNN`
(e.g. an ACM DL or IEEE Xplore DOI for an SC, OSDI, or USENIX paper).
Use for IEEE/ACM papers that are not on arXiv.

### Upload (local PDF)

`source_type=upload`. Use `/api/upload` to stash the PDF first, then
pass its path as `pdf_path`:

```bash
TMP=$(curl -F 'file=@./mypaper.pdf' http://localhost:8765/api/upload | jq -r .path)
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d "{
    \"source_type\": \"upload\",
    \"source\": \"local-upload-$(date +%s)\",
    \"title\": \"My SC24 camera-ready\",
    \"license\": \"IEEE Author proprietary\",
    \"pdf_path\": \"$TMP\"
  }"
```

The PDF is copied into `papers/<paper_id>/paper.pdf`. AD / AE
appendices follow the same path under `ad_pdf_path` / `ae_pdf_path`.

### Local path

`source_type=local`. For PDFs already on disk where you don't need ARI
to re-host them — the registry entry just points at the existing path.

## License classification

License strings are normalized (lower-cased, whitespace-stripped) and
classified into a 4-quadrant assessment:

| Status | Examples |
|---|---|
| **usable** (permissive AND redistributable) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, CC BY-NC, arXiv non-exclusive |
| permissive only (NOT redistributable) | (none currently — kept as a placeholder) |
| **NOT usable** | proprietary, IEEE author, ACM author, "all rights reserved", unknown strings |

The classification is heuristic and **advisory**. Final legal review
remains the user's responsibility. The GUI shows a green ✅ badge for
usable, amber ⚠ for not — both still let the registration go through.

Inspect a paper's assessment:

```bash
curl http://localhost:8765/api/paperbench/papers/<paper_id>/license
```

## Duplicate detection

Imports with the same `paper_id` (default: sanitized `source`) are
blocked unless `overwrite=true` is passed:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/import \
  -H 'Content-Type: application/json' \
  -d '{
    "source_type": "arxiv", "source": "2404.14193",
    "title": "LLAMP v2", "license": "CC BY 4.0",
    "overwrite": true
  }'
```

`paper_id` is itself sanitized to `[A-Za-z0-9._-]{1,64}` — any other
characters become `-`.

## Deletion

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

Idempotent (returns `{deleted: false, reason: "not found"}` when the
id is unknown).

## Metadata patches

For fixing typos without losing the registry slot:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` is immutable.

## See also

- [PaperBench GUI guide](paperbench_gui.md)
- [API reference](../reference/api_paperbench.md)
