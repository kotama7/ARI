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
last_verified: 2026-08-06
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

## `full_log.json`

Per-node full ReAct record, written into each node's `work_dir` at the node's
completion. Like `node_report.json` it is in `PathManager.META_FILES`, so it is
**never inherited** into child work dirs — each node writes its own. Shape:
`{node_id, parent_id, depth, steps, tools[], messages[], trace_log[]}`.

- `tools` — the OpenAI function-calling schemas (name + description + parameters)
  the model was actually given, i.e. **how to use each tool**. The `AVAILABLE
  TOOLS` line in the system prompt lists names only; the usage schemas are passed
  out-of-band via the `tools=` API argument, so this field is where they are visible.
- `messages` — the **complete conversation**: the system prompt, the injected
  handoff (parent `summary` / `full_log` for the relevant arms), the task, and
  every user / assistant / tool turn (with tool-call names + arguments and
  tool-call results). This is the full **input prompt AND output**, not just the
  tool trace.
- `trace_log` — the concise tool-call trace (`→ tool(args)` / `← result`) for
  quick scanning; `steps` is its length.

`trace_log` is empty (`steps: 0`) for models that never call tools (e.g. the
0.5b floor), but `messages` always shows the full prompt that was sent.

## `node_report.json`

Per-node self-report written at `mark_success` / `mark_failed`.
Schema: `ari-core/ari/schemas/node_report.schema.json`.
Consumed by `generate_ear`, `nodes_to_science_data`, and `bfts.expand`.

**Required keys**: `schema_version` (constant `1`), `node_id`, `depth`, `status`,
`files_changed`, `metrics`, `artifacts`. All others are optional (emitted under the
conditions below).

### Core fields (always present)

| Field | Type | Meaning |
|---|---|---|
| `schema_version` | int(1) | Schema version |
| `node_id` | string | This node's id |
| `parent_id` | string \| null | Parent node id (`null` for the root) |
| `ancestor_ids` | string[] | root→parent chain |
| `depth` | int | Tree depth (root = 0) |
| `status` | string | `success` / `failed` / … |
| `started_at` / `completed_at` | string | ISO8601 timestamps |
| `files_changed` | object | `{added, modified, deleted, inherited_unchanged}`, each `{path, sha256}`. Diff vs parent (`added+modified+deleted==0` ⇒ *sterile* / no-op node) |
| `what_was_done` | string | **The agent's own natural-language self-report**. Filled only when the node concluded (empty for weak models that cannot use tools) |
| `metrics` | object | Evaluator-defined scalar measurements. The shared schema does not prescribe metric names or semantics. |
| `measurement_valid` | bool | Objective evaluator verdict. Kept separate from the agent-authored reflection. |
| `evaluation_cases` | object | Evaluator cases as `{case_name: {valid, measurements}}`. Case names and JSON-scalar measurement keys are harness-defined; the shared schema assigns no task-specific meaning. |
| `self_assessment` | object | `{headline, concerns}` from the agent's own LLM self-review (empty if none). |
| `next_steps_hints` | string[] | The agent's own self-reviewed next steps (LLM self-review). Sole source under deterministic scoring (no graded axes); falls back to the evaluator's mid-range axis rationales under a rubric/judge scorer. Empty when the agent volunteered none. |
| `build_command` / `run_command` | string | Operational scaffold (build / run commands) |
| `artifacts` | object[] | Produced artifacts `[{filename, role}]` |
| `evaluator_reason` | string | The deterministic evaluator's verdict reason |
| `trace_log_summary` | string | Summary of the execution trace |

### Exploration labels (always recorded)

`label` / `raw_label` / `original_direction` are **always recorded**.

An **`ARI_REPORT_MINIMAL=1`** flag used to strip them from the record; **it has been
removed**. The label is not decoration — it *drives* the search in three places:
(1) the system prompt's `NODE ROLE`, (2) the child's `Task:` line, and (3) node
**selection** (under the default `scientific_plus_diversity` frontier score,
`diversity_bonus` adds +0.05 for under-represented labels). Hiding it from the record
leaves the influence and deletes only the evidence — in the handoff study, a 4-arm run
that believed labels were "off" still had the ABLATION share skew 0/1/3/4 across arms,
and that was **undetectable from node_report**.

To remove a label's influence, turn the **feature** off rather than hiding the record:
**`ARI_BFTS_NO_LABEL=1`** stops all three sites (every node gets the same neutral
role/task; selection ignores labels). Labels are still recorded then — so a reader can
**verify** they were inert.

| Field | Meaning |
|---|---|
| `label` | BFTS exploration role: `draft` / `improve` / `debug` / `ablation` / `validation` / `other`. Inert (not used by scoring or selection). With `ARI_BFTS_DETERMINISTIC_LABEL=1` it is derived deterministically from the direction |
| `raw_label` | Kept only when `label==other` (the original LLM-proposed label); empty for the canonical five |
| `original_direction` | The direction text the parent's expand assigned to this child |

### Optional group 2: run-environment provenance

`executor` / `hostname` / `slurm_job_id` / `slurm_partition` / `slurm_nodelist` /
`cpu_info` / `mem_total_kb` / `compilers` record where this node actually ran.
They are **always present**, carrying empty values when the run_env skill captured
nothing (legacy runs, dry runs, evaluation-only). Emitting them unconditionally is
deliberate: an omitted key would make "nothing was captured" indistinguishable from
"this key predates the field", and a measurement whose machine is unknown must be
distinguishable from one whose machine was never asked for.

