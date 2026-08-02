# ari-skill-replicate

ORS Auto-Rubric generator and auditor (PaperBench TaskNode-compatible).

## Tools

- `generate_rubric(..., two_stage=True, quality_profile="", max_model_calls=64, subtree_concurrency=4, provider="", model_revision="")` — produces a strict `ari.replication-rubric/v2` envelope. Every model prompt/response, repair, dropped node, exact paper span, model identity, and call budget is recorded beside the output under `.ari-rubric/`.
- `audit_rubric(..., output_path="", max_model_calls=400)` — verifies the frozen rubric and its referenced artifacts, then writes a separate digest-bound `ari.replication-rubric-audit/v2` report. It never mutates the rubric. The report flags `vague_qualifier`, `no_paper_evidence`, `duplicate`, and `unverifiable` leaves and reports whether the reviewer model is actually independent.
- `suggest_target_leaf_count(paper_path, paper_text)` — returns the auto-computed target leaf count (~1 leaf / 75 words, bounded to [50, 400]) and word count for the paper.

## Two-stage generation

The default rubric path is hierarchical (`prompts/skeleton.md` + `prompts/subtree.md`):

1. **Pass 1 — skeleton**: a single LLM call defines the root + direct children (one node per major contribution / experiment / section), and assigns each a `target_subtree_leaves` budget summing to the overall target.
2. **Pass 2 — subtrees (parallel)**: one call per direct child populates its subtree with 4–6 additional levels, scoped to the parent's `requirements`. Concurrency is bounded by an internal semaphore (default 4).
3. **Merge + evidence binding**: subtree roots replace skeleton stubs. Each retained leaf is bound to exact character offsets in the input paper or an explicit external prerequisite and receives a structured artifact/log/metric verification target. Every normalization or dropped node is retained in the repair ledger.

Single-call mode (`two_stage=False`) is retained only as an explicit low-coverage compatibility profile: callers must also set `quality_profile="low-coverage"`. Hierarchical generation fails closed when its call budget is exhausted and records subtree failures instead of silently treating missing coverage as success.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `ARI_MODEL_RUBRIC_GEN` | `gemini/gemini-2.5-pro` | Generator LLM |
| `ARI_MODEL_RUBRIC_GEN_PROVIDER` / `ARI_MODEL_RUBRIC_GEN_REVISION` | inferred / unset | Immutable generator identity |
| `ARI_MODEL_RUBRIC_AUDIT` | `anthropic/claude-opus-4-7` | Auditor LLM (independent from generator) |
| `ARI_MODEL_RUBRIC_AUDIT_PROVIDER` / `ARI_MODEL_RUBRIC_AUDIT_REVISION` | inferred / unset | Auditor identity used for the independence decision |
| `ARI_RUBRIC_GEN_TARGET_LEAVES` | (unset) | Override the per-paper target leaf count. `0` / unset → auto from paper length. Set by the GUI Wizard's "Target leaves" field. |
| `ARI_RUBRIC_GEN_TEMPERATURE` | (unset) | Override generator temperature. Set by the GUI Wizard's "Temperature" field. |
| `ARI_RUBRIC_GEN_TWO_STAGE` | (unset) | `1`/`true`/`on` → force two-stage; `0`/`false`/`off` → force single-call. Unset → use the kwarg default (currently `True`). Set by the GUI Wizard's "Two-stage generation" toggle. |
| `ARI_RUBRIC_GEN_QUALITY_PROFILE` | (unset) | Required as `low-coverage` when single-call generation is selected. |

Resolution order (server.py): explicit kwarg → env var → default. The MCP tool is invoked by `ari-core/config/workflow.yaml::ors_generate_rubric`; the workflow does not pass these three knobs explicitly, so env vars set by the GUI Wizard always win over the kwarg defaults at runtime.

## Output schema

