# Viz API Schema Contract (requirement 06)

Task-control note from `06_viz_api_schema_contract.md`. Captured 2026-05-30 from
a 3-agent mapping workflow that read the **actual** backend producers (not the
assumed shapes) and the current frontend types.

## What was done (this PR) — all additive / corrective, behavior-preserving

Reconciled `frontend/src/types/index.ts` against the real backend output for the
four highest-traffic stable endpoints, documented the contract in
`docs/reference/rest_api.md`, and added a Python contract-guard test.

### Type changes (types/index.ts)
- **`Checkpoint`** += optional `best_metric?: number | null` (backend always
  emits it, hardcoded `null`) and `best_scientific_score?: number` (conditional).
- **`CostSummary`** (new) = the verified shape of `cost_summary.json`
  (`total_cost_usd`, `total_tokens`, `call_count`, `by_phase`, `by_model`).
- **`AppState.cost`** corrected `number` → optional `CostSummary`. The prior
  `number` type was **wrong**: the backend emits the parsed object, and
  `MonitorPage` already read it as `state?.cost as any` (`.total_cost_usd`,
  `.total_tokens`, `.call_count`). Correction is safe (consumed via `as any`).
- **`AppState`** += verified always-present fields omitted before (`exit_code?`,
  `running?`, `pid?`, `llm_model?`) and conditional fields (`phase_flags?`,
  `experiment_md_path?`, `workflow_yaml?`, `best_nodes?`, `all_metric_keys?`,
  `summary_stats?`, `typed_split_sources?`). Added optional so no consumer breaks.
- **`ReproReport`** (new) = `string | Record<string, unknown>`.
- **`CheckpointSummary`** += `id?`, `path?` (echoed back); `reproducibility_report`
  corrected `string|null` (required) → optional `ReproReport|null` (backend emits
  a parsed **dict**, or string for legacy runs; consumed as `any` via
  `summary.reproducibility_report || summary.repro`); `repro` made optional
  (vestigial — backend no longer emits it); += optional `ors_*` / `vlm_review`.

### Docs
- `docs/reference/rest_api.md`: added `checkpoint_api.py` + `api_settings.py` to
  the `sources` front-matter, bumped `last_verified` 2026-05-26 → 2026-05-30, and
  added a "Typed contracts (stable endpoints)" table.

### Guard test
- `ari-core/tests/test_api_schema_contract.py` (5 tests): pins the always-present
  keys of `/api/checkpoints`, `/api/checkpoint/<id>/summary`, `/api/settings` as a
  **subset** (extra/optional keys allowed → additive), and the `{**defaults,
  **saved}` merge pass-through. Fills the req-13 endpoint-shape gap.

## Why this is safe (no wire/behavior change)

- No backend response shape changed — only frontend types + docs + a test.
- All type additions are optional; the two corrections (`cost`,
  `reproducibility_report`) target fields already consumed via `as any` / an
  `any`-typed render param, so they cannot break a call site.
- Checks: `pytest ari-core/tests` 2223 passed / 16 skipped / 0 failed;
  `npm run typecheck` 0 non-test errors; `npm run build` ok; `npm test --run`
  4 passed / 2 failed (pre-existing brittle PaperBench tests).

## Deliberately NOT done (documented follow-up)

- The large `Settings` type ⇄ `/api/settings` divergence is only partially
  reconciled. The frontend `Settings` type carries fields the backend defaults
  omit (`slurm_partitions`, `ssh_*`, `model_idea/bfts/coding/eval/paper/review`,
  `language`, `llm_backend`) and the backend emits fields the type omits
  (`slurm_gpus`, `mcp_skills`, nested `ors`, `letta_deployment*`). These come
  from saved `settings.json` + the wizard, are consumed widely, and a full
  reconcile risks tightening. **Deferred** — a future, separately-justified pass
  (or the generated-types/OpenAPI follow-up below).
- Did NOT flip existing required `AppState`/`CheckpointSummary` fields to optional
  even though many are conditionally present, because they're read without
  null-guards across components (changing optionality could break strict-null
  call sites). Pinned the contract via the guard test instead.
- A future move to generated types / OpenAPI (req-06 §12) remains a separate,
  larger task.
