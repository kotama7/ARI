---
sources:
  - path: ari-core/ari/viz/api_paperbench.py
    role: implementation
  - path: ari-skill-paper-re/src/_paperbench_bridge.py
    role: implementation
  - path: ari-skill-paper-re/src/server.py
    role: implementation
last_verified: 2026-05-25
---

# PaperBench API reference

All endpoints are served by the ARI viz server (`ari viz` /
`python -m ari.viz.server`) on the same host as the dashboard. JSON
bodies use `Content-Type: application/json`. DELETE-equivalent
operations go through POST `.../delete` to match the existing routing
conventions (see `ari-core/ari/viz/routes.py`).

## Papers

### `GET /api/paperbench/papers`

List every paper in the registry.

```json
{
  "papers": [
    {
      "paper_id": "2404.14193",
      "title": "LLAMP: assessing latency tolerance",
      "license": "cc by 4.0",
      "license_assessment": {"usable": true, "note": "permissive — usable"},
      "source_type": "arxiv",
      "source": "2404.14193",
      "imported_at": "2026-05-13T...",
      "registry_dir": "/home/.../paper_registry/papers/2404.14193"
    }
  ]
}
```

### `POST /api/paperbench/papers/import`

Register a new paper. Body fields:

| Field | Required | Notes |
|---|---|---|
| `source_type` | yes | `arxiv` \| `doi` \| `upload` \| `local` |
| `source` | yes | identifier or path |
| `title` | yes | free-form |
| `license` | recommended | classified server-side; missing ⇒ "unknown" |
| `authors` | no | list of strings |
| `venue` / `year` / `artifact_url` | no | optional metadata |
| `paper_id` | no | defaults to sanitized `source`; sanitized to `[A-Za-z0-9._-]{1,64}` |
| `pdf_path` | no | absolute path to a local PDF; copied to `papers/<paper_id>/paper.pdf` |
| `ad_pdf_path` / `ae_pdf_path` | no | optional artefact appendices |
| `overwrite` | no | `true` ⇒ replace duplicate |

Returns the manifest entry on success, `{error: "..."}` on collision
(without `overwrite`) or validation failure.

### `POST /api/paperbench/papers/<paper_id>/delete`

Remove the manifest line + the on-disk paper directory. Idempotent.

```json
{"deleted": true, "paper_id": "2404.14193"}
```

### `POST /api/paperbench/papers/<paper_id>/metadata`

Patch the manifest entry. Pass any subset of writable fields
(`paper_id` itself is immutable). Re-classifies the license if the
`license` field is in the patch body.

### `GET /api/paperbench/papers/<paper_id>/license`

Returns the structured license assessment for a single paper:

```json
{
  "license": "cc by 4.0",
  "permissive": true,
  "modifiable": true,
  "redistributable": true,
  "usable": true,
  "note": "permissive license — ari may use freely"
}
```

## Runs

### `POST /api/paperbench/run`

Enqueue PaperBench runs.

```json
{
  "paper_ids": ["2404.14193"],
  "rubric_config":    {"model": "gemini/gemini-2.5-pro", "two_stage": true},
  "reproduce_config": {
    "model": "gpt-5-mini",
    "time_limit_sec": 43200,
    "iterative_agent": false,
    "sandbox_kind": "slurm",
    "partition": "large",
    "nodes": 4,
    "ntasks": 32,
    "ntasks_per_node": 8,
    "exclusive": true,
    "gpus_per_task": 1,
    "gpu_type": "v100",
    "memory_gb_per_node": 256,
    "constraint": "skylake",
    "cpu_bind": "cores",
    "account": "projX"
  },
  "judge_config":     {"model": "gpt-5-mini", "n_runs": 1, "code_only": false},
  "dry_run": false
}
```

Response (real launch):

```json
{
  "dry_run": false,
  "job_ids": ["abc123..."],
  "estimated_cost": {
    "wall_time_sec": 43560,
    "llm_cost_usd": 2.55,
    "breakdown": { ... }
  }
}
```

When `dry_run: true`, no job is created; only the cost estimate is
returned alongside `papers` (count) and totals.

### `GET /api/paperbench/run/<job_id>`

Status snapshot. Fields: `status` (`queued` / `running` / `completed`
/ `failed`), `current_stage`, `progress`, `created_at`, plus the
original `configs`.

### `GET /api/paperbench/run/<job_id>/results`

Returns the grader output when the job's status is `completed`;
`{error: "results not available", status: "<state>"}` otherwise.

## Cost estimate

### `POST /api/paperbench/cost-estimate`

Same body shape as `/api/paperbench/run` minus `paper_ids` and
`dry_run`. Returns wall-time + cost projections for one paper.

```json
{
  "wall_time_sec": 43560,
  "llm_cost_usd": 2.55,
  "breakdown": {
    "rubric":    {"wall_time_sec": 300, "cost_usd": 0.45},
    "reproduce": {"wall_time_sec": 43200, "cost_usd": 2.0},
    "judge":     {"wall_time_sec": 60, "cost_usd": 0.10}
  }
}
```

## CORS / authentication

The viz server allows all origins (`*`) on the dashboard endpoints and
performs no authentication — it is expected to be bound to localhost
or behind an SSH tunnel. Do **not** expose it on a public interface
without an upstream reverse proxy.