Machine identity is captured on purpose here. `node_report.json` is a run artifact
under `workspace/checkpoints/`, not repository content — the rule against writing
cluster/partition/host names into tracked source, tests and docs is unchanged.

`compilers` above is the **pre-module** view: it is captured in the ARI process,
which never loaded anything. `execution_env` is the record the executing shell
writes about *itself*, and is the only place that says which modules produced a
measurement — without it two module configurations, the very thing loading them
exists to compare, look identical in the report meant to compare them.

| Key | Meaning |
|---|---|
| `loaded_modules` | `$LOADEDMODULES` at the end of the command, split in order. Order matters: a later module can override an earlier one's paths, so it is neither sorted nor de-duplicated. `[]` means the command ran with nothing loaded, which is distinct from the key being absent (no shell tool ran at all) |
| `module_path` | `$MODULEPATH` as the command saw it |
| `path` | `$PATH` after module loading — the complete tool-resolution order, so any "which binary did this use" question stays answerable without ARI naming a single compiler |
| `recorded_at` | When the shell wrote the record |

It is written by an `EXIT` trap, so it survives a failing command (a failed
measurement's environment is as interesting as a successful one's) and the
command's exit status is preserved. `_exec_env.json` is in
`PathManager.META_FILES`: it describes one node's execution, so an inherited
copy would attribute the parent's modules to a child that never loaded them.

`partitions_used` widens this from *this node* to *the whole experiment*, because a
run spread across a heterogeneous cluster otherwise left no single record of where
it had executed and a cross-node metric comparison could not be checked against the
hardware behind it:

| Key | Meaning |
|---|---|
| `this_node` | The partition of this node's own allocation |
| `used` | Every distinct partition the run touched, scanned from each sibling node's `_run_env.json` — observed, not configured |
| `by_partition` | Per partition: `node_count`, and the distinct `nodelists` / `hostnames` seen on it |
| `catalog` | Per-partition probe from `heterogeneous_env.json` — what each partition *is*. Includes partitions that were probed but never ran a node, which is what makes "we could have used X and did not" answerable. Compacted to `arch` / `cpu_model` / `threads` / `mem_total_kb` / `gpus` / `compilers` / `cache_measured` |
| `catalog_path` | Path to the full catalog. The raw `module avail` / `lscpu` dumps run to ~30 KB per partition and already exist once at the checkpoint root, so they are pointed at rather than copied into every node's report |

The sibling scan only runs when the node's `work_dir` really is
`experiments/{run_id}/{node_id}`; otherwise `used` stays empty rather than
counting an unrelated directory's files as part of this experiment.

```json
{
  "schema_version": 1,
  "node_id": "node_a1b2c3d4",
  "parent_id": "node_...root",
  "ancestor_ids": ["node_...root"],
  "depth": 1,
  "status": "success",
  "started_at": "2026-07-10T10:34:32Z",
  "completed_at": "2026-07-10T10:35:24Z",
  "files_changed": {"added": [], "modified": [{"path": "candidate_gemm.c", "sha256": "..."}], "deleted": [], "inherited_unchanged": []},
  "what_was_done": "Parallelized the outer loop with OpenMP and reordered to ikj for cache locality.",
  "metrics": {"_scientific_score": 1.34},
  "measurement_valid": true,
  "evaluation_cases": {
    "case_a": {
      "valid": true,
      "measurements": {"throughput": 123.4, "error": 1e-12}
    }
  },
  "self_assessment": {"headline": "Vectorized the inner loop; measured ~1.2x.", "concerns": ["only 3 problem shapes tested"]},
  "next_steps_hints": [],
  "build_command": "", "run_command": "CC ?= cc",
  "artifacts": [{"filename": "result", "role": "unknown"}],
  "evaluator_reason": "ok", "trace_log_summary": ""
}
```
(The example predates the removal of the `ARI_REPORT_MINIMAL` suppression, so it shows
the label group absent. A current report ALWAYS carries `label` / `raw_label` /
`original_direction`. Machine info is still absent here because the run_env skill was
unused — that field is populate-as-needed, not suppressed.)

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
The best node is `select_best_node`'s winner: nodes logically erased by
RQGM selective erasure (`metrics._valid_for_frontier: false`) are
excluded, and if every candidate is erased there is no winner and no
file. A previously written `verified_context.json` whose `best_node_id`
no longer matches the fresh winner is deleted rather than left to ground
the paper on a since-erased lineage.

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

## `prompt_trace.jsonl` / `prompt_versions.json`

Prompt provenance: which *template* — and, where a rendered string was
available at the call site, which *rendered prompt* — produced each
managed-prompt LLM call. `prompt_trace.jsonl` is the append-only per-call
trace; `prompt_versions.json` is its run-level rollup. Both are written at the
checkpoint root and both are in `PathManager.META_FILES`, so neither is ever
copied into a node work dir; `prompt_trace.jsonl` is additionally classified in
`_TRACE_FILES`, the set of files that live under `runs/<run_id>/traces/` in the
bucketed run-directory layout the path resolver also understands. Source:
`ari-core/ari/prompts/_provenance.py`; the rollup write funnels
through `ari.checkpoint.save_prompt_versions_json`.

