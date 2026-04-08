# ARI CLI Reference

Complete reference for ARI command-line operations. The CLI provides the same functionality as the [web dashboard](quickstart.md) for terminal-based workflows.

---

## Commands Overview

| Command | Description | Dashboard Equivalent |
|---------|-------------|---------------------|
| `ari run` | Run a new experiment | New Experiment wizard → Launch |
| `ari resume` | Resume an interrupted experiment | Experiments page → Resume button |
| `ari paper` | Generate paper only (skip experiments) | `POST /api/run-stage {stage: "paper"}` |
| `ari status` | Show experiment tree and summary | Monitor / Tree page |
| `ari viz` | Launch the web dashboard | — |
| `ari projects` | List all past experiments | Experiments page |
| `ari show` | Show detailed results for a run | Results page |
| `ari delete` | Delete a checkpoint | Experiments page → Delete button |
| `ari settings` | View or modify configuration | Settings page |
| `ari skills-list` | List available tools | Settings → MCP Skills |

---

## ari run

Run a new experiment from an experiment Markdown file.

```bash
ari run <experiment.md> [--config <config.yaml>] [--profile <profile>]
```

| Argument | Required | Description |
|----------|----------|-------------|
| `experiment.md` | Yes | Path to experiment Markdown file |
| `--config` | No | Custom config YAML (auto-generated if omitted) |
| `--profile` | No | Environment profile: `laptop`, `hpc`, or `cloud` |

**Examples:**

```bash
# Basic run (auto-detects configuration)
ari run experiment.md

# With environment profile
ari run experiment.md --profile laptop

# With custom config
ari run experiment.md --config ari-core/config/workflow.yaml

# With environment variable overrides
ARI_MAX_NODES=10 ARI_PARALLEL=2 ari run experiment.md
```

**What happens:**

1. ARI generates a unique project name (LLM-generated title)
2. Creates checkpoint directory: `./checkpoints/<run_id>/`
3. Searches related papers on arXiv and Semantic Scholar
4. Generates hypotheses via VirSci multi-agent deliberation
5. Runs Best-First Tree Search (BFTS) experiments
6. Evaluates results with LLM peer review
7. Writes a LaTeX paper with figures and citations
8. Verifies reproducibility independently

---

## ari resume

Resume an interrupted experiment from its checkpoint.

```bash
ari resume <checkpoint_dir> [--config <config.yaml>]
```

**Example:**

```bash
ari resume ./checkpoints/20260328_matrix_opt/
```

Loads the saved tree, identifies pending/failed nodes, and continues from where it stopped.

---

## ari paper

Generate the paper without running experiments. Useful when experiments are already complete.

```bash
ari paper <checkpoint_dir> [--experiment <experiment.md>] [--config <config.yaml>]
```

**Example:**

```bash
ari paper ./checkpoints/20260328_matrix_opt/
```

Runs the post-BFTS pipeline: data transformation, figure generation, paper writing, review, and reproducibility check.

---

## ari status

Display the experiment tree and summary statistics.

```bash
ari status <checkpoint_dir>
```

**Example:**

```bash
ari status ./checkpoints/20260328_matrix_opt/

# Output:
# ── Experiment Tree ──
# root (success) score=153736
# ├── improve_1 (success) score=180200
# │   ├── ablation_1 (success) score=120000
# │   └── validation_1 (success) score=178500
# └── draft_2 (failed)
#
# Summary: 4 success, 1 failed, 0 running, 0 pending
```

---

## ari viz

Launch the web dashboard for visual experiment management.

```bash
ari viz <checkpoint_dir> [--port <port>]
```

| Argument | Default | Description |
|----------|---------|-------------|
| `checkpoint_dir` | (required) | Checkpoint directory to monitor |
| `--port` | 8765 | Port to serve on |

**Examples:**

```bash
# Start dashboard
ari viz ./checkpoints/ --port 8765

# Monitor a specific run
ari viz ./checkpoints/20260328_matrix_opt/ --port 9878
```

Open `http://localhost:<port>` in your browser. See the [QuickStart Guide](quickstart.md) for dashboard usage.

