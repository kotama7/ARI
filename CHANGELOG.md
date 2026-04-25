
## v0.6.0 (2026-04-26)

### Memory (Letta): drop the dead `LETTA_LLM_CONFIG` knob; mock the agent's chat model

`ari-skill-memory` never invokes the Letta agent's chat / messages API
— only `archival_insert` and `archival_search`, both of which use
embeddings. The user-facing "Agent LLM" picker in Settings → Memory
(Letta) was therefore controlling a value that had no runtime effect.

- **Removed**: `letta_llm_config` field on `MemoryConfig`,
  `LETTA_LLM_CONFIG` env propagation in viz / config, the `llm_config`
  key in `workflow.yaml`, the GUI Agent LLM provider/model picker,
  related i18n strings (en/ja/zh), and corresponding doc rows.
- **Hardcoded**: `_SdkLettaAdapter._model` is now fixed to
  `letta/letta-free`. The Letta SDK requires `model=` on
  `agents.create`, so the value still has to be supplied — it just
  isn't operator-configurable anymore.
- **Lock-in tests**: new `ari-skill-memory/tests/test_llm_config_removed.py`
  pins (a) the field is gone from `MemoryConfig`, (b) `load_config`
  ignores `LETTA_LLM_CONFIG`, (c) `_SdkLettaAdapter` always passes the
  fixed mock handle to `agents.create`. Updated `test_settings_propagation.py`
  and `test_settings_roundtrip.py` to assert the env var and GUI table
  are NOT present.

This is a no-op for runtime behavior — embeddings (the only Letta
component ARI actually exercises) are still configured via
`LETTA_EMBEDDING_CONFIG` and the Settings page.


### Paper review: `review_paper` unified (ensemble + Area Chair folded in); `ari-skill-review` removed

The separate `review_paper`, `review_paper_ensemble`, `area_chair_meta_review`,
and `respond_to_review` pipeline stages are collapsed into a single
`review_paper` stage. `review_compiled_paper` now always runs the ensemble
path internally (N=1 is a no-op wrapper around a single reviewer, N>1 also
runs the Area Chair meta-review). The separately enabled ensemble stage was
always N=1 in practice because the GUI-set `ARI_NUM_REVIEWS_ENSEMBLE` was
never read inside the skill; the unified path reads it correctly.

- **Unified output**: `review_report.json` now contains `ensemble_reviews[]`
  and `meta_review{}` inline when N>1. `ensemble_reviews.json` and
  `meta_review.json` are no longer emitted. Frontend rendering is
  unchanged — `ResultsPage` already read these fields from the merged
  payload.
- **N resolution**: explicit `num_reviews_ensemble` arg >
  `$ARI_NUM_REVIEWS_ENSEMBLE` > `rubric.params.num_reviews_ensemble`
  (defaults to 1). Previously the env var was set by CLI/GUI but never
  consumed inside the skill.
- **Removed MCP tools** (from `ari-skill-paper`): `review_compiled_paper_ensemble`,
  `meta_review`. The underlying `run_ensemble` and `run_meta_review` helpers
  remain and are now called from `review_compiled_paper`.
- **Removed skill**: `ari-skill-review` (rebuttal generation) is deleted in
  full. The rebuttal step was not load-bearing for the pipeline — the
  review score is the final quality signal, and a rebuttal to our own
  paper's review added no signal. Associated `ARI_MODEL_REVIEW` env var,
  default-registry entry, and tests are removed. 14 skills → 13 skills
  (12 default + orchestrator).
- **Workflow stages removed** (in `ari-core/config/workflow.yaml`):
  `review_paper_ensemble`, `area_chair_meta_review`, `respond_to_review`.

### Figure skill consolidation: `ari-skill-figure-router` folded into `ari-skill-plot`

`ari-skill-figure-router` was registered as a default skill but never
wired into any pipeline stage, and its matplotlib path duplicated
`ari-skill-plot:generate_figures_llm`. Its one genuinely unique
feature — LLM-generated SVG architecture diagrams — is merged into
`ari-skill-plot`, so all figure generation (data plots + architecture
diagrams) flows through a single skill and the existing VLM review
loop drives both kinds. 15 skills → 14 skills (13 default + orchestrator).

