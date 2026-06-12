<div align="center">
  <img src="docs/assets/logo.png" alt="ARI Logo" width="200"/>

  # ARI — Autonomous Research Infrastructure

  **A universal research automation system. Laptop to supercomputer. Local models to cloud APIs. Novice to expert. Computation to physical world.**

  [![Tests](https://img.shields.io/badge/tests-2200%2B-brightgreen)](ari-core)
  [![Version](https://img.shields.io/badge/version-v0.9.0-orange)](https://github.com/kotama7/ARI/releases)
  [![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://python.org)
  [![MCP](https://img.shields.io/badge/protocol-MCP-purple)](https://modelcontextprotocol.io)
  [![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
  [![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/SbMzNtYkq)

  **Languages:** **English** · [日本語](README.ja.md) · [中文](README.zh.md)
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

## What's new in v0.9.0 (2026-06-12)

**Verified claims, end to end.** The release theme: a paper ships only when
every claim it makes is machine-verifiable against the run's own artifacts.

- **Story2Proposal claim-evidence loop + idea-owned metric contract** — ideas
  declare falsifiable claims with required evidence names; a deterministic
  hard gate BLOCKS finalize while declared claims lack experiment evidence or
  stated numbers fail recompute. Blocking is reserved for objective
  falsehoods; subjective review findings stay advisory.
- **Mint-once contract & robust parsing** — the contract vocabulary freezes at
  first mint (LLM re-extraction is not referentially stable); the gate parses
  scientific notation and math-delimited units; writer declaration quirks are
  normalized at parse time instead of trusted to instructions.
- **Lineage chaining** — claims whose evidence is *computed* from existing
  measurements (model fitting, held-out validation, model-based selection)
  now run as parent→child node chains over inherited working directories.
- **Review feedback that lands** — every semantic-review warning reaches
  `paper_refine`; the post-refine resolved count is a raw delta, and the
  refiner's whole-document escaping no longer touches math.
- **VirSci-live idea engine (opt-in)** — the real multi-agent VirSci mechanism
  on a live Semantic Scholar snapshot, with platform-aware idea generation
  fed by a run-start capability probe.
- **Gate-verified sample paper** — [`docs/assets/sample_paper.pdf`](docs/assets/sample_paper.pdf)
  is now a study in which all 12 declared claims carried verified evidence
  and zero overclaims remained after refine. See [Demonstrated Results](#demonstrated-results).

See [CHANGELOG.md](CHANGELOG.md) for the full list.

## What's new in v0.8.1 (2026-06-01)

A **behavior-preserving structural refactor** (the full `refactoring/` program,
now retired). No runtime, API, endpoint, MCP-tool, or rendered-output change.

- **Frontend dashboard decomposition** — the six largest React pages were split
  into thin containers + extracted subcomponents/hooks/helpers (no visual
  change). `ResultsPage` 3177 → 462 lines, `DetailPanel` 938 → 425; high-risk
  state extractions were adversarially verified.
- **Stable skill → core contract** — `ari-skill-*` packages depend only on the
  `ari.public.*` surface (new `ari.public.run_env`), enforced by a guard test.
- **viz server seams** — experiment process-control extracted from `routes.py`;
  API ⇄ backend schema pinned by a contract guard; legacy node-tree resolution
  fixed; `.env`-write consolidated into one quote-preserving helper.
- **Docs** — new [`docs/reference/internal_boundaries.md`](docs/reference/internal_boundaries.md)
  (LLM / OS-scheduler-container / two-engine boundaries + concurrency hazards).

See [CHANGELOG.md](CHANGELOG.md#v081--structural-refactor-frontend-decomposition-stable-skill-contract-internal-boundary-docs-2026-06-01) for the full list.

## What's new in v0.8.0 (2026-05-21)

- **PaperBench 3-stage bridge contract** — `rollout_submission` →
  `reproduce_submission` → `judge_submission` exposes vendor PaperBench's
  full Agent Rollout → Reproduction → Grading protocol behind a single
  surface. Drives the dogfood CLI via
  `scripts/sc_paper_dogfood.py --with-rollout / --with-reproduction`.
- **`container_image` end-to-end** — one field flows wizard → API worker →
  MCP tool → sandbox runner, with `pb-env` / `pb-reproducer` aliases
  resolved by `scripts/build_pb_images.sh`.
- **Fail-loud preconditions** — sandbox / GPU mismatches now raise
  actionable `RuntimeError`s by default (four silent-downgrade sites
  fixed); legacy fallbacks behind `ARI_PHASE1_ALLOW_FALLBACK=1` and
  `ARI_SLURM_ALLOW_NO_GRES=1`.
- **PaperBench env-truth** — Stage 1 prompts now probe-before-scaffold,
  counter-prime the language choice, and inject a host-truthful
  `ADDITIONAL NOTES` block (binaries / GPU / network / Phase-2 isolation).
- **Configurable BFTS evaluation layers** — `evaluator.composite`,
  `evaluator.axis_mode`, `bfts.frontier_score`, `bfts.select_prompt`,
  `bfts.expand_select_prompt`. Defaults reproduce the prior behaviour
  exactly; see `docs/reference/configuration.md` § BFTS Evaluation Layers.
- **Seven new reviewer rubrics** — `aer`, `ahr`, `apsr`, `econometrica`,
  `philreview`, `pmla`, `qje` ship under `ari-core/config/reviewer_rubrics/`.
- **Step 4 reproduction-package generator — RETRACTED.** The earlier
  audit score of 0.857 on the SC24 paper is retracted; the legitimate
  path is the bridge contract above.

See [CHANGELOG.md](CHANGELOG.md#v080--paperbench-env-truth--bridge-contract--bfts-configurable-evaluation-2026-05-21) for the full release notes.

---

## See It in Action

<p align="center">
  <video src="https://github.com/kotama7/ARI/raw/main/docs/assets/movie/en/ari_dashboard_demo.mp4" controls width="720" muted playsinline>
    Your browser does not support inline video. <a href="docs/assets/movie/en/ari_dashboard_demo.mp4">Download the demo</a>.
  </video>
</p>

🎬 **Dashboard demo video** — full walkthrough of the ARI web dashboard. Also available in [日本語](docs/assets/movie/ja/ari_dashboard_demo.mp4) · [中文](docs/assets/movie/zh/ari_dashboard_demo.mp4).

📄 **[Sample output paper (PDF)](docs/assets/sample_paper.pdf)** — a real 8-page paper autonomously generated by ARI on an aarch64 (SVE) HPC platform: a CSR SpMM study with store-policy selection across RHS widths and a loopline-guided performance model — every declared claim machine-verified by the claim-evidence gate before release. See [Demonstrated Results](#demonstrated-results).

<details>
<summary><b>📖 Click to read the sample paper inline (scroll through all 10 pages)</b></summary>

<p align="center">
  <img src="docs/assets/images/sample_paper/page-01.png" alt="Sample paper — page 1" width="720"/>
  <img src="docs/assets/images/sample_paper/page-02.png" alt="Sample paper — page 2" width="720"/>
  <img src="docs/assets/images/sample_paper/page-03.png" alt="Sample paper — page 3" width="720"/>
  <img src="docs/assets/images/sample_paper/page-04.png" alt="Sample paper — page 4" width="720"/>
  <img src="docs/assets/images/sample_paper/page-05.png" alt="Sample paper — page 5" width="720"/>
  <img src="docs/assets/images/sample_paper/page-06.png" alt="Sample paper — page 6" width="720"/>
  <img src="docs/assets/images/sample_paper/page-07.png" alt="Sample paper — page 7" width="720"/>
  <img src="docs/assets/images/sample_paper/page-08.png" alt="Sample paper — page 8" width="720"/>
</p>

</details>

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
4. **From paper to proof.** ARI writes the paper *and* verifies its own claims twice over: a deterministic claim-evidence / metric-correctness gate re-derives every reported number from the recorded results and blocks objectively-false or unverified metrics, *and* an independent reproducibility check re-runs the experiment.

---

## Designed for Extension — Into the Physical World

ARI's MCP plugin architecture is intentionally designed to grow beyond computation:

```
Today (computational):
  ari-skill-hpc        → SLURM job submission
  ari-skill-evaluator  → metric extraction from stdout
  ari-skill-paper      → LaTeX paper writing
  ari-skill-vlm        → VLM figure/table quality review
  ari-skill-web        → pluggable retrieval (Semantic Scholar + AlphaXiv)

Tomorrow (physical world):
  ari-skill-robot      → robot arm control via ROS2 MCP bridge
  ari-skill-sensor     → temperature/pressure sensor readout
  ari-skill-labware    → pipette control, plate reader integration
  ari-skill-camera     → computer vision experiment observation
```

Adding any of these requires **no changes to ari-core**. Write a `server.py` with `@mcp.tool()` functions, register it in `workflow.yaml` — done.

---

## Quick Start

```bash
# 1. Install
git clone https://github.com/kotama7/ARI && cd ARI
bash setup.sh

# 2. Set up AI model (choose one)
ollama pull qwen3:8b                          # free, local
export ARI_BACKEND=openai OPENAI_API_KEY=sk-… # or cloud API

# 3. Launch all services (Letta + ari-registry + GUI on :8765)
./start.sh
# Open http://localhost:8765 → use the Experiment Wizard to create and launch experiments
# Tear down with: ./shutdown.sh
```

Or run directly from the CLI:
```bash
ari run experiment.md                 # run experiment
ari run experiment.md --profile hpc   # with SLURM cluster
```

See **[docs/getting-started/quickstart.md](docs/getting-started/quickstart.md)** for the full dashboard walkthrough and **[docs/reference/cli_reference.md](docs/reference/cli_reference.md)** for CLI commands.

---

## Experiment Files — Two Levels

**Novice (3 lines):**
```markdown
# Matrix Multiply Optimization
## Research Goal
Maximize GFLOPS of DGEMM on this machine.
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
<!-- min_expected_metric: 50000 -->
```
```

---

## Web Dashboard (Primary Interface)

A 10-page React/TypeScript SPA for visual experiment management. Launch with:

```bash
./start.sh             # Letta + ari-registry + GUI on http://localhost:8765
./start.sh gui         # (re)start only the GUI
./start.sh status      # show which services are up
./shutdown.sh          # stop everything (reaps apptainer orphans too)
```

| Page | Features |
|------|----------|
| **Home** | Quick actions, recent experiments, system status |
| **New Experiment** | 4-step wizard: Chat/Write/Upload goal → Scope (depth, nodes, workers, recursion) → Resources (LLM, HPC, container, **Paper Review** rubric / few-shot manager / ensemble size / reflection rounds) → Launch |
| **Experiments** | List/delete/resume all checkpoint projects with status and review scores |
| **Monitor** | Real-time phase stepper (Idle → Idea → BFTS → Paper → Review), live log streaming (SSE), cost tracking |
| **Tree** | Interactive BFTS node tree, click any node to inspect metrics, tool-call trace, generated code, and output |
| **Results** | Overleaf-like LaTeX editor (edit/compile/preview), paper PDF viewer, review report, reproducibility results, EAR browser |
| **Ideas** | VirSci-generated hypotheses with novelty/feasibility scores and gap analysis |
| **Workflow** | React Flow visual DAG editor for pipeline stages, with `BFTS / Paper / Reproduce` phase toggles per skill |
| **Settings** | LLM provider/model, API keys, SLURM, container runtime, VLM review model, retrieval backend, Ollama host, **Memory (Letta)** backend |
| **Sub-Experiments** | Recursive sub-experiment tree with parent-child tracking (via orchestrator skill) |

Real-time updates via WebSocket (tree changes) and SSE (log streaming). All data is per-project isolated.

### Dashboard API

The dashboard exposes a REST + WebSocket API that can also be used programmatically:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/state` | GET | Full experiment state (phase, nodes, config, cost) |
| `/api/launch` | POST | Launch new experiment with full config |
| `/api/run-stage` | POST | Run specific stage (resume / paper / review) |
| `/api/checkpoints` | GET | List all checkpoint projects |
| `/api/settings` | GET/POST | Read/write LLM, SLURM, container, and API key settings |
| `/api/workflow` | GET/POST | Read/write workflow.yaml pipeline |
| `/api/workflow/flow` | GET/POST | React Flow graph representation of workflow |
| `/api/chat-goal` | POST | Multi-turn LLM chat for experiment goal refinement |
| `/api/upload` | POST | Upload experiment.md or data files |
| `/api/upload/delete` | POST | Delete an uploaded file |
| `/api/stop` | POST | Gracefully stop running experiment |
| `/api/logs` | GET (SSE) | Stream real-time logs and cost data |
| `/api/checkpoint/{id}/files` | GET | List files in paper directory |
| `/api/checkpoint/{id}/file` | GET/POST | Read/save paper files |
| `/api/checkpoint/compile` | POST | Trigger LaTeX compilation |
| `/api/checkpoint/{id}/filetree` | GET | Full checkpoint directory tree |
| `/api/ear/{run_id}` | GET | Experiment Artifact Repository contents |
| `/api/sub-experiments` | GET/POST | List/launch recursive sub-experiments |
| `/api/rubrics` | GET | List bundled review rubrics (Wizard dropdown) |
| `/api/fewshot/<rubric>` | GET | List few-shot review examples for a rubric |
| `/api/fewshot/<rubric>/{sync,upload,delete}` | POST | Sync from manifest, upload one example, delete one |
| `/api/memory/{health,detect,start-local,stop-local,restart}` | GET/POST | Letta backend admin |
| `/api/checkpoint/{id}/memory_access` | GET | Per-node memory write/read provenance log |
| `/memory/<node_id>` | GET | Retrieve node memory (tool-call trace) |
| `ws://host:{port+1}/ws` | WebSocket | Subscribe to real-time tree updates |

---

## CLI Commands

All dashboard features are also available via the command line:

| Command | Description |
|---------|-------------|
| `ari run <experiment.md>` | Run a new experiment (BFTS + paper pipeline) |
| `ari resume <checkpoint_dir>` | Resume from checkpoint |
| `ari paper <checkpoint_dir>` | Run paper pipeline only (skip BFTS) |
| `ari status <checkpoint_dir>` | Show node tree and summary |
| `ari projects` | List all experiment runs |
| `ari show <checkpoint>` | Detailed results (tree + review report) |
| `ari delete <checkpoint>` | Delete a checkpoint |
| `ari settings` | View/modify config (model, partition, etc.) |
| `ari skills-list` | List all available MCP tools |
| `ari memory <subcmd>` | Manage Letta memory (`migrate` / `backup` / `restore` / `start-local` / `stop-local` / `prune-local` / `compact-access` / `health`) |
| `ari viz <checkpoint_dir>` | Launch web dashboard |

### Output Files

After a run completes, outputs are saved in `./checkpoints/<run_id>/`:

| File | Description |
|------|-------------|
| `tree.json` | Full BFTS node tree (all nodes, metrics, parent-child links) |
| `results.json` | Per-node artifacts, metrics, and status |
| `idea.json` | VirSci-generated hypotheses and gap analysis |
| `science_data.json` | Science-facing data (no internal BFTS terms) |
| `full_paper.tex` / `.pdf` | Generated LaTeX paper and compiled PDF |
| `review_report.json` | Rubric-driven peer review (AI Scientist v1/v2-compatible). Single reviewer by default; `ARI_NUM_REVIEWS_ENSEMBLE>1` adds `ensemble_reviews[]` + Area Chair `meta_review{}` inline. |
| `reproducibility_report.json` | Independent reproducibility verification (sandboxed `react_driver` over MCP `phase: reproduce` skills) |
| `figures_manifest.json` | Generated figure paths and captions |
| `ear/` | Experiment Artifact Repository (code, data, logs, reproducibility metadata) |
| `cost_trace.jsonl` | Per-call LLM cost tracking |
| `experiments/<slug>/<node_id>/` | Per-node work directories and generated code |

---


## Architecture

### Skills (MCP plugin servers)

13 skills total. 12 are registered by default in `workflow.yaml`; 1 additional skill (orchestrator) can be enabled by adding it to the config.

In v0.6.0 two skills were retired: `ari-skill-figure-router` was folded into `ari-skill-plot` (a single skill now owns both matplotlib plots and SVG architecture diagrams, both feeding the same VLM review loop), and `ari-skill-review` (rebuttal generation) was deleted — the rubric-driven review score is the final quality signal.

| Skill | Role | LLM? | Default |
|---|---|---|---|
| `ari-skill-hpc` | SLURM submit / poll / Singularity / bash | ✗ | ✓ |
| `ari-skill-evaluator` | Metric extraction from experiment file | △ | ✓ |
| `ari-skill-idea` | arXiv survey + VirSci hypothesis generation | ✓ | ✓ |
| `ari-skill-web` | DuckDuckGo, arXiv, Semantic Scholar / AlphaXiv, iterative citation, uploaded file access | △ | ✓ |
| `ari-skill-memory` | Ancestor-scoped node memory + typed, artifact-provenanced verifiable research memory (Letta-backed) | △ | ✓ |
| `ari-skill-transform` | BFTS tree → science-facing data + EAR generation | ✓ | ✓ |
| `ari-skill-plot` | Unified figure generation (matplotlib plots + SVG diagrams per-figure, VLM-loop aware) | ✓ | ✓ |
| `ari-skill-paper` | LaTeX writing + BibTeX + rubric-driven review (single or N-reviewer ensemble + Area Chair meta) | ✓ | ✓ |
| `ari-skill-paper-re` | ReAct reproducibility verification | ✓ | ✓ |
| `ari-skill-benchmark` | CSV/JSON analysis, plotting, statistical tests | ✗ | ✓ |
| `ari-skill-vlm` | Vision-Language model figure/table review | ✓ | ✓ |
| `ari-skill-coding` | Code generation + execution + file read + bash | ✗ | ✓ |
| `ari-skill-orchestrator` | Expose ARI as MCP server, recursive sub-experiments, dual stdio+HTTP transport | ✗ | — |

✗ = no LLM, △ = LLM used in some tools only, ✓ = primary tools use LLM.

> **Optional VirSci-live engine.** `ari-skill-idea` can optionally run VirSci's real multi-agent mechanism (freshness team formation + multi-agent deliberation) on a live Semantic Scholar snapshot instead of the lightweight re-implemented loop. Opt in with `ARI_IDEA_VIRSCI_REAL=1` (or `ari run … --virsci-live`, or the experiment-wizard toggle); default OFF leaves behaviour unchanged, and it degrades to the re-impl loop if deps are missing.

### Design Principles

| # | Principle | Meaning |
|---|-----------|---------|
| P1 | Domain-agnostic core | `ari-core` has zero experiment-specific knowledge |
| P2 | Deterministic where possible | MCP tools are deterministic by default; LLM-using tools are explicitly annotated. *Relaxed for `ari-skill-memory` in v0.6.0 — Letta-backed retrieval is embedding-based.* |
| P3 | Multi-objective metrics | No hardcoded scalar score |
| P4 | Dependency injection | Switching experiments = editing `.md` only |
| P5 | Reproducibility-first | Papers describe hardware by specs, not cluster names. *BFTS trajectory may diverge across re-runs when memory is Letta-backed; numerical results remain reproducible.* See `docs/concepts/PHILOSOPHY.md`. |

---

## Demonstrated Results

ARI autonomously designed, implemented, ran, and wrote up an end-to-end study of **CSR SpMM** (sparse matrix–dense matrix multiplication) on an aarch64 (SVE) HPC platform. The full paper — methodology, algorithms, figures, and references — is available in [`docs/assets/sample_paper.pdf`](docs/assets/sample_paper.pdf).

> **CSR Sparse-Dense Matrix Multiplication on CPUs with RHS-Width Robustness and a Loopline-Guided Performance Model**

What makes this paper different is not a headline number but a property: **every claim it makes passed a deterministic claim-evidence gate before release**.

| Verified property | Result |
|---|---|
| Declared falsifiable claims with experiment evidence | **12 / 12** (gate errors: 0) |
| Correctness vs an independent dense FP32 reference | max abs error **6.79×10⁻⁶** |
| Computed-evidence chain (model fitting → held-out validation → model-based selection) | executed via lineage-chained tree nodes |
| Overclaims remaining after the review→refine loop | **0** (5 detected, 5 resolved) |
| Numbers stated without artifact grounding | explicitly hedged in the text |

**Hardware:** an aarch64 (SVE) HPC compute node (48 OpenMP threads, FP32), with an x86_64 node used for ablation probes. Hardware is described by specs, never by cluster names (Philosophy P5).

**What ARI produced autonomously:** the CSR SpMM kernels with a store-policy selector (regular vs non-temporal stores across RHS widths), the correctness validation against a dense reference, microbenchmark probes (memory bandwidth, compute-rate inflation/deflation), a loopline-guided performance-model fitting and held-out validation chain executed across parent→child tree nodes, the figures, the references, and the machine-checked claim-evidence audit — all without human intervention.

---

## Star History

<a href="https://www.star-history.com/#kotama7/ARI&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=kotama7/ARI&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=kotama7/ARI&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=kotama7/ARI&type=Date" />
 </picture>
</a>

---

## License

MIT. See [LICENSE](LICENSE).

