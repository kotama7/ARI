---
sources:
  - path: ari-core/ari/schemas
    role: schema
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/checkpoint.py
    role: implementation
  - path: ari-core/ari/pipeline/verified_context.py
    role: implementation
  - path: ari-core/ari/pipeline/claim_gate
    role: implementation
last_verified: 2026-06-10
---

# File Formats Reference

Every ARI checkpoint is a self-describing directory.  This page
catalogues the JSON / YAML / Markdown files ARI reads and writes,
with the canonical key list and a pointer to the implementation that
produces them.

For schemas formally specified as JSON Schema, see
`ari-core/ari/schemas/`.

## `experiment.md`

Plain Markdown with a single load-bearing convention: a
`Metrics: <token>, <token>, ...` line that the deterministic helper
`parse_metric_from_experiment_md`
(`ari-core/ari/pipeline/experiment_md.py:31`) extracts as the fallback
`primary_metric`.  See `docs/guides/experiment_file.md` for the full guide.

After `generate_ideas` runs, the pipeline appends an idempotent block
delimited by:

```markdown
<!-- AUTO-APPENDED BY VirSci (idea.json) — DO NOT EDIT -->
...
<!-- END AUTO-APPENDED -->
```

Edit only the prose **above** the marker.

## `idea.json`

Output of `ari-skill-idea.generate_ideas`.  Lives at
`{checkpoint}/idea.json` and seeds the BFTS run's plan.

Top-level shape:

```json
{
  "ideas": [
    {
      "title": "...",
      "experiment_plan": "Markdown-formatted plan with §-tags",
      "primary_metric": "GFlops/s",
      "alternatives_considered": ["..."],
      "_pinned": false
    }
  ]
}
```

Children pin a parent's chosen idea by setting `"_pinned": true` on
the inherited entry; subsequent `generate_ideas` runs append new
ideas after it without overwriting.

## `evaluation_criteria.json`

Pipeline-side cache derived from `idea.json` + experiment.md.

```json
{
  "primary_metric": "GFlops/s",
  "higher_is_better": true,
  "metric_rationale": "..."
}
```

Source: `ari-core/ari/pipeline/orchestrator.py` (lines 98 ff. for the
loader, 170 ff. for the fallback path).

## `tree.json`

Live BFTS state, rewritten on every node transition.  Shape:

```json
{
  "schema_version": 1,
  "root_node_id": "...",
  "nodes": {
    "<node_id>": {
      "id": "...",
      "parent_id": "...",
      "depth": 2,
      "status": "running" | "completed" | "errored" | "pending",
      "label": "draft" | "improve" | "debug" | "ablation" | "validation" | "other",
      "metrics": {"GFlops/s": 312.4, ...},
      "score": 0.74,
      "children": ["<node_id>", ...]
    }
  }
}
```

`tree.json` is a *summary*; the per-node detail lives in
`nodes_tree.json`.

## `nodes_tree.json`

Full per-node detail consumed by `ari-skill-transform`,
`ari-skill-plot`, the viz dashboard, and the EAR pipeline.  Shape
matches `tree.json` but each node also carries:

| Key | Meaning |
|---|---|
| `eval_summary` | LLM judge's natural-language verdict |
| `metrics_with_metadata` | per-metric confidence + extractor code |
| `has_real_data` | `true` when the evaluator confirmed real measurements |
| `trace_log` | List of `{role, content}` records (LLM + tool messages) |
| `work_dir` | Per-node working directory (relative to checkpoint root) |
| `artifacts` | Files produced by the node, with sha256 |

## `node_report.json`

Per-node self-report written at `mark_success` / `mark_failed`.
Schema: `ari-core/ari/schemas/node_report.schema.json`.

Required keys: `schema_version` (constant `1`), `node_id`, `label`,
`depth`, `status`, `files_changed`, `metrics`, `artifacts`.

```json
{
  "schema_version": 1,
  "node_id": "...",
  "parent_id": "...",
  "ancestor_ids": ["..."],
  "label": "improve",
  "depth": 2,
  "status": "completed",
  "started_at": "2026-05-08T11:30:00Z",
  "completed_at": "2026-05-08T11:42:00Z",
  "files_changed": {
    "added":    [{"path": "src/main.cpp", "sha256": "..."}],
    "modified": [{"path": "Makefile",     "sha256": "..."}],
    "deleted":  [],
    "inherited_unchanged": []
  },
  "metrics": {"GFlops/s": 312.4},
  "artifacts": [{"path": "results.csv", "sha256": "..."}]
}
```

`generate_ear`, `nodes_to_science_data`, and `bfts.expand` consume
this file.

## `results.json`

Final aggregated results emitted at run completion.

```json
{
  "run_id": "...",
  "experiment_goal": "...",
  "primary_metric": "GFlops/s",
  "best_node": {"id": "...", "metrics": {...}, "score": 0.91},
  "nodes": {
    "<node_id>": {"metrics": {...}, "has_real_data": true, ...}
  }
}
```