- **New output contract for `plot-skill.generate_figures_llm`**
  - The LLM now returns one JSON array; each element has a per-figure
    `kind` field: `"plot"` (matplotlib Python code) or `"svg"`
    (self-contained SVG markup). Schema:
    ```
    [{"name":"fig_1","kind":"plot","code":"<python>","caption":"..."},
     {"name":"fig_2","kind":"svg", "svg":"<svg>...</svg>", "caption":"..."}]
    ```
  - Matplotlib snippets are executed per-figure in isolated subprocesses
    (previously the skill concatenated all figures into a single
    LLM-written script, so one broken figure killed every output).
    Each snippet receives `output_dir` and `name` pre-defined and must
    save both `<name>.pdf` (dpi=150, LaTeX embedding) and `<name>.png`
    (dpi=200, VLM review). Reassignment of `output_dir` is stripped to
    protect the pipeline contract.
  - SVG snippets are written to `<name>.svg` and rasterised to
    `<name>.pdf` + `<name>.png` via `cairosvg`, with an Inkscape CLI
    fallback for environments without the cairo native library.
    `cairosvg>=2.7` is now a hard dependency of `ari-skill-plot`.
  - Return shape gains `figure_kinds: {name: "plot"|"svg"}` and
    (on partial failure) `errors: [str]`. Existing keys
    `figures: {name: pdf_path}` and `latex_snippets: {name: latex}`
    are preserved byte-compatibly, so `ari-skill-paper` needs no
    changes.
  - On a fully unparseable LLM response, the skill retries once with a
    simpler plot-only instruction before giving up — tighter than the
    previous "execute then fall back" retry and no longer depends on
    stderr parsing.