One JSON object per trace line. `prompt_name` and `template_hash` are the
mandatory, always-computable fields; every other field carries a default, so
the record shape can grow without breaking readers:

```json
{"timestamp": "2026-07-10T10:34:32Z", "prompt_name": "pipeline/keyword_librarian",
 "template_hash": "9f2c01ab34de", "rendered_prompt_hash": "34de9f2c01ab",
 "prompt_version": null, "prompt_registry_version": null,
 "model": "...", "node_id": "", "phase": "context_builder", "source": "core"}
```

Hashes are `sha256(text)[:12]` — the same scheme
`FilesystemPromptLoader.load_versioned` uses, so a template body hashes
identically here, there and across machines. `timestamp` is metadata and never
enters a hash. `rendered_prompt_hash` is `null` unless the call site passed the
rendered text; several sites only load a template and never render a final
string there, so `null` means "not captured", not "empty prompt".

`prompt_version` / `prompt_registry_version` are **observed as almost always
`null`**, and that is a frozen property of the call sites rather than a
statement about the prompt. Exactly one writer fills them: the RQGM
PromptRegistry's stamp path (`ari-core/ari/rqgm/registry.py`), which sets
`prompt_version` to the *registry prompt id* and `prompt_registry_version` to
the registry version. Everywhere else — the agent loop, the LLM evaluator, the
context builder, the viz wizard tools, and every RQGM governance /
prompt-evolution / proposal call — both stay `null`. Read `null` as
"unstamped", never as "unversioned prompt". `source` is likewise always
`"core"`: `record_prompt_use` hard-codes it and takes no parameter for it, so
the `"skill"` value the field reserves is emitted by nothing that ships.

`prompt_versions.json` is `{prompt_name: {template_hash, prompt_version,
call_count}}` in first-seen order, with `template_hash` and `prompt_version`
taken from the *first* record seen for that name — a prompt whose template
changed mid-run shows only its first hash there, and the JSONL remains the
truth. It is rebuilt from the trace by `build_prompt_versions_rollup` each time
the BFTS loop flushes the checkpoint (a throttled write; terminal flushes are
forced), so it is derived, never authoritative. That flush is its only writer,
so a phase that records prompt uses without entering the BFTS loop leaves a
trace with no rollup.

Both writers are deliberately best-effort, and the artifacts must be read that
way. `record_prompt_use` no-ops when no checkpoint dir resolves (unit tests,
pre-launch), appends under a module lock, and swallows **every** exception so
provenance logging can never break the LLM call it is recording; the rollup
write is wrapped the same way. Absence of either file means "no provenance
recorded" — never an error, and never proof that a call did not happen.

## RQGM epoch-governance files (opt-in `ari_rqgm` mode)

Written only when `ari.mode: ari_rqgm` **and** `rqgm.enabled: true` agree
(see [Execution Modes](../guides/execution_modes.md)). Absent on every default `simple_bfts`
checkpoint; every reader treats absence as "RQGM never ran". Source:
`ari-core/ari/rqgm/store.py`; JSON Schemas:
`ari-core/ari/schemas/{epoch_state,rqgm_registry,rqgm_transition_event,rqgm_defs}.schema.json`.

### `rqgm_transitions.jsonl`

**Source of truth** for epoch/registry governance state. Append-only,
hash-chained JSONL; one self-contained event per line:

