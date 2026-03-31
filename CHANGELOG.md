
## v0.4.0 (2026-03-31)

### GUI Dashboard
- Full 9-page React/TypeScript SPA dashboard built with Vite (`ari/viz/frontend/`)
  - Home, Experiments, Live Monitor, Tree + Code Viewer, Results + Paper, Experiment Wizard, VirSci Ideas, Workflow Editor, Settings
- Modular backend API: `api_experiment.py`, `api_state.py`, `api_settings.py`, `api_ollama.py`, `api_tools.py`, `api_wizard.py`
- Real-time experiment log streaming via Server-Sent Events (SSE)
- WebSocket for live state updates to connected clients
- CORS preflight support for SSH tunnels and reverse proxies
- Production build served from `ari/viz/static/dist/`

### Environment Auto-Detection & Profiles
- New `ari/env_detect.py`: auto-detects scheduler (SLURM, PBS, LSF, SGE, Kubernetes), container runtime (Docker, Singularity, Apptainer), and SLURM partitions
- Three configuration profiles: `laptop.yaml`, `hpc.yaml`, `cloud.yaml`
- Activated via CLI: `ari run experiment.md --profile hpc`

### CLI Expansion
- `ari projects` — list all checkpoint directories with status
- `ari show <checkpoint>` — display node tree and review report
- `ari delete <checkpoint>` — remove a project with confirmation
- `ari settings` — view/modify config (model, API keys, scheduler params)
- Intelligent run ID generation: `YYYYMMDDHHMMSS_<semantic_slug>` (LLM-generated or content-derived)

### Configuration
- Per-phase model overrides (`ARI_MODEL_IDEA`, `ARI_MODEL_CODING`, etc.)
- `phase` field in `SkillConfig` for controlling when skills run
- Backend determination from `ARI_BACKEND` env var (no model-name guessing)
- Settings persistence to `~/.ari/settings.json`

### Process Management
- PID file management (`ari/pidfile.py`)
- Process group termination via `os.killpg()` with SIGTERM
- Background checkpoint directory watcher

### Skills
- All skills now have `skill.yaml` metadata files
- Skill server updates across all modules for improved MCP compatibility

### Docs & i18n
- Full internationalization: English, Japanese, Chinese across homepage and docs
- `docs/cli_reference.md`: complete CLI command reference
- Homepage updated with dashboard highlight, environment profiles, extended quick start
- Dashboard screenshots for all languages (`docs/images/en/`, `ja/`, `zh/`)
- `docs/quickstart.md`: rewritten with dashboard-first onboarding

### Tests
- 12+ new test files covering CLI, dashboard API, state management, settings, i18n, pipeline, wizard, cost tracker, and more

### Infrastructure
- `scripts/gpu_ollama_monitor.sh`, `scripts/run_ollama_gpu.sh`: GPU/Ollama monitoring
- `scripts/setup/`: modular setup scripts
- `requirements.txt` added
- Cost tracking improvements (`ari/cost_tracker.py`)

## v0.3.0 (2026-03-21)

### Philosophy
- Removed all domain-specific keywords from production code (`_PERF_KEYWORDS`, `OMP_NUM_THREADS` regex, compiler flag regex)
- Node ranking now uses LLM-assigned `scientific_score` (0.0–1.0) instead of HPC performance keywords
- BFTS expansion prompt passes `scientific_score` to child LLM — LLM autonomously determines how to improve

### Evaluator
- `LLMEvaluator` now acts as peer reviewer: assigns `scientific_score` and `comparison_found`
- LLM decides scoring criteria and weights autonomously (no fixed rubric)
- `_scientific_score` and `_comparison_found` stored in node metrics for BFTS ranking

### Transform Skill (ari-skill-transform)
- Replaced regex-based parameter extraction with LLM-powered full tree analysis
- BFS traversal: all nodes (root → ablation → validation) passed to LLM
- LLM decides what fields to extract (hardware, methodology, findings, etc.)
- `experiment_context` included in `science_data.json` for downstream skills

### Plot Skill (ari-skill-plot)
- Receives full `science_data` including `experiment_context`
- Figure types chosen autonomously by LLM based on available data
- Real metric units from data (no "a.u.")

### Pipeline
- `paper_context` = `experiment_context` (from transform) + `best_nodes_metrics`
- `search_memory` query uses node's own eval_summary (not hardcoded HPC keywords)
- `eval_summary` now includes `scientific_score` for child node context

### Docs
- `architecture.md`: updated data flow, design invariants table
- `PHILOSOPHY.md`: added Zero Domain Knowledge Principle section
- `configuration.md`: updated for `ARI_MAX_NODES`, template variables
- `index.html`: added Analyze step, bumped to v0.3.0
