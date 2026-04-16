
## v0.5.0 (2026-04-15)

### Project-scoped settings & memory (no more ~/.ari/)

ARI no longer maintains a global directory under `~/.ari/`.  Every
configuration and memory file now lives under the active checkpoint, so
each experiment is fully isolated and `~/.ari/` can be safely removed.

- `PathManager.project_settings_path(ckpt)` / `project_memory_path(ckpt)` —
  per-experiment paths.  Removed `ari_home()`, `settings_path()`,
  `memory_path()`, `global_settings_path()`.
- `viz/state.set_active_checkpoint(path)` rebinds `_settings_path` to
  `{checkpoint}/settings.json`; passing `None` clears it.
- `_api_save_settings` now refuses to write when no project is selected
  (returns 400 instead of touching `~/.ari/`).
- `core.build_runtime` requires `checkpoint_dir`; agent memory always
  goes to `{checkpoint}/memory.json`.
- `ari-skill-memory` requires `ARI_CHECKPOINT_DIR` (or explicit
  `ARI_MEMORY_PATH`); raises on startup otherwise.  Stores entries at
  `{checkpoint}/memory_store.jsonl`.
- `scripts/gpu_ollama_monitor.sh` updates `ollama_host` only via the GUI
  API; no on-disk fallback file.
- `viz/server.py` `/memory/{node_id}` reads only from the active
  checkpoint's store.
- Docs (en/ja/zh) updated to describe per-checkpoint storage.

### Container Support
- Docker / Singularity / Apptainer auto-detection via `detect_runtime()` (prefers Singularity/Apptainer on HPC when `SLURM_JOB_ID` is set)
- New `container:` section in `workflow.yaml` with `mode` (auto/docker/singularity/apptainer/none), `image`, and `pull` (always/on_start/never) fields
- CLI reads container config at startup, detects runtime, and optionally pulls the image
- Settings page: new Container card with mode/image/pull-policy fields and "Detect Runtime" button
- Wizard StepResources: container image selection dropdown, mode picker, and "Pull new image" form

### Experiment Artifact Repository (EAR)
- New `generate_ear` MCP tool in `ari-skill-transform` builds a structured repository under `<checkpoint>/ear/` with README, code, data, logs, and reproducibility metadata
- New pipeline stage `generate_ear` in `workflow.yaml` runs after `transform_data`
- API endpoint `GET /api/ear/{run_id}` returns EAR contents

### Overleaf-like LaTeX Editor (Results Page)
- File browser sidebar listing all files in `checkpoint/paper/` directory
- Text editor for `.tex`, `.bib`, `.sty`, `.cls` files with save support
- File upload/delete management within the paper directory
- LaTeX compilation (`pdflatex -> bibtex -> pdflatex -> pdflatex`) triggered from the GUI with compile log display
- Inline PDF viewer for the compiled paper
- New API endpoints: `GET /api/checkpoint/{id}/files`, `GET/POST /api/checkpoint/{id}/file`, `POST /api/checkpoint/compile`, etc.

### VLM Figure Review Loop
- New pipeline stage `vlm_review_figures` uses `vlm-skill:review_figure` to visually review generated figures
- `loop_back_to` mechanism in `pipeline.py`: when VLM score < `loop_threshold` (0.7), the pipeline rewinds to `generate_figures` with VLM feedback injected via `{{vlm_feedback}}`
- `loop_max_iterations` (default 2) caps regeneration attempts
- `vlm_review_model` setting (default: `openai/gpt-4o`) in Settings page and Wizard

### Pluggable Retrieval Backend (AlphaXiv)
- `ARI_RETRIEVAL_BACKEND` env var: `"semantic_scholar"` (default), `"alphaxiv"`, or `"both"` (parallel with deduplication)
- New `search_papers()` and `set_retrieval_backend()` tools in `ari-skill-web`
- New `retrieval:` section in `workflow.yaml` with `backend` and `alphaxiv_endpoint`
- Settings page: retrieval backend radio buttons