- **Pipeline integration (no stage changes required)**
  - `ari/pipeline.py`'s `generate_figures` special-case persists the
    new `figure_kinds` dict into `figures_manifest.json`:
    `{figures, latex_snippets, figure_kinds?}`. Empty `figure_kinds`
    is omitted for byte-compatibility with older manifests.
  - `vlm-skill:review_figure` still points at
    `{{checkpoint_dir}}/fig_1.png` — now produced for both kinds — so
    the existing `loop_back_to: generate_figures` +
    `vlm_feedback`-via-user-prompt loop drives SVG regeneration too,
    without touching `workflow.yaml`.
  - `vlm_feedback` is prepended to the figure-generation prompt on
    loop-back exactly as before; the LLM can now address the VLM's
    critique by switching a figure from `kind:"plot"` to
    `kind:"svg"` (e.g. when the reviewer says "this should be a
    pipeline diagram, not a bar chart") within one iteration.

- **Removed**
  - Whole directory `ari-skill-figure-router/` (tools
    `classify_figure_need`, `generate_figure`, `generate_svg_diagram`).
  - `ari-core/tests/test_figure_router.py` (43 static AST checks
    against the deleted source).
  - `figure-router-skill` entry in `ari-core/config/workflow.yaml`
    skills list and in `docs/configuration.md` (en/ja/zh).
  - `figure-router` rows in README.md / README.ja.md / README.zh.md
    and in `docs/architecture.md` + `docs/skills.md` (en/ja/zh).
  - `ari-skill-figure-router` entry from the search roots in
    `tests/test_gui_env_propagation.py`.

- **GUI (Results page)**
  - `ResultsPage.tsx` figure grid was wired for a list-of-objects
    shape that the pipeline never actually wrote (dict), so no
    figures were rendering. The renderer now accepts both shapes:
    dict `{name: path}` is normalised to a list and captions are
    extracted from `latex_snippets` server-side JSON; list entries
    with explicit `caption`/`kind` are still respected.
  - The old `figure_type` badge (`graph` / `architecture` / `table`)
    is replaced with a `kind` badge (`Plot` / `Diagram`) sourced from
    `figure_kinds` in the manifest.
  - The "No results data found" empty state also handles the dict
    manifest shape, so it stops firing when figures exist but are
    stored as a dict.

- **Workflow contract tests**
  - `test_generate_figures_uses_batch_tool` loses its figure-router
    comparison (the comparator skill no longer exists) but still
    asserts `plot-skill` + `generate_figures_llm` own the stage.
  - `test_figure_router_not_in_paper_pipeline` and
    `test_figure_router_still_defined_in_skills` are collapsed into
    a single `test_figure_router_fully_removed` negative test so the
    registration cannot silently come back.
  - `test_skill_mcp_usage_registered_for_unused` drops the
    figure-router branch; `plot-skill` is still asserted as
    `usage="stage"` (pipeline-driven).

- **Design-principle impact**
  - `ari-skill-plot` stays under the existing P2 exception envelope
    ("LLM-writes-code skills may relax P2 as long as the surrounding
    pipeline is deterministic"). SVG rasterisation via `cairosvg`
    is deterministic; inkscape fallback output can vary across
    Inkscape versions but is only exercised when cairosvg is absent.
  - No change to `ari-skill-figure-router` philosophy bullets —
    the skill simply no longer exists.

**Upgrade note**: no checkpoint migration required. Old
`figures_manifest.json` files without `figure_kinds` keep loading
(the key is optional everywhere it's read). Any user `workflow.yaml`
that carried a `figure-router-skill` entry or a stage pointing at
`figure-router-skill:generate_figure` must drop those lines; the
paper pipeline never invoked them, so dropping them is a no-op in
practice.

### Reproducibility ReAct: pipeline-driven `react_driver` replaces the paper-re loop

The reproducibility stage no longer hides a private ReAct loop inside
`ari-skill-paper-re`. The loop is now owned by
`ari-core/ari/agent/react_driver.py` and driven from
`ari-core/ari/pipeline.py` when a stage declares a `react:` block; the
skill has been reduced to two deterministic(-ish) endpoints
(`extract_repro_config`, `build_repro_report`) plus the existing
`extract_metric_from_output` helper. `reproduce_from_paper` is gone.

- **Workflow schema additions**
  - `skills[].phase` now accepts a list (e.g.
    `phase: [paper, reproduce]`). The matching logic in
    `MCPClient.list_tools(phase=…)` treats list and string forms
    uniformly and still honours `"all"` / `"none"`.
  - Stages may declare a `react:` block with
    `agent_phase`, `max_steps`, `final_tool`, `sandbox`,
    `system_prompt`, `user_prompt`, plus sibling fields
    `pre_tool`, `post_tool` on the stage itself.
  - New phase value `reproduce` scopes the MCP tools exposed to the
    reproducibility agent. The default `workflow.yaml` opts
    `web-skill`, `vlm-skill`, `hpc-skill`, and `coding-skill` into
    `reproduce`; `memory-skill`, `transform-skill`, and
    `evaluator-skill` deliberately stay out so the agent cannot reach
    BFTS-phase artefacts (`nodes_tree.json`, ancestor memories, …).
- **Sandbox**
  - The default `reproducibility_check` stage points at
    `{{checkpoint_dir}}/repro_sandbox/` and `react_driver` rejects
    tool calls whose arguments reference absolute paths outside the
    sandbox (plus explicit allow-list entries such as the paper
    `.tex`). `ARI_WORK_DIR` is injected into the MCP server
    environment at spawn so `coding-skill.run_bash` cwds into the
    sandbox by default.
- **GUI (Workflow page)**
  - The Skill Inventory gains a third toggle column, **Reproduce**,
    alongside BFTS / Paper. Internal state is a `Set<phase>` so a
    skill can belong to multiple phases simultaneously; the backend
    `_api_save_skill_phases` endpoint accepts either string or list
    phase payloads.
  - React-driver stages render a read-only summary
    (pre_tool / post_tool / agent_phase / final_tool / max_steps /
    sandbox) in the Node Edit modal instead of the single-tool
    dropdown, so the `react:` block cannot be clobbered from the flow
    editor. The flow round-trip preserves `pre_tool` and `post_tool`
    and leaves the full `react:` block intact via the existing-YAML
    merge path.
- **Tests**
  - New `ari-core/tests/test_react_driver.py` (14 cases) covers sandbox
    path validation, the ReAct loop's final-tool termination, and log
    persistence using stub LLM / MCP clients.
  - New `TestSkillPhaseRoundtrip` suite in
    `test_workflow_contract.py` confirms `_api_save_skill_phases`
    preserves list phases, collapses single-entry lists, and drops
    `none` when other phases are present.
  - `test_pipeline_e2e.py` was updated so the full paper-pipeline e2e
    expects the new `extract_repro_config` / `build_repro_report` MCP
    calls and stubs out `react_driver.run_react` to keep the test
    offline.

### Memory backend: Letta replaces the JSONL store

`ari-skill-memory` is now backed by [Letta](https://docs.letta.com)
(ex-MemGPT). The v0.5.x file-based stores — `memory_store.jsonl` and
`~/.ari/global_memory.jsonl` — are **removed entirely**. A portable
`memory_backup.jsonl.gz` snapshot is written inside each checkpoint so
`cp -r checkpoints/foo /elsewhere/ && ari resume` keeps working.

- **New library**: `ari_skill_memory.backends` exposes a
  `MemoryBackend` ABC with `LettaBackend` (production) and
  `InMemoryBackend` (test-only fake). `server.py` is now a thin
  dispatcher over the library; ari-core's viz and pipeline import the
  same library in-process.
- **New MCP tool**: `get_experiment_context()` returns seeded
  experiment-level facts (goal, primary metric, hardware spec) from
  Letta core memory.
- **Removed MCP tools**: `add_global_memory`, `search_global_memory`,
  `list_global_memory`. Cross-experiment global memory is no longer a
  feature — stable lessons belong in `experiment.md`, code, or prior
  papers.
- **Copy-on-Write**: write-side tools reject `node_id` ≠
  `$ARI_CURRENT_NODE_ID`; Letta self-edit is disabled by default
  (`ARI_MEMORY_LETTA_DISABLE_SELF_EDIT=true`), so ancestor entries are
  byte-stable across siblings.
- **ReAct trace migrated**: `FileMemoryClient` → `LettaMemoryClient`
  (one-line swap at `ari-core/ari/core.py:87`). No more
  `{checkpoint}/memory.json`. Old files are picked up automatically by
  the first-launch auto-migration.
- **Access log**: every write/read emits an event to
  `{checkpoint}/memory_access.jsonl` (rotated at
  `ARI_MEMORY_ACCESS_LOG_MAX_MB`, 100 MB default). Consumed by the
  Tree dashboard `memory_access` API.
- **Pipeline enrichment**: `pipeline.py` injects each node's memory
  into `nodes_tree.json` (bounded by `ARI_TRANSFORM_MEMORY_MAX_ENTRIES`
  and `ARI_TRANSFORM_MEMORY_MAX_CHARS`) so downstream stages
  (transform, paper, EAR) become memory-aware with no per-skill MCP
  call.
- **`ari memory` subcommand**: `migrate` / `backup` / `restore` /
  `start-local` / `stop-local` / `prune-local` / `compact-access` /
  `health`. First-launch auto-migration and on-`ari resume` auto-restore.
- **Deployment**: `scripts/letta/docker-compose.yml` +
  `start_singularity.sh` + `start_pip.sh`, integrated via
  `scripts/setup/install_letta.sh` into `setup.sh`. Auto-detects
  laptop / HPC / container-less environments; honours
  `ARI_MEMORY_BOOTSTRAP_LOCAL_LETTA`.
- **Dashboard**: new **Memory (Letta)** settings card, new
  `/api/memory/{health, detect, start-local, stop-local}` endpoints,
  `/api/checkpoint/{id}/memory_access` for per-node provenance.
- **Design-principle impact**: **P2 relaxed for `ari-skill-memory`**
  (embedding retrieval is not bit-reproducible). **P5 scoped**: BFTS
  *trajectory* may differ across re-runs; numerical metrics still
  reproduce. See `docs/PHILOSOPHY.md`.
- **Observability**: `cost_tracker.CallRecord` gains `component`,
  `op`, `backend`, `embedding_tokens`, `latency_ms` (additive,
  back-compat).
- **Tests**: full new suite under `ari-skill-memory/tests/` exercising
  ancestor scope, CoW, access log, ReAct, backup/restore, checkpoint
  isolation, and the removal of global-memory tools.

**Upgrade note**: running `ari run` / `ari resume` / `ari viz` on a
v0.5.x checkpoint triggers automatic migration. The source JSONL /
JSON files are renamed to `*.migrated-<ts>` (never re-read). Any
`~/.ari/global_memory.jsonl` is detected at startup but not imported —
the entries must be manually promoted to `experiment.md` Rules or
committed code.

### Rubric-driven paper review (AI Scientist v1/v2 compatibility)

The paper review phase is now fully rubric-driven and compatible with
**The AI Scientist** (Nature / arXiv:2408.06292 Appendix A.4) so ARI
outputs can be directly compared with v1/v2.

- **New rubric system** (`ari-core/config/reviewer_rubrics/`): 16
  bundled YAMLs covering ML conferences (`neurips` — default,
  v2-compatible — `iclr`, `icml`, `cvpr`, `acl`), systems/HPC (`sc`,
  `osdi`, `usenix_security`), theory/graphics (`stoc`, `siggraph`),
  HCI/robotics (`chi`, `icra`), and journals/generic (`nature`,
  `journal_generic`, `workshop`, `generic_conference`), plus a
  built-in `legacy` fallback (v0.5 schema). Each declares
  `score_dimensions`, `text_sections`, `decision` rules and execution
  parameters. Add any venue by dropping a YAML — no code changes.
  SHA256 hash computed per rubric for P2 determinism.
- **Rubric loader**: `ari_skill_paper.rubric` validates schema,
  clamps out-of-scale scores, resolves `rubric_id → ARI_RUBRIC env →
  neurips → legacy fallback`.
- **Rubric-driven engine**: `ari_skill_paper.review_engine` builds
  prompts from the rubric, runs a **self-reflection loop** (default 5
  rounds, +2% accuracy per Nature Ablation), loads **few-shot
  examples** (static / dynamic), and normalises output to the rubric
  schema.
- **VLM findings integration**: per-figure VLM feedback (score,
  issues, suggestions) is injected into the review prompt as reviewer
  notes — previously VLM and paper review were parallel & independent.
- **New MCP tools** (`ari-skill-paper`):
  - `review_compiled_paper` — extended with `rubric_id`,
    `vlm_findings_json`, `num_reflections`, `num_fs_examples`
  - `review_compiled_paper_ensemble` — N independent reviewer agents
    with temperature jitter (AI Scientist v1 best config). Disabled by
    default; enable in `workflow.yaml` when variance-reducing
    aggregation is needed (N× cost).
  - `meta_review` — "You are an Area Chair" aggregation of the
    ensemble into a final decision.
  - `list_rubrics` — enumerates available rubrics for the viz API /
    Wizard dropdown.
- **Nature Ablation defaults**: `num_reflections=5`,
  `num_fs_examples=1`, `num_reviews_ensemble=1`, `temperature=0.75`,
  `score_threshold_decision=6` (NeurIPS Weak Accept).
- **Phase 2 dynamic few-shot** (stub + static fallback):
  `fewshot_mode: dynamic` in a rubric triggers OpenReview-based
  similarity retrieval; cache key is
  `sha256(title+abstract+rubric_hash)` for determinism. Falls back to
  static when `openreview-py` is absent or `ARI_STRICT_DYNAMIC` is
  false. SC and CHI force static (reviews closed).
- **CLI**: `ari paper --rubric <id> --fewshot-mode static|dynamic
  --num-reviews-ensemble N --num-reflections N`. Environment variable
  equivalents: `ARI_RUBRIC`, `ARI_FEWSHOT_MODE`,
  `ARI_NUM_REVIEWS_ENSEMBLE`, `ARI_NUM_REFLECTIONS`.
- **Few-shot corpus scripts**: `scripts/fewshot/sync.py` +
  `fetch_openreview.py` + `fetch_arxiv.py` + `manifest.yaml`.
  NeurIPS ships with one synthetic placeholder example; add real
  examples by editing `manifest.yaml` and running `python
  scripts/fewshot/sync.py`.
- **Dashboard**: New Experiment Wizard → "Paper Review" section
  (rubric dropdown dynamically populated from `/api/rubrics`, few-shot
  mode toggle, ensemble size, reflection rounds). Results page
  `renderReviewScores()` now shows NeurIPS-form scores, decision
  badge, strengths / weaknesses / questions / limitations sections,
  issues / recommendations lists, ensemble badges, Area Chair meta-review
  card, and few-shot sources.
- **Few-shot management from the GUI**: the Wizard now ships a
  `FewshotManager` sub-panel that lists existing examples for the
  selected rubric and exposes three actions:
  - **Auto-sync** — runs `scripts/fewshot/sync.py --venue <rubric>`
    server-side to pull the corpus declared in `manifest.yaml`
    (including the three AI Scientist v2 samples from GitHub under
    Apache-2.0).
  - **Upload** — accepts a JSON review form + optional `.txt` excerpt
    + optional PDF (base64). Writes into
    `reviewer_rubrics/fewshot_examples/<rubric>/<id>.*`.
  - **Delete** — removes all sibling files of an example.
  Backed by `GET /api/fewshot/<rubric>`,
  `POST /api/fewshot/<rubric>/sync`,
  `POST /api/fewshot/<rubric>/upload`,
  `POST /api/fewshot/<rubric>/<example>/delete`.
  All endpoints require the rubric to exist in `reviewer_rubrics/`
  (prevents provisioning arbitrary directories via crafted ids) and
  strip `../` / slash characters from inputs.
- **Workflow**: `workflow.yaml` pipes `vlm_review_figures` into
  `review_paper`; new `review_paper_ensemble` and
  `area_chair_meta_review` stages are scaffolded (disabled by default).
- **Breaking change**: `review_compiled_paper` output now follows the
  rubric schema (`scores`, `score_dimensions`, `decision`,
  `rubric_hash`, etc.). Legacy consumers should set
  `ARI_RUBRIC=legacy` or the `--rubric legacy` flag to keep the
  pre-v0.6.0 JSON shape.

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