```json
{"schema_version": 2, "event_id": "evt_000042", "event_type": "prompt_status_change",
 "transaction_id": "transition_003_to_004",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active", "transition_id": "transition_003_to_004"},
 "event_hash": "baf0...64-hex-sha256...", "prev_event_hash": "91ac...64-hex-sha256...",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

For schema v2, `event_hash` is full SHA-256 over the schema version, event
identifier, event type, transaction identifier, canonical payload, and
predecessor digest. Timestamps are metadata outside that commitment. Legacy
schema-v1 payload-only 12-hex events remain readable. Event types:
`epoch_transaction_prepare`, `component_registered`, `prompt_registered`,
`component_status_change`, `prompt_status_change`, `epoch_close`,
`epoch_open`, `epoch_transaction_commit`, `emergency_quarantine`. Registry
status changes, including T16 emergency quarantine, are accepted **only**
through a prepare/commit boundary transaction; on load, events after a
prepare without a matching commit are ignored (crash recovery).

Status-change payloads are supplied by the RegistryTransitionEngine
(RQGM Task 09, `ari-core/ari/rqgm/transition_engine.py` — the sole registry
status writer): each carries `transition_id`, a fixed T1-T21 `rule_id`
(`ari/rqgm/transition_rules.py`; the topology is frozen code, only
`rqgm.transition.*` numeric thresholds are configurable), `from_status` /
`to_status`, `evidence_refs`, `produced_by: registry_transition_engine`
(kernel CK-REG-004), and the `inputs_sha256` content hash of the frozen
boundary inputs (GovernanceReport + candidate evaluations + registry
hashes), so every committed change replays deterministically.

### `rqgm_audit.jsonl`

The RQGM **ImmutableAuditLog**: same append-only hash-chained line
envelope with an independent per-file chain. The governance record
payloads written into it are owned by the GovernanceOrchestrator (RQGM
Task 05); chain integrity verification is the ConstitutionalKernel's
(Task 04). Kernel verdicts are appended as `kernel_report` entries:
`{"context": ..., "constitution_hash": ..., "blocking": ...,
"violations": [{"code": "CK-…", "check": ..., "severity": ...,
"subject_ref": ..., "rule_id": ..., "detail": ...}]}` — every verdict is
replayable.

That replayability is a contract, not a habit. `make_report`
(`ari-core/ari/rqgm/kernel_types.py`) sorts violations by
`(code, subject_ref, detail)` at construction, so identical inputs
serialize to an identical `kernel_report` line; the property is pinned per
violation code in `ari-core/tests/test_rqgm_kernel.py`, which drives each
fixture twice on two separate kernel instances and compares the canonical
JSON. No check reads a clock: no kernel module imports `time` or
`datetime`, and the envelope's `created_at` is checked for **presence**
only (`kernel_rules.ENVELOPE_FIELDS`) — its value never enters a
comparison, a `detail` string, or a hash. Severity is never chosen by the
caller either; it resolves through the frozen `kernel_rules.SEVERITY` map,
so a verdict's severity is a function of its code alone. Numeric slack is
one knob: float comparisons go through `rqgm.kernel.float_tolerance`
(default `1e-9`, see [Configuration](configuration.md)). And "the kernel
is not an LLM judge" is enforced rather than asserted — a test greps every
`ari/rqgm/kernel*.py` plus `transition_rules.py` for `litellm`, `openai`,
`anthropic`, `requests`, `httpx`, `aiohttp`, and `socket` and fails if any
appears as an import; it also asserts the covered file set exactly, so a
new `kernel_*.py` cannot join the kernel without joining the guard.

At each epoch boundary the GovernanceOrchestrator's `audit_epoch` appends
its records here (all carrying the common `rqgm_record_base` envelope):
`evidence_bundle` (EvidenceClerk-only author), `impeachment_motion`
(Auditor-only author; same-role accusations are refused constructively and
rejected by the kernel), `governance_defense`, `impeachment_outcome`, and
the final `governance_report` (schema:
`ari-core/ari/schemas/governance_report.schema.json`;
`recommendations[].action` is the closed set `promote_candidate | promote |
demote | warn | quarantine | retire | no_action` consumed by Task 09). The
latest report for an epoch is the LAST `governance_report` line with that
`epoch_id` (a re-run after a crashed audit appends fresh record ids; prior
partial records remain as history). No governance snapshot file exists;
the JSONL is the truth.

`audit_epoch` is **read-only** with respect to the component and prompt
registries, the frontier, `tree.json` and node state. It reaches the
registries only through their read accessors (`active_set` / `get`), and the
nine-step pipeline *returns* records rather than persisting them — the facade
appends them afterwards. It applies no recommendation either: acting on a
`governance_report` is the RegistryTransitionEngine's job alone (Task 09), so
a report on its own changes no status. Its write set is closed:

- `rqgm_audit.jsonl` — always: the governance records above plus the final
  `governance_report`.
- `prompt_trace.jsonl` — the ordinary provenance records of the shared
  prompt-render path, covering the governance LLM calls only. Those calls
  reach `prompt_versions.json` only indirectly, when the BFTS checkpoint
  flush next rebuilds that rollup from the trace (see
  `prompt_trace.jsonl` / `prompt_versions.json` above); `audit_epoch` never
  writes the rollup itself. A deterministic audit (no LLM seam wired) renders
  no governance prompt and appends nothing here.
- `rqgm_adversarial_cases.jsonl` plus the derived
  `rqgm/adversarial_replay_pool.json` — the step-7 replay-pool update, only
  when a pool is passed. Admitted and upheld cases are **appended** to the
  JSONL truth and the snapshot is then rewritten from in-memory state, which
  makes it a projection rather than an in-place edit of history: bounded
  eviction only flips a case's `status` to `evicted`, and the JSONL keeps
  every case line ever admitted.
- `rqgm_governance_cache.jsonl` — the candidate-evaluation write-back, only
  when a Task 12 governance cache is wired (see `rqgm_governance_cache.jsonl`
  below).

`rqgm_audit.jsonl` is registered both in `PathManager.META_FILES` — so no
inheritance or checkpoint-copy path carries it into a node work dir — and in
the node-report `files_changed` blocklist
(`ari-core/ari/orchestrator/node_report/builder.py`), so a governance write
never surfaces as a node-produced file change. Two regression tests in
`ari-core/tests/test_rqgm_governance.py` hold the line: an `audit_epoch` with
no LLM and no replay pool leaves the registered audit log as the *only* file
in the checkpoint directory, and a default `simple_bfts` run writes no
`rqgm*` file and no `constitution.yaml` at all.

The RegistryTransitionEngine (RQGM Task 09) additionally audits every
boundary resolution here as an `epoch_transition` record (schema:
`ari-core/ari/schemas/epoch_transition.schema.json`; `status` one of
`pending | committed | aborted | rejected | failed` — an aborted/kernel-
blocked transition is logged but applies **no** registry change), plus a
`retirement_event` record on each committed retirement (T17, and the
role-scoped T20 `utility_policy` supersession) and a
`clean_room_generation_request` on each committed T17 retirement
(consumed by Tasks 08/10).

The FrontierRepairEngine (RQGM Task 10,
`ari-core/ari/rqgm/frontier_repair.py`) appends three further line types
on every committed transition with retirements:

- `selective_erasure` — one `SelectiveErasureEvent` (schema:
  `ari-core/ari/schemas/selective_erasure_event.schema.json`):
  kernel-authored (`prompt_hash` null, `component_id`
  `frontier_repair_engine`), listing the retired hashes/components, the
  direct + transitive stale record ids, and the
  invalidated/recompute/abandoned node ids plus
  `policy_rescored_node_ids` when a utility-policy retirement re-weights
  stored raw axis scores. Erasure is **logical-only**
  (invariant 13): the listed records are flagged in
  `rqgm_erasure_state.json`, never rewritten or deleted.
- `frontier_rebuild` — one `FrontierRebuildEvent` (schema:
  `ari-core/ari/schemas/frontier_rebuild_event.schema.json`):
  `frontier_before/after`, removed/reinstated node ids (Rule-A
  reinstatement of a parent whose winning child was erased), recomputed
  node ids, and `kernel_validation`. `status` for both events is
  `applied | conservative | halted_expansion` (the §5.6 fail-closed
  degradation ladder).
- `utility_record` — one **recomputed** UtilityRecord per
  reviewer/adversary/defender/judge erasure that left surviving scored
  evidence (schema: `ari-core/ari/schemas/rqgm_utility_record.schema.json`
  plus `supersedes: <stale record_id>` and `recomputed_in_epoch`):
  recomputed from surviving inputs under the ORIGINAL epoch's frozen
  weights, never re-scaled — the superseded record stays on disk, stale.
  Utility-policy retirement is a separate path: the same repair event
  re-composes each stamped node's stored `_axis_scores` under
  `new_utility_policy` and lists it in `policy_rescored_node_ids`.
  A node whose raw axes are unavailable is invalidated fail-closed.

### `constitution.yaml`

Human-readable statement of the constitutional layer, copied ONCE from the
bundled `ari-core/config/constitution.yaml` at `ari run` start (never
clobbered, `ari_rqgm` only; absent on `simple_bfts` checkpoints). The
authoritative rules are frozen code (`ari/rqgm/kernel_rules.py` +
`ari/rqgm/transition_rules.py`), pinned by `constitution_hash` —
`sha256(canonical_json(<all rule tables>))[:12]` — which is also recorded
additively as an optional `constitution_hash` key in `meta.json`.

So the checkpoint copy is a **provenance marker, not a control surface**:
editing it changes no behaviour, because no ARI code reads it back —
`ari.rqgm.state.copy_constitution_if_missing` is the only code that touches the
path (it is called from `ari/cli/run.py` under the mode gate; see
[Internal Boundaries](internal_boundaries.md), "RQGM mode boundary
(`ari.rqgm`)"). That is
the point rather than an oversight: the checkpoint directory is flat and any
skill can write into it, so a rules file living there would be an
evolution/tampering channel, and the rule tables stay in code instead. The copy
is registered in `PathManager.META_FILES`, so it never reaches a node work dir.
Copying is best-effort in both directions — a packaging that ships no bundled
`constitution.yaml` copies nothing and reports nothing — so an absent file is
not on its own evidence that the run was `simple_bfts`.

### `epoch_state.json`

Derived rewrite-whole snapshot of the currently open (or last closed)
epoch: frozen active component set, active prompt hashes, utility policy,
`registry_version`, `policy_settings` / `policy_fingerprint`, and
`execution_identity` / `execution_fingerprint`. The composite
`epoch_fingerprint` binds both declared identities (`created_at` is metadata,
excluded from all fingerprints). Missing external revision pins are stored
as `unresolved`, never assumed stable. Disposable —
validated against event-log replay on load and rebuilt on mismatch.

### `rqgm_registry.json`

Derived rewrite-whole snapshot of ComponentRegistry + PromptRegistry in
one file (`registry_version`, `as_of_event_hash`, `components[]`,
`prompts[]`). Prompt entries reference their text by source
(`committed_template` loader key; `checkpoint_file`, the write-once evolved
body under `rqgm_prompts/`; or `policy`, a Task-14 governed utility-policy body
referenced by `path`) and carry both `prompt_hash` (`sha256[:12]`) and the full
`prompt_sha256`. Status lifecycle (shared by prompts and components):
`candidate → validated → shadow → probationary_active → active`,
`active → warning | probation | quarantine`,
`quarantine → retired → banned` — mutation only via transition events.

### `proposals/` (RQGM Task 03)

Checkpoint-scoped proposal store — "store everything; hand BFTS only the
summary". Created only by the `ari_rqgm` ProposalRouter or the explicitly
opt-in `proposal_router.record_only` dual-write; a default `simple_bfts`
run creates **no** `proposals/` directory. Source:
`ari-core/ari/rqgm/proposals/store.py`; JSON Schemas:
`ari-core/ari/schemas/{proposal_record,proposal_summary_view}.schema.json`.

```
proposals/
  proposal_records.jsonl       # append-only truth (one ProposalRecord per line)
  proposal_index.json          # derived rollup: record_id → status/generator/epoch
  archive/<record_id>/…        # raw outputs, transcripts refs, generator configs
