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
    "extra_sbatch_args": ["--account=projX"]
  },
  "judge_config":     {"model": "gpt-5-mini", "n_runs": 1},
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

## See also

- [PaperBench GUI guide](../howto/paperbench_gui.md)
- [Execution profile reference](execution_profile.md)
- Source: `ari-core/ari/viz/api_paperbench.py`
