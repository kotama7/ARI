---
sources:
  - path: ari-skill-replicate/schemas/replication_rubric.schema.json
    role: schema
  - path: ari-skill-replicate/src/generator.py
    role: implementation
  - path: ari-skill-replicate/src/auditor.py
    role: implementation
  - path: ari-skill-replicate/src/migration.py
    role: implementation
  - path: ari-skill-replicate/src/rubric_template.py
    role: implementation
last_verified: 2026-08-02
---

# Rubric schema reference

Canonical source: `ari-skill-replicate/schemas/replication_rubric.schema.json`
(JSON Schema Draft 2020-12, `ari.replication-rubric/v2`; the nested
PaperBench bridge version remains `3`).

The rubric envelope wraps a PaperBench `TaskNode` tree with provenance
metadata, exact artifact-backed model calls, a repair ledger, and the
`reproduce_contract` that drives both the replicator agent prompt and the typed
HPC job compiler. Audit is a separate immutable document.

## Envelope

```jsonc
{
  "schema_version": "ari.replication-rubric/v2",
  "version":       "3",
  "paper_sha256":  "<64 hex>",                     // sha256(paper text utf-8)
  "rubric_sha256": "<64 hex>",                     // sha256 of canonical-JSON rubric (self-excluded)
  "generator": {
    "model":         "gemini/gemini-2.5-pro",
    "model_revision": "immutable-provider-revision",
    "provider":      "gemini",
    "prompt_sha256": "<64 hex>",
    "generated_at":  "2026-05-13T...",
    "temperature":   0.0,
    "seed":          0,
    "strategy":      "hierarchical-v2",
    "quality_profile": "calibrated",
    "max_model_calls": 64,
    "subtree_concurrency": 4,
    "calls": [{                                     // exact bytes live under .ari-rubric/
      "label": "skeleton.attempt-1",
      "status": "completed",
      "prompt": {"relative_path": "...", "sha256": "...", "size_bytes": 1, "media_type": "text/plain"},
      "raw_response": {"relative_path": "...", "sha256": "...", "size_bytes": 1, "media_type": "text/plain"},
      "call_sha256": "<64 hex>"
    }],
    "partial_failures": []
  },
  "repair_ledger": {"actions": [], "dropped_artifacts": []},
  "reproduce_contract": { ... },                   // see below
  "rubric": { ... }                                // root TaskNode
}
```

## `reproduce_contract`

```jsonc
"reproduce_contract": {
  "script_path":      "reproduce.sh",              // const; Phase 1 entry
  "max_runtime_sec":  21600,                       // 60..43200
  "expected_artifacts": ["results.csv", "fig_1.pdf"],
  "execution_profile": { ... }                    // optional; see execution_profile.md
}
```

See [`execution_profile.md`](execution_profile.md) for the 16+
parallel-execution fields.

## `TaskNode` (rubric tree)

```jsonc
{
  "id":           "<uuid v4>",
  "requirements": "Definite, verifiable claim text (min 10 chars)",
  "weight":       1,
  "sub_tasks":    [...],                           // empty ⇒ leaf
  "task_category":             "Code Development", // LEAF ONLY
  "finegrained_task_category": "Method Implementation", // LEAF ONLY
  "rationale_from_paper": {                        // LEAF ONLY
    "section": "§3.1",
    "quote":   "<verbatim paper text, min 10 chars>"
  },
  "evidence_span": {                               // LEAF ONLY; exact and digest-bound
    "kind": "paper-span", "section": "§3.1", "quote": "...",
    "start_char": 120, "end_char": 182, "paper_sha256": "<64 hex>"
  },
  "verification": {                               // LEAF ONLY
    "kind": "artifact", "relative_path": "results.json"
  }
}
```

### Categories (closed vocabulary)

`task_category` — exactly one of:
- `Code Development`
- `Code Execution`
- `Result Analysis`

`finegrained_task_category` — exactly one of:
- `Environment & Infrastructure Setup`
- `Dataset and Model Acquisition`
- `Data Processing & Preparation`
- `Method Implementation`
- `Experimental Setup`
- `Evaluation, Metrics & Benchmarking`
- `Logging, Analysis & Presentation`

These mirror PaperBench's `VALID_*_TASK_CATEGORIES` allow-list. The
generator's `normalize_rubric_node` pass clamps any drift before
freezing.

### Weight semantics

Weighted sum aggregates leaf scores up to the root:

```
score(node) = sum_over_children(w_i * score(child_i)) / sum_over_children(w_i)
```

For leaves, `score ∈ {0, 1}` (SimpleJudge binary verdict). Internal
nodes are never directly graded — `_collapse_single_child_chains` folds
single-child wrappers into their child to avoid degenerate
weighting-only nodes.

### Audit findings

`audit_rubric` writes `ari.replication-rubric-audit/v2` beside the rubric. It
does not add fields to TaskNodes. Its deterministic and LLM findings use:

- `vague_qualifier` — "appropriate", "well-organized" etc.
- `no_paper_evidence` — quote does not appear in paper.
- `duplicate` — semantically equivalent to another leaf.
- `unverifiable` — graderless claim (subjective, future work).

