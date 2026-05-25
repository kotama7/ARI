---
sources:
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py
    role: implementation
last_verified: 2026-05-25
---

# Troubleshooting

Common runtime failures and their fixes.  Each section gives the
symptom (often the exact error string), the cause, and the
remediation.

## Startup failures

### `ARI_CHECKPOINT_DIR is not set`

**Cause:** Every state file in v0.5+ is scoped to a checkpoint, so
the env var is mandatory.

**Fix:**

```bash
export ARI_CHECKPOINT_DIR=/abs/path/to/checkpoints/$(date +%Y%m%d_%H%M%S)
mkdir -p "$ARI_CHECKPOINT_DIR"
ari run /abs/path/to/experiment.md
```

If you launch from `sbatch`, set this in the job script — not in a
shell rc file — so sub-experiments can override it.

### `DeprecationWarning: $HOME/.ari/...`

**Cause:** Legacy fallback path is being touched.  v1.0 will hard-
fail on this; v0.5–v0.8 emit a warning.

**Fix:** Set the explicit env var.  Mapping table:

| Legacy path | New env var |
|---|---|
| `$HOME/.ari/registries.yaml` | `ARI_REGISTRIES_FILE` |
| `$HOME/.ari/registry-data` | `ARI_REGISTRY_DATA` |
| `$HOME/.ari/letta-pid` | `ARI_LETTA_PIDFILE` |

### `ImportError: cannot import name '<X>' from 'ari'`

**Cause:** A skill is reaching into ARI internals that moved during
the Phase 4 refactor.

**Fix:** Switch the import to `ari.public.<X>` (see
`docs/reference/public_api.md`).  If the symbol is not yet exposed
publicly, file an issue with the use case.

## SLURM problems

### Job stuck in `PENDING`

**Causes (in order of likelihood):**

1. The partition is full or in maintenance.
2. The requested wall-time / CPUs / GPUs exceed what the partition
   allows.
3. Your account has no remaining allocation.

**Diagnosis:**

```bash
sinfo -p $SLURM_PARTITION       # Look at AVAIL / STATE
squeue -u $USER                  # Check NODELIST(REASON) column
sacct -j <jobid> --format=Reason # Sometimes more verbose
```

If `Reason` is `Resources` or `Priority`, you're queued; if it is
`PartitionConfig` or `QOSMaxJobsPerUserLimit`, your request is
rejected.

### `exit_code=127` from a build step

**Cause:** Almost always a missing compiler.  The HPC skill
restricts you to `gcc`; `mpicc` / `icc` / `aocc` are not in the
default PATH on most clusters.

**Fix:** Replace `mpicc` with `gcc -fopenmp` (and link OpenMPI
explicitly if needed).  Update the experiment.md `Hardware Limits`
section to declare the constraint upfront.

### `--account` rejected

**Cause:** Most clusters reject `#SBATCH --account=` / `-A` headers
unless your site enables Slurm accounting.

**Fix:** Remove the header.  ARI's `slurm_submit` no longer adds
one; if you see it, check the `SLURM Script Template` section of
your `experiment.md`.

## Memory backend (Letta)

### `connection refused` when calling Letta

**Cause:** No Letta server running, or `LETTA_BASE_URL` points to
the wrong endpoint.

**Fix:**

```bash
curl -fsS http://127.0.0.1:8283/healthz   # Should return 200

# If it fails, restart per docs/hpc_setup.md#6
docker compose -f containers/letta/docker-compose.yml up -d
# or
apptainer run containers/letta.sif &
```

The dashboard `/api/memory/health` route is the same probe, so if
the UI says "Letta unhealthy", the cluster has no Letta service
running.

### `LETTA_EMBEDDING_CONFIG is required`

**Cause:** Letta needs an embedding model config to build the
archival collections.

**Fix:** Point `LETTA_EMBEDDING_CONFIG` at a JSON file describing
the embedding endpoint.  An OpenAI-compatible example:

