---
sources:
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/cost_tracker.py
    role: implementation
  - path: ari-skill-memory/src/ari_skill_memory/backends/letta_backend.py
    role: implementation
last_verified: 2026-08-08
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

**Cause:** Legacy fallback path is being touched.  Every release
from v0.5 onward emits a `DeprecationWarning` naming the replacement
(`ari/_deprecation.py`, `removal_version="v1.0"`); v1.0 removes the
fallback.

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

**Cause:** The command is not on `PATH`.  The `slurm_submit` script
bridge submits with `#SBATCH --export=NIL` and then sets
`PATH=/usr/local/bin:/usr/bin:/bin`, so only the base system toolchain
(typically `gcc`) is reachable — a compiler your site publishes through
environment modules (`mpicc` / `icc` / `aocc`) is not.

**Fix:** Load the module the toolchain lives in.  The bridge sources
the module system's own init on the node (`/etc/profile.d/modules.sh`,
`/etc/profile.d/lmod.sh`, `$MODULESHOME/init/bash`) before your body
runs, so a `module load` written inside the script works; passing
`modules=` to the tool instead gets a `module --force purge` first, and
exits `86` when no module system is present at all.  Otherwise replace
`mpicc` with `gcc -fopenmp` (and link OpenMPI explicitly if needed),
and declare the constraint in the experiment.md `Hardware Limits`
section.

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

# If it fails, restart per docs/guides/hpc_setup.md#6
docker compose -f scripts/letta/docker-compose.yml up -d
# or
scripts/letta/start_singularity.sh
```

The dashboard `/api/memory/health` route is the same probe, so if
the UI says "Letta unhealthy", the cluster has no Letta service
running.

### `Letta agent embedding mismatch`

**Cause:** `LETTA_EMBEDDING_CONFIG` is an embedding *handle*, not a
path to a config file, and Letta freezes an agent's `embedding_config`
at creation time.  If the checkpoint's agent was created against a
different handle — most often the hosted `letta/letta-free` →
`embeddings.memgpt.ai` endpoint, which returns 522 with an empty body
when its upstream is down — the frozen handle keeps being used whatever
the env var says, and `add_memory` fails with an opaque 400.

**Fix:** Set the handle, then purge the checkpoint's agent so the next
`add_memory` recreates it against that handle
(`LettaBackend.purge_checkpoint`; note this deletes the existing
archival passages):

```bash
export LETTA_EMBEDDING_CONFIG=openai/text-embedding-3-small
```

Left unset it defaults to `letta-default`. ARI treats an empty value,
`letta-default` and `letta/letta-free` as the same thing — "no explicit
choice" — so on the flaky MemGPT-hosted endpoint the backend only logs a
warning. The hard error above is raised only when you asked for a
*different* handle than the one the agent was frozen with. What
`letta-default` expands to on the server is Letta's own decision, not
ARI's.

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
`$ARI_CHECKPOINT_DIR/cost_trace.jsonl`.  Check the per-minute call
rate; if it exceeds the provider quota, lower `ARI_PARALLEL` or
move the BFTS judge to a cheaper / local model
(`ARI_MODEL_JUDGE=ollama/qwen3:32b`).

### Unexpected cost spike

**Diagnosis:**

```bash
python - <<'PY'
import json, collections
costs = collections.Counter()
with open(f"{__import__('os').environ['ARI_CHECKPOINT_DIR']}/cost_trace.jsonl") as fh:
    for line in fh:
        rec = json.loads(line)
        costs[rec.get("skill") or "?"] += rec["estimated_cost_usd"]
for skill, c in costs.most_common():
    print(f"{c:7.3f}  {skill}")
PY
```

Each line is a flat `CallRecord` (`timestamp`, `node_id`, `phase`,
`skill`, `model`, `*_tokens`, `estimated_cost_usd`, …); there is no
nested `metadata` object.  The additive `epoch` field is written only
by `ari_rqgm` runs, so it is absent on a default run.

The biggest spend is usually the BFTS judge (`ari-skill-evaluator`)
or the rubric review (`ari-skill-paper`).  Cap their models with
`ARI_MODEL_EVAL` / `ARI_MODEL_JUDGE`.

### Every call is booked at `$0.00`

**Cause:** The price table (`ari/configs/model_prices.yaml`) could not
be loaded — usually a malformed appended row, or PyYAML missing in a
skill venv.  With an empty table every call is estimated at 0.

**Diagnosis:** `cost_summary.json` states this explicitly:

```bash
python - <<'PY'
import json, os
s = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/cost_summary.json"))
print("pricing_table_unavailable:", s["pricing_table_unavailable"])
print("dropped_records:", s["dropped_records"], "/ call_count:", s["call_count"])
PY
```

`pricing_table_unavailable: true` means the table failed to load (the
loader also logs `model_prices table unavailable`).  A non-zero
`dropped_records` means `call_count` is an **undercount** — that many
calls had usage but their recording raised; each one logs
`cost record dropped`.

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

**Cause:** `ARI_MAX_CHILD_PROCS` is set, so the coding sandbox capped
fork() with `RLIMIT_NPROC` and a child blew through it.  There is **no
default cap** — unset, neither `ari.container` nor the coding skill
applies one.

**Fix:** Either trim the offending command (the agent often loops
into a fork bomb if the grading prompt is ambiguous) or raise
`ARI_MAX_CHILD_PROCS`.  Note that `RLIMIT_NPROC` is enforced per real
uid, not per process tree: the cap counts every task your user already
has anywhere on the host, which is why an explicit small cap fires
`EAGAIN` on an otherwise idle build.  Unsetting it is usually the right
answer.

## Dashboard / viz

### `Cannot connect to ari viz`

**Diagnosis:** `ari viz` binds to `127.0.0.1` by default.  If you
SSH'd into a remote host, you need to forward the port.

**Fix:**

```bash
# From your laptop — the WebSocket rides port+1, so forward both:
ssh -L 8765:127.0.0.1:8765 -L 8766:127.0.0.1:8766 user@remote-host
# Then on the remote (the checkpoint dir is a required argument;
# --port defaults to 8765):
ari viz /abs/path/to/checkpoints/<run_id>
```

### Frontend shows stale state

**Cause:** WebSocket reconnect pending after a backend restart.

**Fix:** Browser refresh.  The dashboard re-pulls `/state` on
connect.

## Where to look next

- `$ARI_CHECKPOINT_DIR/ari.log` — application log.
- `$ARI_CHECKPOINT_DIR/cost_trace.jsonl` — LLM cost trail
  (rollup: `cost_summary.json`).
- `$ARI_CHECKPOINT_DIR/lineage_decisions.jsonl` — stagnation
  decisions (v0.7+).
- `docs/reference/file_formats.md` — what every file in a
  checkpoint means.
- `docs/guides/migration.md` — the version-to-version migration
  recipes (v0.5 → v0.6 onward) and the GUI-refresh notes.

## See also

[FAQ](../getting-started/faq.md) · [Quickstart](../getting-started/quickstart.md) · [PaperBench troubleshooting](paperbench/paperbench_troubleshooting.md)
