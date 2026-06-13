# ari-skill-transform Requirements

## Overview

MCP server that converts the BFTS experiment tree into science-facing artifacts:
`science_data.json` (consumed by the paper writer and figure generator) and the
EAR publication lifecycle (curate / publish / promote). LLM-powered (P2
exception) for methodology/finding extraction; deterministic for the structured
contract layer.

## Research Contract claim layer (Story2Proposal Phase A)

`science_data.json` is the **Research Contract substrate** (not the EAR). On top
of the existing `configurations[]` / `experiment_context` / `summary_stats`,
`nodes_to_science_data` emits:

- `claims[]` — each `{id, text, section, status, supported_by, numeric_assertions, risk}`.
  - `status ∈ {draft, supported, unsupported, rejected}` (generated as `draft`).
  - `supported_by = {nodes:[real node_id…], results:[{node_id, metric_path}…], figures:[], artifacts:[]}`.
    `figures` starts **empty** and is late-bound by the paper post-processor
    (`paper_claim_links`); science_data.json is never mutated after the fact.
  - claim **text is a templated seed**; the paper writer finalizes the prose.
- `numeric_assertions[]` (top-level, flattened) — each nested assertion plus a
  `claim_id` back-reference, so the hard gate can iterate a flat list. Fields:
  `{id, text_span, metric, value, unit, formula, operands, aggregation, tolerance}`.

### Determinism contract

- Operands reference **real `(node_id, metric_path)`** resolvable from
  `tree.json` / `results.json`; identical inputs ⇒ identical operands
  (claim prose LLM variance is allowed, operands are not).
- Claims ground **only** on the deterministic part of science_data
  (`results.json` measurements/scores or node metrics), never on the
  LLM-generated `experiment_context` / `implementation_overview`.
- `aggregation` (statistic/trials) is **recorded only** in the MVP; true trial
  aggregation needs per-trial raw values (future scope).

### Formula registry (mirrored in `ari-core/ari/pipeline/claim_gate/numeric.py`)

`identity` (absolute), `relative_speedup`, `relative_gain`,
`relative_improvement_percent`, `relative_increase_percent`,
`relative_reduction_percent`, `absolute_difference`. The transform generator
emits an absolute (`identity`) claim for the best configuration and, when ≥2
configurations exist, a comparison claim (`relative_increase_percent` for
higher-is-better, `relative_reduction_percent` for lower-is-better).

### Environment-aware comparison (provenance, not prohibition)

Each operand is tagged with its execution `environment` (`executor` / `cpu_model`
/ `arch`, from `node_report`) — universal provenance, no cluster/domain knowledge
(P1). A comparison assertion records `cross_environment` when its operands span
different environments. Each science-facing `configuration` is likewise tagged
with its `environment`.

Comparison selection is driven by **injected research intent** (P4), NOT a
hardcoded rule — `comparison_scope` (param, or env `ARI_COMPARISON_SCOPE`):
- `any` (default): build the comparison from the global best/worst and tag
  `cross_environment` transparently. Correct for **cross-architecture studies**,
  where the cross-host comparison IS the contribution (it must not be suppressed).
- `same_environment`: restrict the comparison baseline to the best node's own
  environment; skip the comparison when no same-env peer exists. Correct for
  **single-architecture optimization studies**, so an accidental cross-host run
  (e.g. a validation node that fell back to the login host) is never turned into
  a spurious speedup claim.

The generator never hard-forbids cross-env comparisons (that would bake a
domain assumption and break cross-arch studies); it surfaces provenance and lets
intent + the hard gate decide. The gate's `environment_mismatch` severity follows
the same `comparison_scope` (warning under `any`, blocking under `same_environment`).

### Forward-declaration config handles (Story2Proposal (c))

Each science-facing `configuration` gets a stable `config_id` (`cfg1`, `cfg2`,
…), and `nodes_to_science_data` emits an internal `_config_nodes` map
(`cfgN -> {node_id, environment, metrics[]}`). This lets the **writer DECLARE**
the derivation of every numeric result it states (forward, not reverse), e.g.
`% CLAIM:Cx:NCx metric=GFlops/s formula=ratio_percent baseline=cfgN:ceiling
proposed=cfgN:measured`, which `link_paper_claims` parses into a verifiable
assertion (resolving `cfgN -> node_id`) and the hard gate **re-derives from the
executed data** — a wrong declaration surfaces as `numeric_mismatch`. The generic
formula registry gained `ratio_percent` (`proposed/baseline*100`, e.g.
measured/roofline-ceiling) for attainment-style claims. No reverse search, no
domain knowledge baked in.

### Schema

`src/schemas/science_data_claims.schema.json` (draft-07). New keys (operand
`environment`, assertion `cross_environment`, top-level `_config_nodes`) are
additive: existing consumers use `.get()` and are unaffected.

## Tech stack

Python 3.11+, FastMCP, litellm. Schema as JSON Schema + dataclasses (no Pydantic).

## Status

Phase A code + unit tests complete (`tests/test_claims.py`). Real compute-node
validation (master plan Step 13) is pending; see `PLAN_s2p_science_data_claims.md`.