```json
{
  "embedding_endpoint_type": "openai",
  "embedding_model": "text-embedding-3-small",
  "embedding_dim": 1536,
  "embedding_endpoint": "https://api.openai.com/v1"
}
```

### `archival memory search returned 0 results`

**Cause:** Likely a data path mismatch.  `search_memory` uses the
embedding-ranked `passages.search` (`embed_query=True`); if you fall
back to `passages.list(search=q)` the SQL `LIKE` matcher silently
returns 0 hits for long natural-language queries.

**Fix:** Confirm the active backend by calling
`/api/memory/detect`.  If you've patched the skill, ensure you are
on the `passages.search` route (see
`ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py`).

## LLM cost / quota

### `litellm.exceptions.RateLimitError`

**Cause:** Provider rate limit.

**Fix:** ARI records every LLM call in
`$ARI_CHECKPOINT_DIR/cost_log.jsonl`.  Check the per-minute call
rate; if it exceeds the provider quota, lower `ARI_PARALLEL` or
move the BFTS judge to a cheaper / local model
(`ARI_MODEL_JUDGE=ollama/qwen3:32b`).

### Unexpected cost spike

**Diagnosis:**

```bash
python - <<'PY'
import json, collections
costs = collections.Counter()
with open(f"{__import__('os').environ['ARI_CHECKPOINT_DIR']}/cost_log.jsonl") as fh:
    for line in fh:
        rec = json.loads(line)
        costs[rec["metadata"].get("skill", "?")] += rec["cost_usd"]
for skill, c in costs.most_common():
    print(f"{c:7.3f}  {skill}")
PY
```

The biggest spend is usually the BFTS judge (`ari-skill-evaluator`)
or the rubric review (`ari-skill-paper`).  Cap their models with
`ARI_MODEL_EVAL` / `ARI_MODEL_JUDGE`.

## VLM (figure / table review)

### `VLM model returned no caption`

**Cause:** Either the VLM is not vision-capable, or the image
encoded badly.

**Fix:**

```bash
# Verify the model.
echo "$VLM_MODEL"   # should be something like openai/gpt-4o, ollama/qwen2.5vl:32b
# Verify the image.
file $ARI_CHECKPOINT_DIR/figures/fig1.png   # should report PNG
```

If the model is text-only (e.g. `gpt-3.5-turbo`), switch to a
vision model.

## Container / sandbox

### `singularity exec: command not found`

**Cause:** Apptainer / Singularity is not installed on the host.

**Fix:** Either install it (Apptainer is the canonical successor to
Singularity), or unset `ARI_CONTAINER_IMAGE` to fall back to host
execution.

### `RLIMIT_NPROC: resource temporarily unavailable`

**Cause:** The coding sandbox capped fork() at
`ARI_MAX_CHILD_PROCS` (default 1024) and a child blew through it.

**Fix:** Either trim the offending command (the agent often loops
into a fork bomb if the grading prompt is ambiguous) or raise
`ARI_MAX_CHILD_PROCS`.  The default is intentionally generous —
running into it usually means a real bug, not a budget shortage.

## Dashboard / viz

### `Cannot connect to ari viz`

**Diagnosis:** `ari viz` binds to `127.0.0.1` by default.  If you
SSH'd into a remote host, you need to forward the port.

**Fix:**

```bash
# From your laptop:
ssh -L 8000:127.0.0.1:8000 user@remote-host
# Then on the remote:
ari viz --port 8000
```

### Frontend shows stale state

**Cause:** WebSocket reconnect pending after a backend restart.

**Fix:** Browser refresh.  The dashboard re-pulls `/state` on
connect.

## Where to look next

- `$ARI_CHECKPOINT_DIR/ari.log` — application log.
- `$ARI_CHECKPOINT_DIR/cost_log.jsonl` — LLM cost trail.
- `$ARI_CHECKPOINT_DIR/lineage_decisions.jsonl` — stagnation
  decisions (v0.7+).
- `docs/reference/file_formats.md` — what every file in a
  checkpoint means.
- `docs/refactor_audit.md` — known migration debt.