---

## ari projects

List all past experiment runs.

```bash
ari projects [--checkpoints <dir>]
```

**Example:**

```bash
ari projects

# Output:
# ID                              Nodes  Status    Best Score  Modified
# 20260328_matrix_opt             28     complete  153736      2h ago
# 20260327_sorting_benchmark      12     complete  0.95        1d ago
# 20260326_sample_experiment           5      failed    --          2d ago
```

---

## ari show

Show detailed results for a specific experiment.

```bash
ari show <checkpoint> [--checkpoints-dir <dir>]
```

Displays the experiment tree, review report summary, and list of artifacts.

---

## ari delete

Delete a checkpoint directory.

```bash
ari delete <checkpoint> [--yes]
```

| Flag | Description |
|------|-------------|
| `-y` / `--yes` | Skip confirmation prompt |

---

## ari settings

View or modify ARI configuration.

```bash
ari settings [--config <config.yaml>] [options]
```

| Option | Description |
|--------|-------------|
| `--model <name>` | Set LLM model name |
| `--api-key <key>` | Set API key |
| `--partition <name>` | Set SLURM partition |
| `--cpus <count>` | Set CPU count |
| `--mem <GB>` | Set memory in GB |

**Examples:**

```bash
# View current settings
ari settings

# Change model
ari settings --model gpt-4o

# Set multiple options
ari settings --model qwen3:32b --partition gpu --cpus 64 --mem 128
```

---

## ari skills-list

List all available MCP tools and their descriptions.

```bash
ari skills-list [--config <config.yaml>]
```

---

## Environment Variables

### Core Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_BACKEND` | LLM backend (`ollama` / `openai` / `anthropic` / `claude`) | `ollama` |
| `ARI_MODEL` | Model name | `qwen3:8b` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OLLAMA_HOST` | Ollama server URL | `http://localhost:11434` |
| `LLM_API_BASE` | Generic API base URL (fallback) | — |

### BFTS Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_MAX_NODES` | Maximum total experiments | 50 |
| `ARI_MAX_DEPTH` | Maximum tree depth | 5 |
| `ARI_PARALLEL` | Concurrent experiments | 4 |
| `ARI_MAX_REACT` | Max ReAct steps per node | 80 |
| `ARI_TIMEOUT_NODE` | Timeout per node (seconds) | 7200 |

### HPC Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `ARI_EXECUTOR` | Execution backend (`local` / `slurm` / `pbs` / `lsf`) | `local` |
| `ARI_SLURM_PARTITION` | SLURM partition name | — |

### Per-Phase Model Overrides

| Variable | Phase |
|----------|-------|
| `ARI_MODEL_IDEA` | Idea generation |
| `ARI_MODEL_BFTS` | BFTS experiments |
| `ARI_MODEL_PAPER` | Paper writing |
| `ARI_MODEL_REVIEW` | Paper review |

### .env File

ARI loads `.env` files automatically (checked in order):

1. `<checkpoint_dir>/.env` (highest priority)
2. `<project_root>/.env`
3. `<project_root>/ari-core/.env`
4. `~/.env` (lowest priority)

Format: `KEY=VALUE` (lines starting with `#` are ignored).

---

## Running on HPC (SLURM)

```bash
# Set executor
export ARI_EXECUTOR=slurm
export ARI_SLURM_PARTITION=your_partition

# Submit as a SLURM job
sbatch << 'EOF'
#!/bin/bash
#SBATCH --job-name=ari
#SBATCH --partition=your_partition
#SBATCH --nodes=1
#SBATCH --cpus-per-task=32
#SBATCH --time=04:00:00
#SBATCH --output=ari_%j.out

# If using Ollama on a GPU node:
ollama serve &
sleep 10

export ARI_BACKEND=ollama
export ARI_MODEL=qwen3:32b

cd /path/to/ARI
ari run /path/to/experiment.md --profile hpc
EOF
```

**Important rules:**

- Always use absolute paths (not `~` or relative paths)
- Never redirect stdout in SLURM scripts (SLURM captures it via `--output`)
- Never add `--account` or `-A` flags unless your cluster requires them