Per-node `results*.json` files written by `ari-skill-coding.emit_results`
may also carry an optional `_provenance` key — an `{operand: source}`
map tagging where each reported value came from (`microbench` /
`benchmark` for a measured ceiling, `correctness` / `reference` for a
verification residual, `declared` / `constant` otherwise). The key is
omitted when empty. The claim-evidence hard gate reads it (via
`science_data.json` → `configurations[]._provenance`) to confirm a
measured ceiling or a correctness check was actually run.

## `science_data.json`

Paper-facing science surface built by
`ari-skill-transform.nodes_to_science_data` from the executed-node
evidence. Beyond `configurations[]` / `experiment_context` /
`summary_stats`, it carries the Research Contract substrate the
claim-evidence hard gate verifies:

| Key | Meaning |
|---|---|
| `claims` | Candidate claims deterministically derived from node evidence; each anchors to real `node_id` + `metric_path`. Prose is a templated seed the paper writer rewrites while preserving `% CLAIM:Cx:NCx` anchors. |
| `numeric_assertions` | Operand/formula records the hard gate re-derives and compares against the paper-reported number within tolerance. |
| `metric_contract` | The idea-owned metric-correctness contract grafted from `metric_contract.json` (see below), so the gate enforces the *declared* contract, not just the universal invariant registry. |

`_config_nodes`, `_anomalies`, and `_anomalous_metrics` are internal
(underscore-prefixed) annotations and are not part of the paper-facing
surface.

## `metric_contract.json`

The idea-owned metric-correctness contract emitted by
`make_metric_spec` (ari-skill-evaluator) and written to
`{checkpoint}/metric_contract.json` next to `idea.json` / `tree.json`,
so `nodes_to_science_data` can graft it onto `science_data.json`. All
expressions are restricted-AST (see
`ari-core/ari/pipeline/claim_gate/formula_eval.py`).

```json
{
  "key": "<metric the paper reports>",
  "formula": "geomean(gflops_byK / ceiling_byK)",
  "ceiling_select": "cache_bw if effective_bw > dram_peak_bw else dram_peak_bw",
  "invariants": ["value <= 1", "model_sec <= sec"],
  "correctness": {"expr": "max_abs_err < 1e-4", "requires": ["max_abs_err"]},
  "required_measured": ["dram_peak_bw", "cache_bw", "ceiling_byK"],
  "claims": [{"claim": "...", "required_evidence": ["thp_on_tput", "thp_off_tput"]}],
  "correctness_required": true,
  "ceiling_must_be_measured": true,
  "tolerance": {"absolute": 0.0, "relative": 0.02}
}
```

`correctness_required` / `ceiling_must_be_measured` are idea-owned flags
the agent cannot drop; they are satisfied by an EVIDENCE tag in
`results.json._provenance` (a measured-source ceiling, a
correctness-source residual), never by an agent-declared name. Source:
`ari-core/ari/pipeline/claim_gate/contract.py`.

The file is **mint-once**: it is immutable after the first claims-bearing
mint. A later `make_metric_spec` call returns the persisted contract
verbatim (the response carries `contract_frozen: true`) instead of
re-extracting — LLM naming is not referentially stable, so a mid-run
regeneration would mint a new evidence vocabulary and hide evidence already
emitted under the old names from the exact-match gate. Scaffold-only
contracts (no `claims`) do not freeze.

## `verified_context.json`

Artifact-grounded claims scoped to the best node's root→best lineage,
written by `ari-core/ari/pipeline/verified_context.py` so the
`write_paper` stage can ground its quantitative claims in verified,
artifact-backed (ideally reproduced) results. Written **only** when the
typed research-memory store has at least one grounded claim — an empty
store leaves no file and the paper stage behaves exactly as before.

```json
{
  "best_node_id": "...",
  "lineage": ["<root_id>", "...", "<best_id>"],
  "claims": [...],
  "limitations": [...],
  "usable_for_claims": [
    {"text": "...", "repro_status": "rerun_passed" | "unverified",
     "artifact_refs": [{"path": "...", "sha256": "..."}]}
  ]
}
```

## `paper_claim_links.json`

Deterministic reconciliation (no LLM) of the paper's `% CLAIM:Cx:NCx`
anchors against the `science_data.json` claim registry, produced by
`ari-skill-paper.link_paper_claims` after `write_paper` (draft) and
again after `paper_refine` (final).

| Key | Meaning |
|---|---|
| `paper_claim_links` | Anchor-keyed records (`claim_id` / `numeric_id` / `section` / `span_hash` / `line_range` / figures). The **anchor** is the stable key that survives refine/render; `span_hash` detects sentence changes. |
| `numeric_mentions` | Every numeric token in the paper, classified (`result_claim` / `experimental_setting` / `citation_year` / `figure_table_ref` / `ambiguous`) with section attribution and a `requires_assertion` flag. |
| `figure_refs` | Figure ids actually referenced in the paper (figure binding is recorded here; `science_data.json` is never mutated). |
| `unresolved_anchors` / `uncovered_numeric_candidates` | Diagnostics the hard gate consumes. |