## Bridge contract (in-process Python surface)

For callers running in-process (orchestrators, dogfood scripts, custom
pipelines), `ari-skill-paper-re/src/_paperbench_bridge.py` exposes three
keyword-only async callables matching PaperBench's 3-stage protocol
(arXiv:2504.01848 §3). All three share the same
`(paper_md, work_dir-or-submission_dir, model, …)` vocabulary so they
can be chained:

| Stage | Function | Wraps |
|---|---|---|
| 1 — Agent rollout | `rollout_submission(paper_md, work_dir, agent_model, sandbox_kind, container_image, iterative_agent, env, agent_env_path, forbid_host_filesystem, blacklist_urls, time_limit_sec, …)` | `_replicator_agent.run_replicator_agent` (vendor BasicAgent / IterativeAgent) |
| 2 — Reproduction | `reproduce_submission(submission_dir, sandbox_kind, container_image, partition, gpus_per_task, gpu_type, memory_gb_per_node, exclusive, capture_tarball, tarball_dir, salvage_retries, retry_threshold_sec, time_limit_sec)` | `server.run_reproduce` (typed HPC handle or host sandbox dispatch; deprecated `extra_sbatch_args` reader retained temporarily) |
| 3 — Grading | `judge_submission(paper_md, rubric, submission_dir, reproduce_log, judge_model, paper_audit_mode, code_only, …)` | vendor `SimpleJudge` direct |

Vendor-fidelity behaviour built into the bridge:

- **submission-root resolution (v0.8.0)** — `reproduce_submission` and
  `judge_submission` descend into a nested `submission/` when the agent
  built its self-contained repo there (the workspace presents the
  vendor's `/home/submission` as a workspace-relative `submission/`, so an
  agent following the prompt nests one level). Reproduction/grading then
  run where `reproduce.sh` is co-located with its sources, matching the
  vendor reproducer's cd-into-submission semantics; an orphaned top-level
  `reproduce.sh` copy is ignored. This is what stops the
  `src/…: No such file or directory` build failure that otherwise zeros
  every Code Execution / Result Analysis leaf.
- **apply_patch command parity (v0.8.0)** — the host-side `LocalComputer`
  exposes the vendor's own `apply_patch.py` on PATH (as both `apply_patch`
  and `applypatch`), mirroring the vendor Docker image's
  `/bin/apply_patch`. gpt-5 / codex agents reflexively edit files via
  `apply_patch <<'PATCH' … PATCH`; without this they fail `command not
  found` and waste tool-call budget. Apptainer SIFs already carry the
  command, so the shim is host-sandbox-only.
- **immutable container identity** — local non-symlink SIF files are hashed;
  Docker accepts a full `sha256:<image-id>` or `name@sha256:<digest>`;
  remote Apptainer references require `@sha256:<digest>`. Mutable tags and
  the former `pb-env` / `pb-reproducer` aliases fail closed.
- **agent.env auto-load** — when `agent_env_path` unset, auto-discovers
  `$ARI_AGENT_ENV_PATH` then `~/.ari/agent.env`. `HF_TOKEN` from the
  calling process env is automatically forwarded to the agent.
- **forbid_host_filesystem** — refuses `sandbox_kind=local/slurm`
  combinations (host-FS leak surface). Default False preserves
  development workflows.
- **blacklist_urls** — prepends a `FORBIDDEN URLS` block to the
  agent's instruction prompt AND exports `ARI_BLACKLIST_URLS` env var
  so downstream tool wrappers can refuse.
- **salvage_retries** — opt-in vendor-style retry on
  early-failure runs (per
  `vendor/.../reproduce.py:252 reproduce_on_computer_with_salvaging`).
  Tracks wall-clock across attempts so the total budget is honoured.
- **capture_tarball** — writes per-attempt
  `submission_executed_<UTC>.tar.gz` next to the submission so a run
  is re-gradable.
- **code_only** — when True, explicitly prunes a verified successful
  reproduction to Code Development leaves (vendor
  `paperbench/grade.py:109-112`). Missing reproduction records fail without a
  scientific score.
- **paper_audit_mode** — patches vendor `TASK_CATEGORY_QUESTIONS` to
  paper-audit phrasing. Mutually exclusive with `code_only`.

Fail-loud preconditions (there is no host-local downgrade):

| Condition | Env override |
|---|---|
| `sandbox_kind=docker` but daemon unreachable | start Docker or select an available reviewed sandbox |
| `sandbox_kind=apptainer/singularity` but binary missing | install the runtime or select another reviewed sandbox |
| `sandbox_kind=slurm` but `sbatch` missing or no partition | configure the scheduler/partition |
| GPU request unsupported by the selected partition | fix GRES/select a compatible partition; no silent downgrade |

## See also

- [PaperBench GUI guide](../guides/paperbench/paperbench_gui.md)
- [PaperBench quickstart](../guides/paperbench/paperbench_quickstart.md)
- [Environment variables](environment_variables.md)
- [MCP tool reference](mcp_tools.md)
- [Execution profile reference](execution_profile.md)
- Source:
  `ari-core/ari/viz/api_paperbench.py`
  /
  `ari-skill-paper-re/src/_paperbench_bridge.py`
  /
  `ari-skill-paper-re/src/server.py`