```

Each `proposal_records.jsonl` line carries the mandatory RQGM record
fields (`record_id` `prop_%06d`, `epoch_id` — `null` in record-only mode,
`component_id`, `role: "generator"`, `prompt_hash` — the standard
`sha256[:12]`, `null` for legacy imports, `created_at`, `source_refs`,
`status: candidate|selected|expanded|superseded`) plus `generator`
(`cheap|mutation|attack_driven|prior_art|virsci|legacy_idea_json`), the
inline bounded `summary` (ProposalSummaryView; the ONLY shape BFTS sees),
`archive_refs` (checkpoint-relative references, never copies), and the
logical-only `stale` / `valid_for_frontier` flags (read-time semantics
owned by RQGM Task 10; never rewritten in stored JSONL). Records are
deduplicated by a content key (generator + source_refs + summary), so
retried MCP calls never duplicate lines. In `ari_rqgm`, `idea.json` is
the store's maintained compatibility projection of these records
(pinned ideas stay in front; `_pinned` / `_inherited_from` /
`_root_choice` markers preserved verbatim;
`ideas[i]._proposal_record_id` links back to the record).

### `rqgm_adversarial_cases.jsonl` (RQGM Task 06)

Append-only truth of the adversarial evolution loop (one JSON per line,
lock-guarded, never raises — the `lineage_decisions.jsonl` posture).
Created only when the `ari_rqgm` adversarial round runs; absent on every
`simple_bfts` checkpoint. Source: `ari-core/ari/rqgm/adversarial/pool.py`;
JSON Schemas: `ari-core/ari/schemas/{rqgm_attack_records,
rqgm_utility_record,rqgm_replay_pool}.schema.json`. Line types, in the
per-node §5.3 order raw → defense → judgment → validated → utility:

- `rqgm_adversarial_round` — per-node idempotency marker (`node_id`,
  `epoch_id`): the round runs at most once per node, resume-safe.
- `raw_attack` — one adversary attack (`atk_%06d`, role `adversary`).
  Targets a **closed artifact set** (`proposal | experiment_plan |
  node_report | metric_result | paper_claim | novelty_claim |
  citation_claim | reproducibility_claim`) — never a component — and
  must cite ≥ 1 `attack_evidence_refs`. Audit material ONLY: raw attacks
  never touch any score (invariant 8).
- `defender_response` — `rebut | concede | propose_fix` per attack
  (`def_%06d`, role `defender`).
- `judgment_record` — the ArtifactJudge verdict
  `valid | partially_valid | invalid` with judge-assigned severity
  (`jdg_%06d`, role `judge`); always written, even for `invalid`.
- `validated_attack` — exists ONLY for `valid | partially_valid`
  verdicts (`vat_%06d`; adjudication required, invariant 9).
- `utility_record` — the §5.4 penalty channel audit record (`utl_%06d`,
  role `utility_policy`): `base_score` / `penalty` / `final_score`, the
  epoch-frozen policy weights embedded by value, and
  `input_refs.validated_attack_ids` (non-empty whenever `penalty > 0`).
- `adversarial_replay_case` — one AdversarialReplayCase admitted at an
  epoch boundary (`adv_case_%05d`): `replay_view` (full materials;
  denied to role `clean_room_generator`) + `abstract_view`
  (contamination-safe FailureSummary — no raw attack/defense text).

Penalized nodes additionally carry the additive `Node.metrics` keys
`_pre_penalty_score` and `_validated_attack_penalty`;
`_scientific_score` is rewritten (sterile-gate precedent), never shadowed.

### `rqgm/adversarial_replay_pool.json` (RQGM Task 06)

Derived byte-fixed snapshot of the AdversarialReplayPool
(`schema_version`, `case_seq`, `cases[]`), rewritten at epoch boundaries
by the GovernanceOrchestrator's step 7; `rqgm_adversarial_cases.jsonl`
stays the source of truth and fills any crash tail on load. Eviction is
logical-only (`status: "evicted"`; nothing removed from the JSONL).

### `prompt_evolution.jsonl` (RQGM Task 07)

Append-only truth of prompt evolution (fail-open writer modeled on
`prompt_trace.jsonl`). Created only when the `ari_rqgm` prompt-evolution
pipeline runs; absent on every `simple_bfts` checkpoint. Source:
`ari-core/ari/rqgm/prompt_evolution.py`; JSON Schema:
`ari-core/ari/schemas/rqgm_prompt_evolution.schema.json`. Line types:

- `prompt_candidate` — one PromptMutator/clean-room output (`pcand_%05d`)
  carrying the full embedded PromptSpec
  (`ari-core/ari/schemas/rqgm_prompt_spec.schema.json`); always born
  `status: "candidate"` — no instant activation.
- `prompt_candidate_validation` — one lifecycle-stage execution
  (`pval_%05d`; stages `static_validation → constitutional_validation →
  schema_dry_run → replay_evaluation → anchor_evaluation → shadow`,
  monotonic — the record chain makes stage skipping detectable).
- `comparison_observation` — one shadow side-by-side sample
  (`cobs_%05d`): input/output **hashes** and divergence summary only —
  shadow output text never reaches this file, node metrics, or the
  frontier (observation-only).

Adoption into `probationary_active`/`active` happens ONLY through the
RegistryTransitionEngine's epoch-boundary transaction in
`rqgm_transitions.jsonl` (Task 09), never through this file.

### `prompt_specs.json` (RQGM Task 07)

Derived rollup of the prompt-evolution registry view
(`schema_version`, `specs{candidate_id → prompt_spec, stages_passed,
rejected}`), rewritten best-effort at epoch boundaries and run end
(`prompt_versions.json` pattern); `prompt_evolution.jsonl` stays the
source of truth.

### `rqgm_prompts/` (RQGM Task 07)

Checkpoint-scoped evolved template bodies, one write-once
`<prompt_id>.md` per evolved prompt (differing rewrites are refused —
active prompt text is never mutated in place; a change mints a new
`prompt_id`). Bytes are pinned by `prompt_hash = sha256(text)[:12]` — the
exact `FilesystemPromptLoader.load_versioned` scheme. Gate 10 carve-out:
the report appendix covers exactly the committed
`ari-core/ari/prompts/**` templates; runtime-evolved prompts are covered
by this directory plus the `prompt_trace.jsonl` provenance fields
(`prompt_version`, `prompt_registry_version`) instead. Absence of
`rqgm_prompts/` == fully-committed prompt trajectory (the
`bfts_web_provenance.json` P5 pattern applied to prompts).

### `rqgm_cleanroom.jsonl` (RQGM Task 08)

Append-only truth of clean-room regeneration (fail-open writer modeled
on `prompt_evolution.jsonl`). Created only when a retirement produces
`EpochTransition.clean_room_requests`; absent on every `simple_bfts`
checkpoint. Source: `ari-core/ari/rqgm/clean_room.py`; JSON Schemas:
`ari-core/ari/schemas/clean_room_request.schema.json` (requests) and
`ari-core/ari/schemas/clean_room_bundle.schema.json` (the closed input
bundle). Event kinds (`event` field):

- `request_created` — one full `CleanRoomGenerationRequest` (the five
  forbidden input flags are const-false; requests replay from this file
  on resume — pending ones retry at the next epoch boundary under the
  `rqgm.prompt_evolution.max_clean_room_generations_per_epoch` budget).
- `bundle_assembled` — `bundle_id` + `bundle_hash` (hash12 over the
  canonical bundle payload; the bundle is the ENTIRE generator context
  besides the committed `rqgm/clean_room_generator.md` meta-prompt).
- `generation_attempted` — one-shot completion marker with
  `rendered_prompt_hash` (audit: exactly meta-prompt + canonical bundle
  JSON reached the LLM).
- `clean_room_violation` / `candidate_rejected_contaminated` — kernel
  CK-CLN-001/CK-CLN-002 screen findings; contaminated candidates never
  enter the Task 07 lifecycle (blocking at admission, fail-open for the
  run).
- `candidate_registered` — handoff into `prompt_evolution.jsonl` at
  `status: "candidate"` (never instantly active).
- `request_status` — request status transitions
  (`pending|generating|generated|rejected_contaminated|failed|superseded`).
- `fallback_to_baseline` — the no-vacancy rule: a role with no active
  prompt and no admissible candidate reverts to its committed baseline
  template.

### `rqgm_erasure_state.json` (RQGM Task 10)

Derived rewrite-whole snapshot of selective-erasure staleness, rebuildable
by folding every `selective_erasure` / `frontier_rebuild` event in
`rqgm_audit.jsonl` (the `prompt_trace` → `prompt_versions` "JSONL is
truth, snapshot is derived" precedent). Created only when a repair runs;
absent on every `simple_bfts` checkpoint and on runs without retirements.
Source: `ari-core/ari/rqgm/erasure_state.py` (write funneled through
`ari.checkpoint.save_erasure_state_json`; `indent=2, ensure_ascii=False`);
JSON Schema: `ari-core/ari/schemas/erasure_state.schema.json`. Registered
in `PathManager.META_FILES` and the node_report `files_changed` blocklist.

```json
{
  "schema_version": 1,
  "retired_prompt_hashes": {"a1b2c3d4e5f6": {"retirement_event_id": "retire_00042",
                                              "retired_in_epoch": "epoch_004"}},
  "stale_record_ids": {"review_00311": "erase_00007"},
  "invalid_frontier_node_ids": {"node_031": "erase_00007"},
  "last_erasure_event_id": "erase_00007",
  "last_rebuild_event_id": "rebuild_00007"
}
```

Staleness is **read-time**: a record is stale iff its `record_id` is in
`stale_record_ids` — stored JSONL lines are never rewritten (invariant
13), and absence of this file means "nothing stale, all valid" (pre-Task-10
checkpoints stay valid). Erased/invalidated nodes additionally carry the
additive `Node.metrics` sentinels `_stale`, `_valid_for_frontier`,
`_stale_reason` (`generator_retired | utility_invalidated |
trace_depth_exceeded` — diagnostic only), and `_erasure_event_id`,
persisted through `tree.json`; they keep an erased node excluded even
after a mode switch back to `simple_bfts` (contamination does not become
clean by switching modes).

This rollup is also the surface ARI publishes to **other packages**, so two
consumer-side rules apply to it. First, `invalid_frontier_node_ids` is a pinned
cross-package contract — ari-core writes it, the memory skill reads it, and
`ari-skill-memory/tests/test_erasure_annotation.py` greps the ari-core writer
so a rename on either side fails rather than silently disabling erasure
awareness. Second, that cross-package reader
(`ari-skill-memory/src/ari_skill_memory/erasure.py`) is forward-compatible by
**degrading**: it pins `SUPPORTED_SCHEMA_VERSION = 1`, and a file whose
`schema_version` is not an integer it understands — above its supported
version, or a string / float / bool — is read as "nothing is stale" rather than
risking a wrong erasure label, the same verdict it returns for an absent,
unreadable or malformed file. A missing `schema_version` key is read as the
supported version.

Note the asymmetry, which is a property of the readers rather than of the
format: ari-core's own `view_from_payload`
(`ari-core/ari/rqgm/erasure_state.py`) does **not** inspect `schema_version` at
all — it is the writer's absence-tolerant twin — and the JSON Schema declares
`schema_version` as `const: 1`. Only the cross-package reader implements the
degrade ladder.

### `rqgm_governance_cache.jsonl` (RQGM Task 12)

The governance result cache: append-only JSONL, one record per cached
governance evaluation. Source: `ari-core/ari/rqgm/governance_cache.py`;
JSON Schema: `ari-core/ari/schemas/rqgm_governance_cache.schema.json`.
Registered in `PathManager.META_FILES` / `_TRACE_FILES` and the
node_report `files_changed` blocklist. Absence == empty cache, never an
error; absent on every `simple_bfts` checkpoint.

```json
{"schema_version": 1, "cache_key": "a3f19c02b7d4e881", "role": "judge",
 "epoch_id": "epoch_004", "prompt_hash": "9f2c01ab34de",
 "artifact_hash": "sha256:…", "input_context_hash": "sha256:…",
 "output_schema_hash": "sha256:…", "result_ref": "judgment_00042",
 "score": 0.8, "created_at": "2026-07-05T00:00:00Z"}
```

`cache_key = sha256(artifact_hash ␟ prompt_hash ␟ role ␟ epoch_id ␟
input_context_hash ␟ output_schema_hash)[:16]` (`␟` = `\x1f`); the two
content hashes are full sha256 over canonical JSON. `created_at` is
provenance only — never part of the key (P2). Replay lookups
(`rqgm.replay.use_cached_results`) compute the key with the case's
**origin** epoch id and the candidate's own `prompt_hash` — the one
sanctioned cross-epoch hit; the epoch-boundary candidate evaluation
consults this cache first and writes pool-derived per-case `score`
values back (`ari-core/ari/rqgm/governance/_adjudication.py`). Entries are never invalidated in place: a
retired prompt's entries simply stop being addressable because its
`prompt_hash` never recurs in a lookup (invariant 13). Budget consumption
and governance-level assignments are NOT stored here — they ride
`rqgm_audit.jsonl` as `budget_consumed` / `budget_degraded` /
`governance_level` lines (source: `ari-core/ari/rqgm/budget.py`), which
is also how per-epoch budget counters survive `ari resume`.

### `rqgm_eval_metrics.json` / `rqgm_injection_provenance.json` (RQGM Task 13)

Evaluation-harness artifacts, written ONLY on runs the
`scripts/rqgm_eval/run_ablation.py` harness launches itself (absent on
every normal checkpoint in both modes). Source:
`ari-core/ari/rqgm/evaluation/{metrics,injection}.py`. Both registered in
`PathManager.META_FILES` and the node_report `files_changed` blocklist.

- `rqgm_eval_metrics.json` — the thirteen post-hoc metrics from
  `compute_metric_report` (pure function over persisted artifacts; no
  LLM, no wall clock in derived values — metric 13 is metadata only,
  never hashed). Envelope: `schema_version`, `computed_by_version`,
  `condition_id`, `run_id`, `seed`, `config_digest` (sha256-12 of
  `workflow.yaml`), `injection_ids`, and `metrics{key → {value,
  numerator, denominator, evidence_refs, applicable[, detail]}}` in the
  fixed plan-§5.4 key order. Missing data sources yield
  `applicable: false`, never an error.
- `rqgm_injection_provenance.json` — the durable synthetic-trajectory
  marker (the `bfts_web_provenance.json` precedent): `schema_version`,
  `injection_ids` (held-out `eval_*` namespace, disjoint from `adv_*` /
  `anchor_*` cases), `specs_digest` (hash12 over the id-sorted canonical
  spec list), `harness_version`. Any checkpoint carrying this file is an
  injected evaluation run and must never be mistaken for a real one.

Campaign-level outputs (`ablation_report.{json,md}`, expanded condition
configs) live outside the checkpoint under `workspace/rqgm_eval/<eval_id>/`
— see `docs/guides/rqgm_evaluation.md`.

## `.ari-manuscript/` (opt-in Manuscript Complete)

This namespace is absent when `manuscript.mode: "off"`. Audit and enforce
attempts use immutable, digest-bound JSON documents:

```text
.ari-manuscript/
├── state.json
├── transitions.jsonl
├── attempts/<attempt-id>/
│   ├── source_snapshot.json
│   ├── requirement_profile.json
│   ├── context.json
│   ├── omission_manifest.json
│   ├── readiness.json
│   ├── section_briefs.json
│   ├── authoring_binding.json        # only when authoring-ready
│   └── publication_decision.json     # after verification/finalization
├── segments/*.json
├── repair-transactions/*.json
├── auto-rounds/*.json
└── attempts/<attempt-id>/publication_lock.json
                                        # only after a fresh publishable decision
```

The attempt identity is derived from the source snapshot and profile digests;
source mutation creates a new attempt rather than rewriting an old one.
Schemas are named `manuscript_*_v1.schema.json` and
`research_repair_*_v1.schema.json` under `ari-core/ari/schemas/`. The full
lineage and status rules are in the
[Manuscript Complete contract reference](manuscript_complete_contracts.md).

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
  the publish and Manuscript Complete manifests.
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml parser.
- `docs/guides/experiment_file.md` — long-form `experiment.md` guide.
