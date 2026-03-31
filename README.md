<div align="center">
  <img src="docs/logo.png" alt="ARI Logo" width="200"/>

  # ARI — Artificial Research Intelligence

  **A universal research automation system. Laptop to supercomputer. Local models to cloud APIs. Novice to expert. Computation to physical world.**

  [![Tests](https://img.shields.io/badge/tests-60%20passed-brightgreen)](./ari-core)
  [![Version](https://img.shields.io/badge/version-v0.4.0-orange)](https://github.com/kotama7/ARI/releases)
  [![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
  [![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io)
  [![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
  [![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/SbMzNtYkq)
</div>

---

## Vision

Research automation should not require a supercomputer, a cloud budget, or an engineering team.

ARI is designed around one principle: **describe the goal in plain Markdown — ARI handles the rest.**

- A student with a laptop and a local LLM can run their first autonomous experiment in 10 minutes.
- A researcher with HPC cluster access can run 50-node parallel hypothesis searches overnight.
- A team can extend ARI to control lab hardware, robotics, or IoT sensors by adding a single MCP skill — without touching the core.

The system scales across five axes:

| Axis | Minimal | Full |
|------|---------|------|
| **Compute** | Laptop (local process) | Supercomputer (SLURM cluster) |
| **LLM** | Local Ollama (qwen3:8b) | Commercial API (GPT-5, Claude) |
| **Experiment spec** | 3-line `.md` | Detailed SLURM scripts + rules |
| **Domain** | Computational benchmarks | Physical world (robotics, sensors, lab) |
| **Expertise** | Novice (goal only) | Expert (full parameter control) |

---

## What ARI Does

```
experiment.md  ──►  ARI Core  ──►  results + paper + reproducibility report
                       │
          ┌────────────┼──────────────────────────────┐
          │            │                              │
     BFTS Engine    ReAct Loop            Post-BFTS Pipeline
   (best-first     (per-node agent)    (workflow.yaml driven)
    tree search)         │
                    MCP Skill Servers
                    (plugin system — add any capability here)
```

1. **You describe the goal.** Write an experiment file. ARI reads it, generates hypotheses, runs experiments, and reports results.
2. **BFTS over hypothesis space.** Best-First Tree Search guides exploration — evidence-driven, not exhaustive.
3. **Deterministic tools, reasoning LLM.** MCP skills are pure functions. The LLM reasons; skills act.
4. **From paper to proof.** ARI writes the paper *and* verifies its own claims via reproducibility check.

---

## Designed for Extension — Into the Physical World

ARI's MCP plugin architecture is intentionally designed to grow beyond computation:

```
Today (computational):
  ari-skill-hpc        → SLURM job submission
  ari-skill-evaluator  → metric extraction from stdout
  ari-skill-paper      → LaTeX paper writing

Tomorrow (physical world):
  ari-skill-robot      → robot arm control via ROS2 MCP bridge
  ari-skill-sensor     → temperature/pressure sensor readout
  ari-skill-labware    → pipette control, plate reader integration
  ari-skill-camera     → computer vision experiment observation
```

Adding any of these requires **no changes to ari-core**. Write a `server.py` with `@mcp.tool()` functions, register it in `workflow.yaml` — done.

---

## Quick Start

**Minimal (laptop + local Ollama):**
```bash
git clone https://github.com/kotama7/ARI && cd ari
bash setup.sh
ollama pull qwen3:8b
ari run experiment.md
```

**With HPC (SLURM cluster):**
```bash
export ARI_BACKEND=openai
export OPENAI_API_KEY=sk-...
ari run experiment.md --profile hpc
```

**Dashboard & CLI:**
```bash
ari viz ./checkpoints/my_run/   # launch web dashboard
ari projects                     # list all runs
ari settings                     # view/modify config
```

See **[docs/quickstart.md](docs/quickstart.md)** for full setup.

---

## Experiment Files — Two Levels

**Novice (3 lines):**
```markdown
# Matrix Multiply Optimization
## Research Goal
Maximize GFLOPS of DGEMM on this machine.
<!-- metric_keyword: GFLOPS -->
```

**Expert (full control):**
```markdown
# Protein Folding Force Field Sweep
## Research Goal
Minimize energy score across AMBER force field variants.
## SLURM Script Template
```bash
#!/bin/bash
#SBATCH --nodes=4 --ntasks-per-node=32 --time=02:00:00
module load gromacs/2024
gmx mdrun -v -deffnm simulation -ntmpi 32
```
## Rules
- HARD LIMIT: never exceed 128 MPI tasks
- Always use work_dir=/abs/path in slurm_submit
<!-- metric_keyword: energy_score -->
<!-- min_expected_metric: -500 -->
```
```

---

## Web Dashboard

A 9-page React/TypeScript SPA lets you control experiments from the browser:

```bash
ari viz ./checkpoints/my_run/ --port 8765
```

Home, Experiments, Live Monitor, Tree + Code Viewer, Results + Paper, Experiment Wizard, VirSci Ideas, Workflow Editor, Settings — all in one interface. Real-time log streaming via SSE and WebSocket.

---


## Architecture

### Skills (MCP plugin servers)

| Skill | Role | LLM? |
|---|---|---|
| `ari-skill-hpc` | SLURM submit / poll / read output | ✗ |
| `ari-skill-evaluator` | Metric extraction from stdout | ✗ |
| `ari-skill-idea` | arXiv survey, hypothesis generation | ✗ |
| `ari-skill-web` | DuckDuckGo, page fetch, arXiv | ✗ |
| `ari-skill-memory` | Ancestor-scoped node memory | ✗ |
| `ari-skill-transform` | LLM-powered tree analysis and data extraction | ✗ |
| `ari-skill-plot` | Figure generation | ✓* |
| `ari-skill-paper` | LaTeX writing + BibTeX + review | ✓* |
| `ari-skill-paper-re` | ReAct reproducibility verification | ✓* |

\* LLM exception — explicitly annotated. All others are deterministic.

### Design Principles

| # | Principle | Meaning |
|---|-----------|---------|
| P1 | Domain-agnostic core | `ari-core` has zero experiment-specific knowledge |
| P2 | Deterministic skills | MCP tools never call LLM (3 annotated exceptions) |
| P3 | Multi-objective metrics | No hardcoded scalar score |
| P4 | Dependency injection | Switching experiments = editing `.md` only |
| P5 | Reproducibility-first | Papers describe hardware by specs, not cluster names |

---

## Demonstrated Results

ARI autonomously discovered optimal compiler flags for a stencil benchmark:

| Configuration | MFLOPS | Notes |
|---|---|---|
| Baseline (1 thread, -O2) | ~64,662 | Starting point |
| **Best found by ARI** | **277,573** | -O3 -ffast-math -march=native, 64 threads |
| Speedup | **4.3×** | Fully autonomous |

---

## License

MIT. See [LICENSE](./LICENSE).

