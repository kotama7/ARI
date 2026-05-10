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
`primary_metric`.  See `docs/experiment_file.md` for the full guide.

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

Bundled defaults live in `ari-core/ari/configs/workflow.default.yaml`.

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

- `docs/architecture.md` (Checkpoint Directory Layout) — narrative
  view of the same files.
- `ari-core/ari/schemas/` — formal JSON Schemas for `node_report` and
  the publish manifest.
- `ari-core/ari/pipeline/yaml_loader.py` — workflow.yaml parser.
- `docs/experiment_file.md` — long-form `experiment.md` guide.