### React Flow Visual Workflow Editor
- WorkflowPage completely rewritten using React Flow with draggable DAG nodes and edges
- Custom `PhaseNode` component showing skill name, tool, available tools, and enable/disable toggle
- Swim-lane layout: BFTS stages on top, Paper stages below
- New `api_workflow.py` module with `workflow_yaml_to_flow()` / `flow_to_workflow_yaml()` converters

### Recursive Sub-Experiments (Orchestrator)
- `run_experiment` tool now supports `parent_run_id`, `recursion_depth`, and `max_recursion_depth` parameters
- New `list_children` tool returns child runs of a parent
- Dual transport: stdio (MCP for Claude Desktop) + HTTP (REST + SSE on `ARI_ORCHESTRATOR_PORT`, default 9890)
- GUI: `GET /api/sub-experiments`, `POST /api/sub-experiments/launch`
- Wizard StepScope: `maxRecursionDepth` field

### Review/Rebuttal Pipeline Stage
- New `respond_to_review` stage: `review-skill:generate_rebuttal` parses review comments and generates a rebuttal
- Outputs `rebuttal.json` in the checkpoint directory

### Benchmark/Analysis Pipeline Stage (BFTS)
- New `analyze_results` BFTS stage: `benchmark-skill:analyze_results` runs statistical analysis and significance tests before frontier expansion

### BFTS Improvements
- `expand()` now generates exactly **one child per call** (callers re-expand with `existing_children` to avoid duplicates)
- Expand prompt includes rich context: sibling scores, ancestor chain, tree diversity metrics, already-spawned children
- New `NodeLabel.OTHER` for LLM-invented labels; `raw_label` preserved in JSON
- **Diversity bonus**: `+0.05` for underrepresented labels in `select_next_node()` (last 20 runs tracked)
- **Score calibration**: `_score_history` (up to 15 recent scores) injected into evaluation prompt to prevent score collapse
- Frontier nodes are no longer removed when expanded — stay available for re-expansion with `_touched_this_round` / `_failed_this_round` tracking
- Plan B file copy: all user files from checkpoint dir copied into each node's `work_dir`

### Skills — New & Updated
- **New default skills registered**: `figure-router-skill`, `benchmark-skill`, `review-skill`, `vlm-skill`, `coding-skill` (total 15 skills, 14 default)
- **ari-skill-coding**: new `read_file` tool with `offset`/`limit` for paginated reads; `run_code`/`run_bash` output truncation with informative markers
- **ari-skill-web**: new `search_papers`, `set_retrieval_backend`, `list_uploaded_files`, `read_uploaded_file` tools
- **ari-skill-transform**: new `generate_ear` tool for Experiment Artifact Repository
- **ari-skill-orchestrator**: recursive sub-experiments, dual stdio+HTTP transport, `list_children` tool

### Dynamic MCP Tool Discovery
- `enrich_hints_from_mcp(hints, mcp_tools)` enriches WorkflowHints with dynamically discovered MCP tools after `MCPClient.list_tools(phase="bfts")`
- Grouped "AVAILABLE TOOLS" descriptions injected into the LLM system prompt

### Dashboard API Additions
- Checkpoint file tree: `GET /api/checkpoint/{id}/filetree`, `GET /api/checkpoint/{id}/filecontent`
- Paper editor: file CRUD, compile, raw file serving with proper MIME types (PDF, PNG, JPEG, SVG, EPS) and 20MB limit
- Upload management: `POST /api/upload/delete`, staging directory under `~/.ari/staging/`
- Auto-append uploaded files to `## Provided Files` section (English/Japanese/Chinese headers)
- SLURM CPU auto-detection on launch via `sinfo -p <partition>`

### Agent Loop Enhancements
- System prompt now lists files already present in `work_dir` ("Provided files (ready to use): ...")
- `_args_preview` truncation increased from 500 to 4000 chars
- Chinese `提供文件` section header support for provided files detection
- `ARI_SLURM_CPUS` environment variable fallback

### Tests
- `test_workflow_contract.py`: comprehensive workflow contract tests (867 lines)
- Updated tests across BFTS, child node workflow, GUI errors, server, pipeline, and more

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