## `evaluation/claim_evidence_hard_gate_{draft,final}.json`

The deterministic claim/evidence hard gate report written by
`ari-skill-evaluator.claim_evidence_hard_gate` (one per `phase`:
`draft`, then `final`). It verifies claim existence, numeric recompute,
numeric coverage, figure existence, and the declared `metric_contract` —
it checks transcription/derivation consistency between the paper and the
recorded results, **not** the truthfulness of the results themselves.

```json
{
  "gate": "claim_evidence_hard_gate",
  "phase": "final",
  "policy": "strict" | "warn",
  "status": "...",
  "should_block": true,
  "errors": [...],
  "warnings": [...],
  "metrics": {"total_claims": 0, "grounded_claims": 0, ...}
}
```

The MCP wrapper turns `should_block` (set only at `phase: final` under
strict policy, or on objective-falsehood findings) into a hard pipeline
failure so finalize is skipped. Source:
`ari-core/ari/pipeline/claim_gate/gate.py`.

## `evaluation/evidence_grounded_semantic_review.json`

Non-blocking, evidence-grounded semantic review written by
`ari-skill-evaluator.evidence_grounded_semantic_review`. It detects
over-claiming / interpretation issues grounded in the hard-gate evidence
and emits `suggested_revisions` for `paper_refine`. Never blocks the
pipeline; on any error it returns an empty (`status: "ok"`) review. The
post-refine pass writes the
`evidence_grounded_semantic_review_post_refine.json` variant alongside it.

## `lineage_decisions.jsonl` (v0.7.0)

Append-only log of stagnation-rule decisions.  One JSON record per
line:

```json
{"node_id": "...", "decision": "switch_to_idea", "rationale": "...", "ts": "..."}
{"node_id": "...", "decision": "fanout",        "rationale": "...", "ts": "..."}
```

Decisions: `continue` / `switch_to_idea` / `fanout` / `terminate`.
Source: `ari-core/ari/orchestrator/lineage_decision.py`.

## `settings.json`

Per-checkpoint settings used by the viz dashboard.

```json
{
  "model": "ollama/qwen3:32b",
  "provider": "ollama",
  "hpc": {"partition": "your_partition", "cpus": 64},
  "registries": [
    {"name": "default", "url": "http://127.0.0.1:8290", "token_env": "ARI_REGISTRY_TOKEN"}
  ]
}
```

API keys are **never** stored here — they live in `.env` files
(search order: checkpoint → ARI root → ari-core → home).

## `workflow.yaml`

Pipeline definition consumed by `ari-core/ari/pipeline/yaml_loader.py`.
Each stage names the skill + tool to call and any inputs / outputs.

```yaml
stages:
  - name: idea_generation
    skill: idea
    tool: generate_ideas
    inputs:
      - experiment.md
    outputs:
      - idea.json
  - name: bfts
    skill: orchestrator
    ...
```

Bundled defaults live in `ari-core/config/workflow.yaml` (the package config root returned by `package_config_root()`).

## `memory_store.jsonl` / `memory_backup.jsonl.gz`

Memory backend artefacts written under `ARI_CHECKPOINT_DIR`:

| File | Backend | Notes |
|---|---|---|
| `memory_store.jsonl` | `file` | Legacy v0.5 format, line-delimited JSON entries |
| `memory_backup.jsonl.gz` | `letta` | Portable snapshot (auto on stage boundary + exit) |
| `memory_access.jsonl` | any | Append-only telemetry of writes / reads |

Snapshot record shape:

```json
{
  "node_id": "...",
  "ancestor_ids": ["..."],
  "kind": "node_scope" | "react_trace",
  "text": "...",
  "metadata": {...},
  "ts": "..."
}
```

## EAR bundle (v0.7.0)

`{checkpoint}/ear/` is the candidate set; `{checkpoint}/ear_published/`
is the curated subset published to a backend.  The trust anchor is:

```
ear_published/
├── manifest.lock         # canonical JSON, files-only sha256 + bundle_sha256
├── publish_record.json   # backend, ref, sha256, visibility
└── ...                   # curated artefacts
```

`manifest.lock` schema: `ari-core/ari/schemas/publish.schema.json`.
The `bundle_sha256` must equal the `\codedigest{...}` macro baked
into the published paper.

## See also

- `docs/concepts/architecture.md` (Checkpoint Directory Layout) — narrative
  view of the same files.
- `ari-core/ari/schemas/` — formal JSON Schemas for `node_report` and
  the publish manifest.
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml parser.
- `docs/guides/experiment_file.md` — long-form `experiment.md` guide.
