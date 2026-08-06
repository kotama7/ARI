# ari-skill-transform

Tree-walk MCP skill: converts an ARI BFTS run into digest-bound raw facts,
deterministic derivations, and a separately-bound model interpretation, and owns the EAR
publication lifecycle (curate / publish / promote).

The skill sits between the BFTS output (`nodes_tree.json`) and the
paper pipeline (`ari-skill-paper`): it produces the structured
"science data" the paper writer consumes.

## MCP tools

| Tool | Purpose | LLM |
|---|---|:---:|
| `nodes_to_science_data` | Build canonical `ScienceDataV1`; optionally annotate verified node reports | ✓ |
| `generate_ear` | Build `{checkpoint}/ear/` from BFTS artefacts (sources + chosen results) | ✗ (deterministic from blacklist + tree state) |
| `curate_ear` | Promote `{checkpoint}/ear/` into `{checkpoint}/ear_published/` plus `manifest.lock` (sha256 per file) | ✗ |
| `publish_ear` | Hand the curated bundle to a backend (`local-tarball` / `ari-registry` / `zenodo` / `gh`) | ✗ |
| `promote_ear` | Move a previously-published artefact between visibility tiers (`staged` → `unlisted` → `public`) | ✗ |

`nodes_to_science_data` is the only LLM-using tool. Its `raw`, `derived`, and
`interpretation` sections carry independent digests; interpretation is always
`claim_eligible=false`. The EAR pipeline is deterministic, and manifest v2
binds file roles, run/catalog locks, cassettes, ResultEnvelope artifacts, and
admission evidence.

## Determinism

Mixed: `nodes_to_science_data` is a P2 exception (LLM call); the EAR
tools are P2-safe.  Same checkpoint state in, same manifest.lock and
sha256 digests out.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARI_MODEL_TRANSFORM` | Transform-specific model; highest-priority environment override | (none) |
| `ARI_MODEL_TRANSFORM_REVISION` | Immutable model revision recorded in interpretation provenance | (none) |
| `ARI_LLM_MODEL` | Cross-skill fallback | (none) |
| `LLM_MODEL` | Legacy model fallback | `gpt-4o-mini` |
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

`nodes_to_science_data` accepts typed `results.json` plus identity-matching
`node_report.json`. Missing or tampered reports make interpretation unavailable;
the live path never substitutes `trace_log` or an arbitrary work-directory
scan. Pre-v1 artifacts are converted only with
`python scripts/migrate_science_data.py SOURCE OUTPUT --run-id RUN`.

The model prompt uses the same report-driven source selection as EAR code
publication and is capped before dispatch. Raw model bytes are stored as a
content-addressed artifact rather than inline trace text.

## Development

```bash
pytest tests/ -q
```

The test files cover the science-data extraction, the Research
Contract claim layer (`test_claims.py`), and the
`metric_contract`→`science_data`→hard-gate seam
(`test_metric_contract_seam.py`).

## See also

- `docs/reference/skills.md` — high-level summary in the master skill index.
- `docs/concepts/architecture.md` (Publication Lifecycle, Plan / Venue contract) — where this skill fits.
- `ari-core/ari/publish/` — the backend implementations called by `publish_ear`.
- `ari-core/ari/orchestrator/node_report/` — the data this skill consumes.
