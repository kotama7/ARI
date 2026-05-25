---
sources:
  - path: ari-skill-hpc
    role: implementation
  - path: containers
    role: config
last_verified: 2026-05-25
---

# HPC Setup Guide

This guide covers running ARI on a SLURM cluster, deploying ARI inside
Apptainer / Singularity / Docker, and pointing the memory backend at a
shared Letta service.  Replace cluster-specific names (partition,
login node, paths) with your own.

## 1. Environment

ARI is a normal Python application — install once with `setup.sh`,
then drive it from the login node or a sbatch wrapper.  Required env
vars on every cluster:

| Variable | Purpose |
|---|---|
| `ARI_CHECKPOINT_DIR` | Active checkpoint root (every input/output is scoped here) |
| `ARI_LLM_MODEL` | LiteLLM model id (e.g. `ollama/qwen3:32b`, `openai/gpt-4o`) |
| `ARI_LLM_API_BASE` | Optional — pin the LLM endpoint if not the LiteLLM default |
| `OLLAMA_HOST` / `OLLAMA_MODELS` | Required if the LLM is local Ollama |

> v0.5.0 removed the global `$HOME/.ari/` directory — every state file
> now lives under `ARI_CHECKPOINT_DIR` or under an explicit env var.
> Set the env vars in your sbatch wrapper, *not* in shell rc files
> (so a sub-experiment can override them).

## 2. Available partitions (template)

| Partition | Hardware | Notes |
|-----------|----------|-------|
| `your_cpu_partition` | CPU nodes | BFTS exploration, baseline benchmarks |
| `your-gpu-partition` | NVIDIA L40S | LLM inference for the agent loop |
| `your-h200-partition` | NVIDIA H200 | Large-model inference, paper review |
| `your_gpu_partition` | GPU nodes | GPU-bound experiments |

Pick partitions with the `--partition=` field of your `sbatch`
wrapper.  ARI picks up `SLURM_DEFAULT_PARTITION` for sub-jobs.

## 3. Run ARI on the cluster

### Submit a BFTS run

```bash
sbatch ~/ARI/scripts/run_ari.sh
```

### Monitor

```bash
squeue -u $USER
tail -f $ARI_CHECKPOINT_DIR/ari.log
```

### Inspect results

```bash
# Best metric from a completed run.
python - <<'PY'
import json, os
r = json.load(open(f"{os.environ['ARI_CHECKPOINT_DIR']}/results.json"))
for nid, n in r["nodes"].items():
    if n.get("has_real_data"):
        print(nid[:12], n["metrics"])
PY
```

## 4. SLURM script template

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# Checkpoint scope — every state file goes here.
export ARI_CHECKPOINT_DIR=/abs/path/checkpoints/$(date +%Y%m%d_%H%M%S)

# Local LLM (Ollama on the GPU node) — skip this block when using a remote LLM.
export OLLAMA_HOST=127.0.0.1:11434
export OLLAMA_MODELS=/home/youruser/.ollama/models
export OLLAMA_CONTEXT_LENGTH=8192
export OLLAMA_NUM_PARALLEL=2
/home/youruser/local/ollama/bin/ollama serve &
OLLAMA_PID=$!
for i in $(seq 1 30); do
  curl -sf http://127.0.0.1:11434/api/tags > /dev/null 2>&1 && break
  sleep 2
done

# Defaults inherited by sub-jobs that ARI launches via the hpc skill.
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# Optional: choose a specific reviewer rubric (see docs/architecture.md).
export ARI_RUBRIC=neurips2025

cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run /abs/path/to/experiment.md

kill $OLLAMA_PID 2>/dev/null || true
```

## 5. Container deployments (v0.7+)

ARI ships three deployment recipes for environments that prohibit
running tools directly on a login node.  They are equivalent — pick
whichever your site supports.

### Apptainer / Singularity

`scripts/registry/start_singularity.sh` is the reference launcher; the
same recipe works for the agent loop:

```bash
apptainer build ari.sif containers/ari.def
apptainer exec --bind /scratch:/scratch ari.sif \
    ari run /abs/path/to/experiment.md
```

`ari-skill-coding` and `ari-skill-hpc` honour
`ARI_CONTAINER_IMAGE=/path/to/ari.sif` and
`ARI_CONTAINER_MODE=singularity` to wrap the user code itself in the
SIF — useful for reproducible benchmarks.

### docker-compose (single host)

`scripts/registry/docker-compose.yml` is the production recipe for the
registry; an analogue exists for the full stack:

```bash
docker compose -f containers/ari/docker-compose.yml up -d
```

### Pip (development, no container)

```bash
./setup.sh                # creates the virtualenv + installs ari-core
ari run experiment.md     # uses the host python directly
```

## 6. Letta memory backend deployment

`ari-skill-memory` defaults to a Letta backend (v0.6+).  The skill
talks to a Letta service via `LETTA_HOST` / `LETTA_PORT` (default
`127.0.0.1:8283`).  Three deployment paths:

| Path | When to pick it |
|---|---|
| Apptainer SIF (`containers/letta.sif`) | HPC where Docker is unavailable |
| docker-compose (`containers/letta/docker-compose.yml`) | Dev workstation, single-node prod |
| Pip (`pip install letta && letta server`) | Quick smoke tests; not for shared clusters |

Required env vars regardless of deployment:

| Variable | Purpose |
|---|---|
| `LETTA_HOST` / `LETTA_PORT` | Where the Letta API is listening |
| `LETTA_EMBEDDING_CONFIG` | Path to the embedding configuration JSON (required) |
| `OPENAI_API_KEY` etc. | Whatever the embedding model needs |

Each ARI checkpoint owns its own Letta agent (collections
`ari_node_<ckpt_hash>` + `ari_react_<ckpt_hash>`).  Deleting the
checkpoint via `ari ckpt delete` automatically deletes the matching
Letta agent — see `ari-skill-memory/README.md` for the deletion path.

## 7. Critical SLURM constraints

| Rule | Detail |
|------|--------|
| Compiler | Use `gcc` only.  `mpicc` / `icc` / `aocc` produce `exit_code=127` on most clusters |
| CPU limit | `--cpus-per-task` must respect the partition's per-node CPU count |
| Path expansion | Never use `~` in `#SBATCH` lines — always absolute paths |
| stdout redirect | Never redirect stdout in the job script — SLURM captures via `--output` |
| Account header | `--account` / `-A` are rejected on most cluster configs — only add them if your site requires it |
| Output filename | Match the pattern your skill expects (e.g. `slurm_job_{JOBID}.out`) |

## 8. Ollama model recommendations

| Model | Best for |
|-------|---------|
| `qwen3:32b` | Default — best tool-calling quality on local hardware |
| `qwen3:8b` | Faster, lower quality, good for smoke tests |
| `deepseek-r1:32b` | Reasoning-heavy tasks (lineage decision, paper review) |
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI-compatible alternative |
| `qwen2.5vl:32b` | Vision tasks (figure / table review via `ari-skill-vlm`) |

## See also

- `docs/configuration.md` — every environment variable ARI honours
- `docs/architecture.md` — runtime architecture, memory layout, layered structure
- `ari-skill-hpc/README.md` — SLURM tool reference (local + SSH modes)
- `ari-skill-memory/README.md` — backend selection + Letta deployment recipe
