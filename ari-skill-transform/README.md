# ari-skill-transform

Tree-walk MCP skill: traverses an ARI BFTS run and uses an LLM to
extract methodology setup and key findings, plus owns the EAR
publication lifecycle (curate / publish / promote).

The skill sits between the BFTS output (`nodes_tree.json`) and the
paper pipeline (`ari-skill-paper`): it produces the structured
"science data" the paper writer consumes.

## MCP tools

| Tool | Purpose | LLM |
|---|---|:---:|
| `nodes_to_science_data` | Walk the BFTS tree, summarise methodology + findings into structured JSON | ✓ |
| `generate_ear` | Build `{checkpoint}/ear/` from BFTS artefacts (sources + chosen results) | ✗ (deterministic from blacklist + tree state) |
| `curate_ear` | Promote `{checkpoint}/ear/` into `{checkpoint}/ear_published/` plus `manifest.lock` (sha256 per file) | ✗ |
| `publish_ear` | Hand the curated bundle to a backend (`local-tarball` / `ari-registry` / `zenodo` / `gh`) | ✗ |
| `promote_ear` | Move a previously-published artefact between visibility tiers (`staged` → `unlisted` → `public`) | ✗ |

`nodes_to_science_data` is the only LLM-using tool; the EAR pipeline
is fully deterministic so a re-run produces a byte-identical bundle.

## Determinism

Mixed: `nodes_to_science_data` is a P2 exception (LLM call); the EAR
tools are P2-safe.  Same checkpoint state in, same manifest.lock and
sha256 digests out.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `LLM_MODEL` | LLM used by `nodes_to_science_data` | `gpt-4o-mini` |
| `ARI_LLM_MODEL` | Cross-skill fallback honoured when `LLM_MODEL` is unset | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |

## EAR pipeline (v0.7.0)

```
{checkpoint}/                    ← BFTS run output
    │
    ├── generate_ear   ─►   {checkpoint}/ear/                  (every artefact, no curation)
    │
    ├── curate_ear     ─►   {checkpoint}/ear_published/        (+ manifest.lock with sha256)
    │
    ├── publish_ear    ─►   backend.publish(bundle)            (local-tarball / ari-registry / zenodo / gh)
    │                       └─► writes {checkpoint}/publish_record.json
    │
    └── promote_ear    ─►   backend.promote(staged → unlisted/public)
```

`manifest.lock` is the trust anchor: the SHA-256 digest baked into
the published paper (`\codedigest{...}`) equals
`manifest.lock.bundle_sha256`, so the published artefact verifies
against the paper independently of which backend hosts it.

## Tree walk strategy

`nodes_to_science_data` consumes the tree in this priority order:

1. Per-node `node_report.json` (preferred — built by
   `ari-core/ari/orchestrator/node_report/`).
2. `trace_log` tool outputs from the agent loop (legacy fallback).
3. Source files collected from each node's `work_dir` (last-resort
   when reports are missing).

Truncation budgets keep the prompt within the LLM context window:
node-report blocks are capped at 65 KB total, individual tool
outputs at 2–3 KB per node.

## Development

```bash
pytest tests/ -q
```

Two test files cover the science-data extraction and the EAR curate
path.

## See also

- `docs/reference/skills.md` — high-level summary in the master skill index.
- `docs/concepts/architecture.md` (Publication Lifecycle, Plan / Venue contract) — where this skill fits.
- `ari-core/ari/publish/` — the backend implementations called by `publish_ear`.
- `ari-core/ari/orchestrator/node_report/` — the data this skill consumes.
