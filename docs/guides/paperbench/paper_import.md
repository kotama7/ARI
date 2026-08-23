---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-core/ari/viz/api_paperbench_worker.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/api_tools.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/PaperBench/PaperImportDialog.tsx
    role: implementation
last_verified: 2026-08-16
---

# Importing external papers

The paper registry holds external papers the PaperBench wizard can run
audits against. This page covers the four import paths and license
handling.

## Storage layout

```
{ARI_PAPER_REGISTRY_DIR or {workspace_root}/paper_registry}/
├── manifest.jsonl            # one paper per line (JSON)
├── jobs/
│   └── <job_id>.json         # durable run records (mode 0600)
└── papers/
    └── <paper_id>/
        ├── paper.pdf         # required before a run can start
        ├── ad.pdf            # artifact description (optional)
        └── ae.pdf            # artifact evaluation (optional)
```

The root is `ARI_PAPER_REGISTRY_DIR` when set, otherwise
`PathManager.from_env().paper_registry_root` —
`{workspace_root}/paper_registry`, where the workspace root is inferred
from `ARI_CHECKPOINT_DIR` and falls back to the current working
directory. It is **not** under `~/.ari/`: v0.5+ ARI keeps no global
per-user data directory.

`paper.pdf` is described as optional by the import endpoint but is a
hard precondition for running: the wizard worker aborts with
`"paper.pdf missing under …; cannot launch PaperBench"` before the
first stage.

## Import paths

### arXiv ID

Most-used path. Fill the wizard with `source_type=arxiv` and
`source=2404.14193`. Metadata auto-fetch has shipped — the import form's
**Fetch metadata** button (and `GET /api/paperbench/arxiv/<id>`) queries
the arXiv Atom API and returns `title`, `authors`, `year`,
`license: "arXiv non-exclusive"`, `summary`, `pdf_url` and `abs_url`.
Both new-style (`2404.14193`, `2404.14193v2` — the version suffix is
stripped) and legacy (`cs.LG/0102030`) ids are accepted, with an
optional `arxiv:` prefix.

The **PDF is still not fetched**: `pdf_url` comes back in the response
and nothing downloads it. Attach `paper.pdf` yourself via the upload
path below, or the run worker will abort.

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
appendices follow the same path under `ad_pdf_path` / `ae_pdf_path` —
but note the asymmetry: a failed `paper.pdf` copy aborts the import with
`{"error": "could not copy paper PDF: …"}`, while a failed AD/AE copy is
only logged and the import succeeds without them.

### Local path

`source_type=local`. For PDFs already on disk where you don't need ARI
to re-host them. Note that `source` is stored verbatim and never
interpreted as a path — only `pdf_path` copies a file into the registry.
A `local` entry without `pdf_path` therefore has no `paper.pdf` and
cannot be run; pass `pdf_path` pointing at the on-disk PDF if you want
the run to start.

## License classification

License strings are normalized (lower-cased, whitespace-stripped) and
classified into a `{permissive, modifiable, redistributable, usable,
note}` assessment:

| Status | Examples |
|---|---|
| **usable** (permissive AND redistributable AND not non-commercial) | MIT, Apache-2.0, BSD-2/3-Clause, CC0, CC BY, CC BY-SA, arXiv non-exclusive |
| permissive only (NOT redistributable) | CC BY-NC — flagged *"non-commercial ⚠ NOT usable — CC BY-NC restricts commercial reuse"* because ARI may be used commercially downstream |
| **NOT usable** | proprietary, IEEE author, ACM author, "all rights reserved", unknown strings, and an empty/absent license |

`modifiable` is narrower than `permissive`: `arXiv non-exclusive` is
redistributable but not modifiable.

The classification is heuristic and **advisory**. Final legal review
remains the user's responsibility. The GUI shows a green ✅ badge for
usable, ⚠ for not — both still let the registration go through.

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

A collision is reported in the body, not the status line: the response
is HTTP 200 carrying
`{"error": "paper_id already registered: <id>", "paper_id": …,
"existing": <the current manifest entry>}`. With `overwrite=true` the
manifest entry is **replaced wholesale**, not merged — fields you omit
are dropped. The paper directory is reused, so an existing `paper.pdf`
survives unless a new `pdf_path` overwrites it.

`paper_id` is itself sanitized to `[A-Za-z0-9._-]` — any other
character becomes `-`, and the result is truncated to 64 chars. An
empty id becomes a random 12-hex-char UUID4 slice.

## Deletion

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/delete
```

Idempotent (returns `{deleted: false, reason: "not found"}` when the
id is unknown). The module docstring still advertises
`DELETE /api/paperbench/papers/<paper_id>`; only the `POST …/delete`
form above is actually routed.

Deleting removes the manifest entry and `rmtree`s
`papers/<paper_id>/`, which takes any `runs/<job_id>/` sandboxes under
it with it. The durable job records in `{registry_root}/jobs/` are not
touched.

## Metadata patches

For fixing typos without losing the registry slot:

```bash
curl -X POST http://localhost:8765/api/paperbench/papers/<paper_id>/metadata \
  -H 'Content-Type: application/json' \
  -d '{"venue": "SC25", "year": 2025}'
```

`paper_id` is immutable — it is re-stamped from the URL after the
merge, so a `paper_id` in the body is ignored. Patching `license`
re-runs `_classify_license` and stores the lower-cased string plus a
fresh `license_assessment`.

## See also

- [PaperBench GUI guide](paperbench_gui.md)
- [API reference](../../reference/api_paperbench.md)