`>20%` flagged leaves trigger the report's regeneration recommendation. The
report also records all auditor prompts/responses and reports
`not-independent` when generator and auditor identities match.

## Validation

```python
import json, jsonschema
from pathlib import Path

schema = json.loads(
    Path("ari-skill-replicate/schemas/replication_rubric.schema.json").read_text()
)
validator = jsonschema.Draft202012Validator(schema)
rubric = json.loads(Path("rubric.json").read_text())
validator.validate(rubric)  # raises on schema violations
```

## sha256 verification

```python
from ari_skill_replicate.manifest import verify
verify(rubric)   # True iff rubric_sha256 matches the recomputed canonical hash
```

`rubric_sha256` excludes only itself. Any post-freeze mutation invalidates the
rubric. Audit reports bind the rubric and paper digests independently.

## Version negotiation and migration

`ari-skill-paper-re` accepts `ari.replication-rubric/v2` and, during the
declared support window, an unversioned version-`3` legacy envelope through an
explicit digest-verifying V1 reader. Unknown versions, digest mismatch, and
paper mismatch fail closed. `migrate_v1_to_v2` retains the complete legacy
source under `.ari-rubric/`, records every normalization, and refuses a
migration that would drop a node. Migrated rubrics use quality profile
`requires-independent-audit`.

## Venue-conditioned templates

`generate_rubric` accepts an optional `paperbench_rubric_id` argument
that selects a YAML template from `ari-core/config/paperbench_rubrics/`.
The template's `prompt_overrides` block is injected into the skeleton
and subtree prompts via `{VENUE_HINT}` placeholders, mirroring the
`reviewer_rubrics/` venue pattern that `ari-skill-paper` uses for
peer review.

### Discovery search path

First match wins:

1. `$ARI_PAPERBENCH_RUBRIC_DIR` (env override)
2. `<cwd>/ari-core/config/paperbench_rubrics/`
3. `<cwd>/config/paperbench_rubrics/`
4. Repo-relative fallback (resolved from the skill source path)

### Modes

| `mode` | Behaviour |
|---|---|
| `agent_benchmark` | The original PaperBench framing. Direct children decompose by scientific structure (one per contribution / experiment). Leaves grade whether a candidate submission reproduces the paper. Default when no template is supplied. |
| `paper_audit` | Direct children are a fixed set of audit axes declared in `top_level_axes`. Leaves grade whether the paper text (and AD/AE appendix when supplied) describes enough to reproduce — code execution is out of scope. Used for reproducibility-audit research (HPC_PaperBench, NeurIPS Checklist, Nature Reporting Summary). |

### YAML schema

```yaml
id: <slug>                # filesystem-safe id; must match the filename (no .yaml)
version: "2026"
venue: "<human-readable venue name>"
domain: "<HPC / ML / Wet-lab / ...>"
mode: <agent_benchmark | paper_audit>

# REQUIRED when mode = paper_audit; ignored when mode = agent_benchmark.
top_level_axes:
  - id: <axis_slug>
    name: <human-readable name>
    weight: <positive integer>
    description: <one-paragraph requirement that drops into the rubric tree>

prompt_overrides:
  system_hint: |
    <free-form text injected at the top of the skeleton prompt — sets
    the framing change, surfaces venue-specific failure modes>
  leaf_style: |
    <free-form text injected at the top of the subtree prompt — pins
    the YES/NO phrasing the downstream pass should use for leaves>
```

Every mode uses the mandatory calibrated hierarchical strategy. This preserves
the fixed-axis constraint for `paper_audit` templates.

### Shipped templates

| `id` | `mode` | Axes |
|---|---|---|
| `generic` | `agent_benchmark` | (free-form — decomposes by paper contribution) |
| `sc` | `paper_audit` | env_reconstructable, data_available, execution_specified, figures_consistent, scaling_consistent, conclusion_supported |
| `neurips` | `paper_audit` | claims_supported, experimental_setup, code_data_available, statistical_rigor, ethics_limitations, figures_consistent |
| `nature` | `paper_audit` | materials_traceable, protocol_specified, statistics_reported, data_availability, ethics_compliance |

### Adding a new venue

1. Copy `generic.yaml` or `sc.yaml` and rename to `<venue_id>.yaml`.
2. Set `mode`, fill `top_level_axes` (for `paper_audit`), and write
   `prompt_overrides.system_hint` / `prompt_overrides.leaf_style` to
   surface venue-specific failure modes.
3. No code change is required — the loader picks up new files via
   the search path.

ARI core stays domain-agnostic (P4); venue knowledge lives in YAML.

## See also

- [Execution profile reference](execution_profile.md)
- [PaperBench API reference](api_paperbench.md)
- Skill source: `ari-skill-replicate/src/generator.py`,
  `ari-skill-replicate/src/rubric_template.py`
- Template directory: `ari-core/config/paperbench_rubrics/`
- Sibling venue pattern: `ari-core/config/reviewer_rubrics/` (peer review)
- PaperBench parity: `paperbench/nano/tasks.py` (vendor)