See `schemas/replication_rubric.schema.json` and `schemas/replication_rubric_audit.schema.json`. The frozen rubric and audit are distinct immutable documents. `ari-skill-paper-re` accepts V2 and a digest-verified legacy V1 reader during the migration window; unknown versions, tampered envelopes, and paper-digest mismatches fail before execution or grading. `src/migration.py::migrate_v1_to_v2` performs an offline, lossless migration and preserves the complete V1 source artifact.

## `execution_profile` (HPC / parallel-execution hints)

Optional sibling of `expected_artifacts` under `reproduce_contract`. Populated by the generator when the paper specifies parallel execution properties (MPI rank counts, GPU types, node exclusivity, etc.); compiled by `ari-skill-paper-re` into the common typed HPC job contract and consumed by the BasicAgent prompt. Omit entirely for legacy single-CPU papers — backward compatible.

```jsonc
"reproduce_contract": {
  "script_path": "reproduce.sh",
  "max_runtime_sec": 7200,
  "expected_artifacts": ["submission/results/scaling_strong.csv"],
  "execution_profile": {
    "kind": "mpi_gpu",                                  // cpu_single | gpu_single | gpu_multi | mpi | mpi_gpu
    "paper_max_ranks": 32,
    "paper_max_nodes": 4,
    "min_ranks": 4,
    "result_aggregation": "rank0_csv",
    "metric_columns": ["nodes", "ranks", "runtime_sec", "gflops"],
    "accepts_reduced_scale": true,
    "requested_nodes": 4,
    "ntasks_per_node": 8,
    "exclusive": true,                                  // → --exclusive
    "requested_gpus_per_task": 1,                       // typed per-task GPU request
    "gpu_type": "v100",                                 // typed GPU selector
    "memory_gb_per_node": 256,                          // → --mem=256G
    "constraint": "skylake",                            // → --constraint=skylake
    "cpu_bind": "cores",                                // emitted inside the srun job step
    "module_loads": ["cuda/12.4", "openmpi/4.1"],       // clean, recorded module environment
    "account": "projX"                                  // typed scheduler policy field
  }
}
```

The full set of fields (allocation fields compile to `ResourceRequestV1`; job-step fields remain in the generated reproduction script):

| Field | Consumed as | Notes |
|---|---|---|
| `kind` | agent prompt only | drives whether agent uses CUDA / MPI |
| `paper_max_ranks`, `paper_max_nodes`, `min_ranks`, `min_nodes` | agent prompt | the agent's scale budget |
| `metric_columns`, `result_aggregation`, `accepts_reduced_scale` | agent prompt | CSV header contract |
| `requested_nodes` | `--nodes=N` | |
| `ntasks_per_node` | `--ntasks-per-node=N` | 0 = leave to SLURM |
| `requested_nodelist` / `exclude_nodes` | `--nodelist=...` / `--exclude=...` | |
| `exclusive` | `--exclusive` | important for performance reproduction |
| `requested_gpus_per_task` / `requested_gpus_per_node` | typed per-task / per-node GPU request | mutually exclusive |
| `gpu_type` | typed GPU selector | requires an explicit GPU count |
| `memory_gb_per_node` / `memory_gb_per_cpu` | `--mem=NG` / `--mem-per-cpu=NG` | |
| `constraint` | `--constraint=...` | e.g. `skylake`, `haswell\|broadwell` |
| `cpu_bind`, `mem_bind` | generated `srun` job step | NUMA / CPU affinity is not an allocation option |
| `hint` | typed scheduler hint | bounded enum |
| `module_loads` | clean module environment | recorded in job provenance |
| `account`, `qos`, `reservation` | typed scheduler policy fields | inert identifiers only |
| `extra_sbatch_args` | deprecated compatibility reader | accepts only account/QoS/reservation/hint; new producers never emit it |

For the typed consumer, lifecycle, environment, and shared-filesystem operator contract, see `ari-skill-paper-re/REQUIREMENTS.md` and `ari-skill-hpc/README.md`.
