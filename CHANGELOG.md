
## v0.4.1 (2026-04-08)

### Homepage & docs
- New dedicated **Demo** section on the homepage with a top-nav link, hero CTA, and an auto-looping dashboard walkthrough video (en/ja/zh)
- Inline **window-style sample paper viewer** on the homepage — scroll through all 11 PDF pages without leaving the page (image-based, avoids browser PDF download prompts)
- New **Prior Work** nav link and `id="inspired"` anchor so the *Inspired By* section (AI Scientist v2 / HPC-AutoResearch / VirSci) is one click away; section title enlarged for visibility
- `docs/movie/{en,ja,zh}/ari_dashboard_demo.mp4` shipped alongside `docs/sample_paper.pdf`; both are referenced from quickstart guides in all three languages
- `docs/docs.html` now embeds the dashboard demo video and links to the sample paper from the *First Run* / *Experiment Monitor* sections

### README
- Added **README language switcher** (`README.md` / `README.ja.md` / `README.zh.md`) with a Languages bar at the top of each
- Embedded the **dashboard demo video** inline via `<video>` raw URLs (works on github.com)
- Added a `<details>` collapsible **scrollable sample paper preview** (11 PNG pages) so the paper can be browsed inside the README itself
- Updated the *Demonstrated Results* table to match the actual sample paper (CSR SpMM / *Stoch-Loopline*: 26.22 GFLOP/s, 105.18 GB/s, +3.53 GFLOP/s prefetch gain on the `fx700` node) — replaces the previous stale stencil-benchmark numbers
- Test count badge bumped from `60 passed` to `1200+` to reflect the current ~1240-test suite

### i18n
- New keys for the Demo section, Prior Work nav, sample-paper viewer captions, and watch-demo CTAs across `en.js` / `ja.js` / `zh.js`
- `i18n.js` now force-`load()` + `play()`s every `<video[autoplay]>` after each `innerHTML` replacement, so language switches and dynamic insertions don't break dashboard auto-loop playback (with timed retries for slow preview iframes)

### Assets
- `docs/images/sample_paper/page-01.png` … `page-11.png` — 110 DPI PNG renders of the sample paper, used by the homepage viewer and the README `<details>` block

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
