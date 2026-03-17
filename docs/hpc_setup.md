# HPC Setup Guide

## Environment

- **Cluster**: your HPC cluster (`your-cluster-login-node`)
- **SSH alias**: `ssh your-cluster`
- **Python**: `~/miniconda3/bin/python3` (3.13)
- **Ollama**: `~/local/ollama/bin/ollama`
- **ARI root**: `~/ARI/`

## Available Partitions

| Partition | Hardware | Max CPUs | Use Case |
|-----------|----------|----------|----------|
| `your_cpu_partition` | CPU nodes | varies | CPU experiments |
| `your-gpu-partition` | NVIDIA L40S GPU | — | LLM inference, GPU experiments |
| `your-h200-partition` | NVIDIA H200 GPU | — | Large model inference |
| `your_gpu_partition` | GPU nodes | — | GPU experiments |

## Running ARI on HPC

### Submit a BFTS run

```bash
sbatch ~/ARI/logs/your_job_script.sh
```

### Monitor

```bash
squeue -u $USER
tail -f ~/ARI/logs/ari_run_<JOBID>.out
```

### Check results

```bash
# Best MFLOPS from completed run
python3 -c "
import json
r = json.load(open('~/ARI/logs/ckpt_<run_id>/results.json'))
for nid, n in r['nodes'].items():
    if n.get('has_real_data'):
        print(nid[:12], n['metrics'])
"
```

## SLURM Script Template for ARI

```bash
#!/bin/bash
#SBATCH --job-name=ari-experiment
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=64
#SBATCH --time=04:00:00
#SBATCH --output=/abs/path/logs/ari_%j.out
#SBATCH --error=/abs/path/logs/ari_%j.err

# Start Ollama
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

# Set SLURM defaults for sub-jobs
export SLURM_DEFAULT_PARTITION=your_partition
export SLURM_DEFAULT_WORK_DIR=/path/to/ari/

# Run ARI
cd /path/to/ari/ari-core
/home/youruser/miniconda3/bin/ari run \
    /abs/path/to/experiment.md \
    --config /tmp/ari_config.yaml

kill $OLLAMA_PID 2>/dev/null || true
```

## Critical Constraints

| Rule | Detail |
|------|--------|
| Compiler | Use `gcc` only. `mpicc`, `icc`, `aocc` → exit_code=127 |
| CPU limit | `--cpus-per-task` to your partition limit |
| Path expansion | Never use `~` in SBATCH scripts — always absolute paths |
| stdout redirect | Never redirect stdout in job scripts — SLURM captures via `--output` |
| Account header | `--account` and `-A` are invalid on this cluster — never add them |
| Output filename | Must follow pattern: `slurm_job_{JOBID}.out` |

## Available Ollama Models

| Model | Best For |
|-------|---------|
| `qwen3:32b` | Default — best tool calling quality |
| `qwen3:8b` | Faster, lower quality |
| `deepseek-r1:32b` | Reasoning-heavy tasks |
| `gpt-oss:20b` / `gpt-oss:120b` | OpenAI-compatible alternative |
| `qwen2.5vl:32b` | Vision tasks (figures/tables) |
