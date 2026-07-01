# 001 — Current Architecture Report

> Planning artifact for the ARI refactoring initiative. **Planning only — no runtime code, imports, prompts, configs, workflows, frontend, or directory names are modified by this document.** Every claim below is grounded in verified inspection of the repository at `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`, planning date 2026-07-01).
>
> **Classification vocabulary** (from the master prompt): `KEEP`, `ADAPT`, `MERGE`, `MOVE_TO_LEGACY`, `DELETE_CANDIDATE`, `REVIEW_REQUIRED`. The word "deprecated" is reserved here for **external contracts only** (public API, CLI, MCP tools, dashboard API, documented import paths, ari-skill stable interfaces).
>
> **Contracts that must not be broken** in any later implementation phase without a compatibility-adapter note: the `ari` CLI console script and its command/flag surface, `ari.public.*`, the 14 MCP `ari-skill-*` tool contracts, the dashboard HTTP/WS API + `services/api.ts` schema, checkpoint/output/config file formats, the `ari-skill-* → ari-core` stable interface (`ari.public.*`), README/docs usage, and scripts invoked by `.github/workflows/`.

---

## 1. Top-Level Structure

Repository root: `/home/t-kotama/workplace/ARI`. There is **no top-level `pyproject.toml`**; the core manifest is `ari-core/pyproject.toml` (44 lines, hatchling backend, `name = "ari-core"`, `version = "0.9.0"`, `requires-python = ">=3.9"`, wheel `packages = ["ari"]`). There is **no `sonfigs/` directory anywhere** in the tree (`find -iname '*sonfig*'` returns nothing); the "sonfigs" token in some planning prompts is a hypothesized typo that does **not** exist in the repo. State this explicitly wherever the config trio is discussed.

Top-level directories:

| Path | Role | Classification |
|---|---|---|
| `ari-core/` | Python core framework (package `ari`, console script `ari`), version 0.9.0 | KEEP |
| `ari-skill-*/` (14 packages) | MCP skill servers: benchmark, coding, evaluator, hpc, idea, memory, orchestrator, paper, paper-re, plot, replicate, transform, vlm, web | KEEP |
| `docs/` | VitePress documentation site (i18n: en root + `ja/` + `zh/`), `.vitepress/` config + theme | KEEP |
| `docs/refactoring/` | Planning workspace (`reports/`, `subtasks/` — both currently empty); **not** part of the published VitePress IA | KEEP (planning) |
| `report/` | Separate LaTeX/HTML report build tree (en/ja/zh chapters, `shared/`, `scripts/`, `html/`) | KEEP |
| `scripts/` | Shell + Python tooling: `docs/` checkers, `setup/`, `letta/`, `registry/`, `git-hooks/`, `fewshot/` | KEEP |
| `.github/workflows/` | 5 workflows only; no `ISSUE_TEMPLATE/`, no `PULL_REQUEST_TEMPLATE.md`, no `dependabot.yml`, no `CODEOWNERS`, no `.github/actions/` | KEEP / see §21 |
| `checkpoints/` | Root-level checkpoint dir — empty on disk, appears legacy; coexists with `workspace/checkpoints/` | MOVE_TO_LEGACY (candidate) / REVIEW_REQUIRED |
| `workspace/` | Runtime output: `checkpoints/<ts_slug>/`, `experiments/<ts_slug>/`, `staging/<ts>/`, plus `bundle.tar.gz` | KEEP (git-ignored) |
| `containers/` | Container build assets | KEEP |

Root files: `README.md`, `README.ja.md`, `README.zh.md`, `CHANGELOG.md` (~129 KB), `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `pytest.ini`, `requirements.txt`, `requirements.lock`, `setup.sh`, `start.sh`, `shutdown.sh`, `.env`, `.gitmodules`, `.gitignore`, `HPC_PaperBench_Final_Proposal_for_Professors.pdf`.

**Measured baseline.** `ari-core/ari` production code = **30,277 LOC** (`*.py`, excl. `__pycache__`); the 14 skill `src` trees ≈ **25.5k LOC**. `viz/` alone is **8,131 LOC** (27% of core). `public/` — the frozen contract surface — is only **148 LOC**. Tooling on this machine: **ruff 0.15.2 installed; radon NOT installed; Python 3.13.2**; `ruff check ari-core --statistics` → **661 findings, 341 of them `F401` unused-import**; no cyclomatic-complexity data exists today (ruff McCabe `C901` not enabled, radon absent).

---

## 2. ari-core Structure

`ari-core/ari/` (package `ari`). `ari/__init__.py` is **empty (0 bytes)** — no exports, no `__version__`; the version lives only in the manifest. Recursively verified subpackage `*.py` counts (excl. `__pycache__`):

| Subpackage | py | LOC | Notable files (LOC) | Classification |
|---|---|---|---|---|
| `viz/` | 27 | 8,131 | `routes.py` 1197, `api_experiment.py` 929, `api_paperbench.py` 813; `frontend/` (React+TS) | ADAPT (§16–18) |
| `pipeline/` | 17 | 3,900 | `orchestrator.py` 913; `claim_gate/` (9 files), `stage_runner.py`, `yaml_loader.py`, `context_builder.py`, `verified_context.py`, `stage_control.py`, `experiment_md.py` | ADAPT (§7) |
| `agent/` | 9 | 3,303 | `loop.py` 1630 (ReAct); `react_driver.py` 442 (second ReAct); `tool_manager.py`, `guidance.py`, `message_utils.py`, `metric_contract.py`, `workflow.py`, `run_env.py` | ADAPT (§6) |
| `orchestrator/` | 10 | 2,996 | `bfts.py` 845; `node.py`, `node_selection.py`, `lineage_decision.py` 593, `root_idea_selector.py`, `web_provenance.py`, `node_report/{builder 652,legacy_reconstruct}` | ADAPT (§5) |
| `cli/` | 8 | 2,582 | `bfts_loop.py` 911, `run.py` 575, `commands.py`, `projects.py`, `lineage.py`, `migrate.py`, `__init__.py` 175, `__main__.py` | ADAPT (§15) |
| `clone/` | 7 | 665 | `__init__.py` (`clone`, `_safe_extract_tar`), `resolvers/` | KEEP |
| `publish/` | 6 | 756 | `__init__.py` (`_load_backend`), `backends/{ari_registry 213,local_tarball 48,zenodo 139,gh 134}` | KEEP |
| `memory/` | 6 | 343 | `client.py` (ABC), `letta_client.py`, `file_client.py`, `local_client.py`, `auto_migrate.py` | ADAPT (§11) |
| `registry/` | 5 | 511 | HTTP artifact registry: `app.py`, `storage.py`, `auth.py`, `cli.py` (**not** a DI registry — §24 registry block) | KEEP |
| `migrations/` | 5 | 170 | `v05_to_v07/{legacy_axes,memory,node_reports}.py` | KEEP |
| `llm/` | 4 | 1,234 | `client.py` 26+ (`LLMClient`), `routing.py`, `cli_server.py` 919 (OpenAI-compat shim) | ADAPT (§9) |
| `evaluator/` | 3 | 1,261 | `llm_evaluator.py` 723, `dynamic_axes.py` 516 | ADAPT (§10) |
| `public/` | 9 | 148 | STABLE PUBLIC API (§14) | KEEP (contract) |
| `mcp/` | 2 | 495 | `client.py` 484 (`MCPClient`) | ADAPT (§8) |
| `config/` | 2 | 773 | `finder.py` 145, `__init__.py` 628 (Pydantic + env overrides) | ADAPT (§13) |
| `configs/` | 2 | 69 | `_loader.py` + packaged `defaults.yaml`, `model_prices.yaml` | KEEP (§13) |
| `protocols/` | 2 | 63 | `evaluator.py` (Protocol), `__init__.py` | KEEP |
| `prompts/` | 2 | 61 | `_loader.py`, `__init__.py` + `.md` templates | KEEP (§19) |
| `schemas/` | 1 | 20 | `__init__.py` + `node_report.schema.json`, `publish.schema.json` | REVIEW_REQUIRED (§24) |

Top-level `.py` (2,796 LOC total): `checkpoint.py` (197), `paths.py` (303), `container.py` (481), `cost_tracker.py` (448), `core.py` (282), `lineage.py` (250), `cli_ear.py`, `memory_cli.py`, `env_detect.py`, `pidfile.py`, `_deprecation.py`, `__init__.py` (empty).

---

## 3. ari-skill-* Structure

14 MCP skill servers, each `ari-skill-<name>/src/server.py`. **Not** on PyPI; launched by filesystem path (`python <skill>/src/server.py`), not console scripts (only `paper-re` and `replicate` declare `[project.scripts] = "server:main"`, and both are **unused by the loader** — inconsistent bare `server:` module ref). Two divergent server idioms (a refactor hazard with different return shapes):

- **FastMCP** (`mcp = FastMCP(...)`, `@mcp.tool()`, `mcp.run()`): benchmark, idea, memory, paper, paper-re, plot, replicate, transform, vlm, web.
- **Low-level `mcp.server.Server`** (`@server.list_tools()`/`@server.call_tool()`, `stdio_server`, returns `list[TextContent(...)]`): coding, evaluator, hpc, orchestrator.

| Skill | `server.py` LOC | Framework | ari-core touchpoint |
|---|---|---|---|
| benchmark | 175 | FastMCP | none |
| coding | 644 | Server | `ari.public.claim_gate`, `ari.public.container` (fallback `ari.container`), `ari.public.run_env` (fallback `ari.agent.run_env`) |
| evaluator | 983 | Server | `ari.public.claim_gate`, cost_tracker |
| hpc | 304 (+`slurm.py`, `singularity.py`) | Server | `ari.public.run_env` (fallback `ari.agent.run_env`) |
| idea | 775 (+ vendored VirSci at `vendor/virsci/`) | FastMCP | cost_tracker; **boundary violation** `from ari.lineage import…` (server.py:614) |
| memory | 238 (dispatcher over `ari_skill_memory/`) | FastMCP | inverse edge (§below) |
| orchestrator | 1043 (**no `pyproject.toml`**, only `src/requirements.txt`) | Server | — |
| paper | **2956 (largest file in repo)** (+`claim_links.py`, `review_engine.py`, `rubric.py`) | FastMCP | `ari.public.verified_context.render_grounded_block` |
| paper-re | 1395 (+ `_paperbench_bridge.py` 2376, `_replicator_agent.py` 730) | FastMCP | cost_tracker; **boundary violation** `from ari.clone import clone, CloneError` (server.py:146) |
| plot | 802 | FastMCP | cost_tracker |
| replicate | 194 (+ generator/auditor) | FastMCP | cost_tracker |
| transform | **2465 (2nd largest)** (+`claims.py`, `curate.py`) | FastMCP | **boundary violations** `ari.orchestrator.node_selection` (681/2083), `ari.publish.{publish,promote}` (2433/2451); public `ari.public.claim_gate.scan_science_data` |
| vlm | 355 | FastMCP | cost_tracker |
| web | 712 | FastMCP | cost_tracker |

**ari-skill → ari-core contract** is lazy, optional, unpinned: no skill lists `ari-core` in its `dependencies`; every touch is an in-function `try/except ImportError`. Near-universal touchpoint: `from ari.public import cost_tracker`. Sanctioned surface consumed: `claim_gate`, `container` + `run_env`, `verified_context`, `cost_tracker`. **Four confirmed boundary violations** import private ari-core modules: paper-re→`ari.clone`, idea→`ari.lineage`, transform→`ari.orchestrator`+`ari.publish` (classify REVIEW_REQUIRED; candidate `check_import_boundaries.py` would flag these — do not implement now).

**Inverse edge (core → skill).** `ari_skill_memory.backends.get_backend` is imported at **~13 core sites** (`memory_cli.py:49`, `cli/run.py:537`, `cli/commands.py:129`, `pipeline/orchestrator.py:250`, `pipeline/verified_context.py:74/76`, `agent/loop.py:1047`, `viz/{checkpoint_lifecycle,api_memory,routes,node_work_api}.py`, `memory/{letta_client,auto_migrate}.py`). Documented at `ari-core/pyproject.toml:27` but deliberately omitted from `dependencies` (editable-installed by `setup.sh`). Coupling is bidirectional: `ari-skill-memory/.../letta_backend.py:157` lazily imports `ari.public.cost_tracker`.

**Drift/hygiene (skills).** Manifest triplication & version skew (paper-re = 0.8.0 pyproject / 0.4.0 mcp.json / 0.5.0 skill.yaml; evaluator 1.0.0 vs skill.yaml 0.4.1; replicate 0.2.0 vs mcp.json 0.1.0). `mcp.json` tool lists are stale (memory advertises 4 but has 15 `@mcp.tool`; web 5 vs 9; paper 12 vs 14; coding/hpc/vlm/orchestrator list `[]`; transform has **no `mcp.json`**). `requires-python` fragmented (3.10 / 3.11 / 3.13 across skills). Two heavy vendored submodules: paper-re `vendor/paperbench/` (openai/preparedness monorepo, injected via `_vendor_path.py`, **no local fallback** — KEEP_INLINE) and idea `vendor/virsci/`.

---

## 4. Core Execution Flow

Composition root: `ari/core.py::build_runtime` (L83–222) wires `LLMClient`(s), `MemoryClient`, `MCPClient`, `BFTS`, `AgentLoop`, `LLMEvaluator`. `core.py` also mixes in rubric-YAML loading (`_load_rubric_dict_for_axes` L23–55), a generic metric extractor (`_make_metric_spec` L62–76), and pipeline dispatch (`generate_paper_section` L235–283 with `print`/path resolution) — composition tangled with domain logic (ADAPT).

End-to-end sequence:

1. **CLI entry** — `ari run <experiment>` (`cli/run.py:168`) generates `run_id = {strftime %Y%m%d%H%M%S}_{slug}` (`run.py:322-323`), pins `ARI_CHECKPOINT_DIR`, and calls into the BFTS driver. If launched from the GUI with `ARI_CHECKPOINT_DIR` already set, the existing dir name is adopted as `run_id` (`run.py:280-283`).
2. **BFTS search loop** — `cli/bfts_loop.py::_run_loop` (L85–837) is the orchestrator glue: a `ThreadPoolExecutor` over `agent.run`, driven by `BFTS.select_best_to_expand` / `expand` / `should_prune` / `select_next_node`. It also owns workspace file-copy, sterile detection, node_report/checkpoint writes, and lineage hooks (concern-mixing — §5).
3. **Per-node ReAct** — `agent/loop.py::AgentLoop.run` (L459–1630, one ~1170-line method) executes Thought→Action→Observation over MCP tools until terminal JSON or step exhaustion (§6).
4. **Evaluation** — `evaluator/llm_evaluator.py::LLMEvaluator` scores each finished node on multi-axis LLM-judge criteria (§10).
5. **BFTS sanity gate** — `pipeline/orchestrator.py:505-537` aborts before paper stages if no node has `has_real_data`, unless `ARI_FORCE_PAPER=1`.
6. **Post-BFTS pipeline** — `core.py:235 generate_paper_section` → `pipeline/orchestrator.py:280 run_pipeline` drives the YAML-defined stage list to produce the paper + reproducibility artifacts (§7).

---

## 5. BFTS Engine

### Component block — BFTS

- **Current files.** `ari/orchestrator/bfts.py` (845 LOC, class `BFTS`); supporting `orchestrator/node.py`, `orchestrator/node_selection.py`, `orchestrator/node_report/{builder.py 652, legacy_reconstruct.py, __init__.py}`, `orchestrator/root_idea_selector.py`, `orchestrator/lineage_decision.py` (593). Prompt templates externalized to `ari/prompts/orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`.
- **Current responsibility.** The *search strategy*: which node to run/expand next. Public methods `select_next_node` (L418), `select_best_to_expand` (L520), `should_prune` (L498, hard cutoffs), `expand` (L577, generates ≤1 child), deterministic fallbacks `_fallback_score`/`_select_fallback` (L322–369), diversity accounting `record_run`/`diversity_bonus`/`expansion_count` (L267–319). BFTS is *itself an LLM caller* (planner/judge role): `self.llm.complete` at L485, L564, L762.
- **Inbound dependencies.** Constructed only by `core.py::build_runtime` (L102); methods invoked by `cli/bfts_loop.py::_run_loop`.
- **Outbound dependencies.** `ari.config.BFTSConfig`, `ari.llm.client`, `ari.memory.client` (`memory.search` at L446), `ari.orchestrator.node`, `ari.paths.PathManager`, `ari.prompts.FilesystemPromptLoader`, and the filesystem (`node_report.json`).
- **Runtime role.** Ranking/selection engine driving the search tree; consumes node reports, produces expansion directions.
- **Public contract.** None external — internal to the engine. No `ari.public.*` symbol exposes BFTS.
- **Observed problems.** Strategy tangled with I/O, prompt-building, parsing, and memory: heavy inline context serialization in `expand` (L604–760: sci_note/depth_note/budget_note + sibling/ancestor/existing-children/diversity blocks), candidate descriptions (L451–470, L537–550); direct `node_report.json` reads via `_resolve_pm_and_run_id` (L43), `_format_parent_report_block` (L64–108), cached `_get_node_report` (L372–404), `_load_sibling_node_reports` (L406) — coupling BFTS to `ari.paths` and the filesystem; response parsing `_extract_directions_json` (L145–201).
- **Likely refactoring direction (ADAPT).** Extract a `BFTSPromptBuilder` (context serialization L604–760 + candidate descriptions) leaving BFTS as pure ranking/selection; introduce an injected `NodeReport` repository behind an interface to remove the filesystem/`ari.paths` coupling (L43–416). No contract break — internal only.
- **Related subtasks.** BFTSStrategy purity; NodeReport repository; prompt-builder extraction (§24).

---

## 6. ReAct Loop

### Component block — ReAct (AgentLoop)

- **Current files.** `ari/agent/loop.py` (**1630 LOC**, `AgentLoop.run` L459–1630). Partial extractions already present: `agent/tool_manager.py`, `agent/guidance.py`, `agent/message_utils.py`, `agent/metric_contract.py`, `agent/workflow.py`, `agent/run_env.py`, and a **second, cleaner generic ReAct loop** `agent/react_driver.py` (442 LOC).
- **Current responsibility.** ReAct executor for a single node: Thought→Action→Observation over MCP tools until terminal JSON or step exhaustion. `run` is one ~1170-line method.
- **Inbound dependencies.** `core.py::build_runtime` (L93); invoked by `cli/bfts_loop.py::_run_loop`.
- **Outbound dependencies.** `ari.agent.{workflow,tool_manager,guidance,metric_contract,message_utils}`, `ari.llm.client` (LLM call at L837), `ari.mcp.client`, `ari.memory.client`, `ari.orchestrator.node`, `ari.prompts`, plus **cross-layer** reach into `ari_skill_memory.backends` (L1047) and `ari.pipeline._extract_plan_sections` (L1061, L1118).
- **Runtime role.** The per-node worker that actually executes tools and produces artifacts, trace logs, memory writes, and the node evaluation.
- **Public contract.** None external.
- **Observed problems.** Everything in one method despite the "no domain-specific knowledge" docstring: system-prompt assembly (L489–554), root/child user_content (L570–621), module-level `build_working_context_messages` (L164–355), window management (`_build_safe_window` L725–805, `repair_tool_message_order` L113–155), file I/O (writes `idea.json` L1015–1016; reads `metric_contract.json`/`platform_capabilities.json` L228–290, `experiment.md` L1051), **duplicated** `evaluator.evaluate_sync` at L1454/1532/1600, memory writes scattered at L921/960/1480/1549/1567/1615 (5 near-identical "RESULT SUMMARY" blocks), trace saving (L899–912, `_notify_progress`→tree.json flush L439–457), and a giant domain-specific tool router `if r["name"] == ...` (L950–1318: survey, generate_ideas, make_metric_spec, emit_results, job_status, run_bash). **A second ReAct implementation** exists in `agent/react_driver.py` (used by pipeline stages at `pipeline/stage_runner.py:143`) — duplicated ReAct logic.
- **Likely refactoring direction (ADAPT + MERGE).** Decompose `AgentLoop.run` into a `PromptAssembler` (L489–621), a `MessageWindow` (already partial), a `ToolResultRouter` (L950–1318), and a `NodeEvaluationPersister` deduping the 3 `evaluate_sync` and 5 memory-summary blocks. **MERGE** the two ReAct implementations (`agent/loop.py` vs `agent/react_driver.py`) into one generic driver. Internal only — no contract break.
- **Related subtasks.** AgentLoop decomposition; unify ReAct implementations; dedupe evaluate/memory blocks (§24).

---

## 7. Post-BFTS Pipeline

### Component block — Pipeline

- **Current files.** `ari/pipeline/orchestrator.py` (**913 LOC**, `run_pipeline` L548–911); `pipeline/yaml_loader.py` (`load_pipeline` L29, `load_disabled_stage_names` L43, `_resolve_templates` L84); `pipeline/stage_runner.py` (`_run_stage_subprocess` L331, `_run_react_stage` L51); `pipeline/stage_control.py`, `pipeline/context_builder.py`, `pipeline/experiment_md.py`, `pipeline/verified_context.py`, `pipeline/claim_gate/` (9 files: `gate`, `contract`, `formula_eval`, `invariants`, `latex`, `numeric`, `policy`, `resolve`, `__init__`). Stage definitions live in the DATA file `ari-core/config/workflow.yaml` (~629 LOC, ~30 stages).
- **Current responsibility.** Drive the paper-generation + reproducibility (ORS) workflow after BFTS. **100% data-driven from YAML — no stage classes exist.** A "stage" is a plain `dict`; execution is a single imperative `while`-loop (`run_pipeline` L548-911).
- **Inbound dependencies.** `core.py:235 generate_paper_section` → `run_pipeline` (L280). Also a **duplicate** pipeline driver in `viz/api_paperbench_worker.py:168 _run_pipeline` (thread L313).
- **Outbound dependencies.** MCP tools (default: subprocess per stage via `sys.executable -c` with string-concatenated scripts, `stage_runner.py:367-404`); `ari.clone.clone` (react path pre-fetch L203); `ari_skill_memory.backends` (L250); hardwired filenames (`nodes_tree.json`, `science_data.json`, `full_paper.tex`, `publish_record.json`, `manifest.lock`, `meta.json`, `ear_published/`).
- **Runtime role.** Sequences ~30 stages across four bands: BFTS/idea, paper generation, publish/finalize, reproducibility (ORS: `ors_generate_rubric` → `ors_seed_sandbox`/`ors_build_reproduce`/`ors_run_reproduce` → `ors_grade`).
- **Public contract.** `workflow.yaml` stage schema and the hardwired output filenames are effectively a **file-format contract** consumed by the dashboard and downstream tools (ADAPT with care).
- **Observed problems.** The 913-LOC god-function hand-rolls per stage: `disabled_tools` skip (L561), `depends_on` (L571-601), `skip_if_exists` (L604-625), template resolution (L627-653, regex `{{var}}` — **not Jinja**), tool-specific fallback injection (L655-680, hardcoded `_paper_tools`/`_metrics_tools`), dispatch (L682-733), output persistence with **type-sniffing side-effects** (`.tex`→`result["latex"]`, `.pdf`→copy-if-distinct, L757-801), a special-cased `generate_figures` manifest branch (L814-826), and `loop_back_to` cursor rewind with VLM feedback (L831-901). No stage abstraction, no registry, no state object — `tpl_vars`/`stage_outputs` threaded manually. The **ReAct stage path is dormant in the default config** (`grep -c 'react:' config/workflow.yaml == 0` — confirmed); exercised only by tests / per-checkpoint YAML. Config-discovery duplicated across `core.py:252-259`, `orchestrator.py:328-336`, `cli/lineage.py:57-60`. `_promote_plan_to_experiment_md` mutates checkpoint `experiment.md` mid-pipeline (L394). Lazy-delegator monkeypatch-stabilizer anti-pattern at `orchestrator.py:42-56`, `cli/run.py:41`, `cli/projects.py:39`. `clone/` and `publish/` are clean self-contained packages by contrast.
- **Likely refactoring direction (ADAPT).** Introduce `BasePipelineStage` (`resolve_inputs`/`should_skip`/`run`/`persist_outputs`/`evaluate_loopback`) with `SubprocessMCPStage`/`ReActStage` subclasses; a `BaseWorkflowDriver` owning the `_stage_idx` loop + pre-flight, collapsing `run_pipeline` and `viz/api_paperbench_worker._run_pipeline`; a `StageContext` value object; a single `WorkflowLocator` for the 3+ duplicated `workflow.yaml` discovery sites; an `OutputSink`/path registry to remove hardcoded filenames.
- **Related subtasks.** Stage abstraction; workflow-driver unification; workflow.yaml locator; output-path registry (§24).

---

## 8. MCP Skill Integration

Client: `ari/mcp/client.py` (484 LOC, class `MCPClient`, public per `ari/mcp/__init__.py`). stdio transport, per-skill connection pooling, `MAX_RETRIES=3`. Discovery `list_tools()` → `[{name, description, inputSchema, skill_name}]`; `call_tool()` returns a **`{"result": <text>}` or `{"error": ...}`** envelope (a hard contract). Timeouts tiered: `DEFAULT_TOOL_TIMEOUT=300`, `SLOW=3600`, `VERY_SLOW=13h`. `to_claude_mcp_config()` emits fully-qualified `mcp__<skill>__<tool>` names for the Claude CLI subprocess.

**Observed problems.** Tool names are bare snake_case in **one flat namespace** (`make_metric_spec`, `generate_ideas`, `add_memory`, `build_reproduce_sh`, …). `MCPClient._tool_registry` maps `tool_name → skill.name` globally, so **cross-skill name collisions silently clobber (last skill wins)** — REVIEW_REQUIRED. Two divergent server idioms (§3) yield different return shapes.

**Public contract (MUST NOT break).** Tool names, `inputSchema`, the `{"result"|"error"}` envelope, and `mcp__<skill>__<tool>` fully-qualified naming. Any refactor toward namespacing needs a compatibility-adapter mapping old bare names.

---

## 9. LLM Backend

### Component block — LLM

- **Current files.** `ari/llm/client.py` (`LLMClient`, concrete, from L26), `ari/llm/routing.py` (`resolve_litellm_model` L37, `_KNOWN_PREFIXES` L21), `ari/llm/cli_server.py` (**919 LOC**, OpenAI-compatible HTTP shim), `ari/llm/__init__.py`. Total `llm/` = 1,234 LOC. Cost capture lives separately in `ari/cost_tracker.py` (448 LOC).
- **Current responsibility.** Provider abstraction over litellm. `resolve_litellm_model(model, backend)` is the single source of truth for provider prefixes; `LLMClient` wraps `litellm.completion`, forwards node/phase/skill via `metadata` (L122), detects the cli-shim target (`_is_cli_shim_target` L71, port :8900), forwards MCP config + `work_dir` via `extra_body` (L169-179). `cli_server.py` wraps `claude -p`/`codex exec` as virtual models (`parse_model` L103, `VIRTUAL_MODELS` L743), surfacing real cost as non-standard `usage.cost_usd` (L456/512).
- **Inbound dependencies.** `core.py::build_runtime`; `agent/loop.py`, `orchestrator/bfts.py`, others construct/use `LLMClient`. Re-exported via `ari/public/llm.py` (`LLMClient`).
- **Outbound dependencies.** `litellm`; `ari/configs/model_prices.yaml` (pricing via cost_tracker).
- **Runtime role.** Every LLM call in core flows through `LLMClient` — **except** the evaluator, which bypasses it (see §10 problem 1).
- **Public contract.** `ari.public.llm.LLMClient` — stable API.
- **Observed problems.** **No `BaseModelBackend`/ABC** — `LLMClient` is concrete. **No retry/backoff anywhere** (no `num_retries`/tenacity). Timeouts hardcoded: `litellm.completion(timeout=1800)` (client.py:180), evaluator thread `future.result(timeout=120)` (llm_evaluator.py:535), shim `TIMEOUT` env default 1800. Inline special-cases: `gpt-5*` temperature drop (client.py:130), qwen3 think-disable (L142). Cost capture is a **process-wide litellm monkeypatch** installed at `init()` (`cost_tracker.py:288-326`, `_install_litellm_metadata_injector`) plus a `success_callback`; `CallRecord.latency_ms` is never populated (data available but unused, cost_tracker.py:406); `_reload_existing` (L91) drops additive fields when restoring `cost_trace.jsonl`.
- **Likely refactoring direction (ADAPT).** Introduce a `BaseModelBackend` protocol behind `ari.public.llm`; add retry/backoff and config-driven timeouts; route the evaluator through `LLMClient`; move the monkeypatch behind an explicit adapter. Preserve `LLMClient` symbol as a compatibility shim.
- **Related subtasks.** Backend protocol; retry policy; evaluator-routes-through-client; cost-capture de-monkeypatch (§24).

---

## 10. Evaluator

### Component block — Evaluator

- **Current files.** `ari/evaluator/llm_evaluator.py` (**723 LOC**, `LLMEvaluator` L240), `ari/evaluator/dynamic_axes.py` (516), `ari/evaluator/__init__.py`. Total `evaluator/` = 1,261 LOC. Correctness/cost scoring lives in the **skill** `ari-skill-evaluator/src/server.py` (983 LOC). Protocol at `ari/protocols/evaluator.py` (`Evaluator`, `@runtime_checkable`, one async `evaluate`).
- **Current responsibility.** Multi-axis LLM-judge scoring with a pluggable composite. `LLMEvaluator` is the single concrete evaluator (no ABC subclassing; it satisfies the `Evaluator` Protocol structurally). Returns per-axis scores in [0,1]; composite stored as `metrics["_scientific_score"]` (L662, returned L709). Composites are **functions** in `_COMPOSITES` registry (L165-170): `weighted_harmonic_mean` (default), `weighted_arithmetic_mean`, `weighted_min`, `weighted_geometric_mean`; selected via ctor `composite=` validated against the registry (L280) and surfaced by `EvaluatorConfig.composite` Literal (`config/__init__.py:212`). Axes: legacy 5-axis `AXIS_NAMES` (L31) vs Phase-3 `dynamic_axes.build_axes_for_run` (L449) — `GENERIC_AXES` (6 axes), rubric `score_dimensions`, plan §-tag keyword axes + domain vocabularies (HPC/ML/theory/HCI); three modes via `axis_mode` legacy/dynamic/custom; wired in `core.py:195-202`.
- **Inbound dependencies.** `core.py::build_runtime`; `agent/loop.py` (`evaluate_sync` at L1454/1532/1600).
- **Outbound dependencies.** `litellm.acompletion` **directly** (L585, bypassing `LLMClient`); `ari/prompts/evaluator/{extract_metrics,peer_review}.md` (loaded L255/413); `dynamic_axes`; `MetricSpec`.
- **Runtime role.** Scores each finished node; the composite feeds BFTS ranking.
- **Public contract.** The `Evaluator` Protocol (internal); no `ari.public` re-export. The skill's 3 MCP tools (`make_metric_spec`, `claim_evidence_hard_gate`, `evidence_grounded_semantic_review`) are external contracts.
- **Observed problems.** (1) `LLMEvaluator.evaluate` bypasses `LLMClient` and calls litellm directly (L585), passing `api_base` manually and relying on the global monkeypatch for provider routing rather than call-site `resolve_litellm_model`. (2) Hardcoded 120s thread timeout (L535). (3) No separate correctness/perf/cost axis type in core — perf is domain-injected via `MetricSpec.expected_metrics` + HPC plan keywords; correctness/cost live in the skill; cost is *tracked, never scored*. (4) Composites are functions, not a `BaseCompositeEvaluator` hierarchy.
- **Likely refactoring direction (ADAPT).** Route `evaluate` through `LLMClient`; formalize `BaseEvaluator`/composite protocol under `ari.protocols`; config-drive the timeout. Keep the `_COMPOSITES` keys and `EvaluatorConfig.composite` Literal in sync (contract).
- **Related subtasks.** Evaluator-through-client; composite protocol; axis-mode consolidation (§24).

---

## 11. Memory

### Component block — Memory

- **Current files.** Core `ari/memory/` (6 files, 343 LOC): `client.py` (`MemoryClient` **ABC** L8: `add`/`search`/`get_all`), `letta_client.py` (`LettaMemoryClient` L22, delegates to `ari_skill_memory.backends.get_backend` L27 — the first core→skill import), `file_client.py` (`FileMemoryClient` L16), `local_client.py` (`LocalMemoryClient` L8), `auto_migrate.py` (`maybe_auto_migrate` L28). Skill side: `ari-skill-memory/src/ari_skill_memory/` with a richer `MemoryBackend` **ABC** (`backends/base.py:8`), `in_memory`/`letta` impls (`get_backend` factory `backends/__init__.py:15`), and `server.py` (238 LOC, 13 `@mcp.tool`, CoW-guarded `_set_current_node` L212).
- **Current responsibility.** Ancestor-scoped run memory. Canonical store is JSONL at `{ARI_CHECKPOINT_DIR}/memory_store.jsonl`; deterministic keyword scoring; no LLM calls (design principle P2).
- **Inbound dependencies.** `core.py:130` hardcodes `LettaMemoryClient(...)`; ~13 core sites import `ari_skill_memory.backends.get_backend` (§3).
- **Outbound dependencies.** `ari_skill_memory.backends`; `ari.public.cost_tracker` (from the skill side, bidirectional).
- **Runtime role.** Read/write of node-scoped memories consumed by BFTS (`select_next_node` `memory.search`) and AgentLoop (`add_memory`).
- **Public contract.** MCP memory tools; the `MemoryClient` ABC methods; the `memory_store.jsonl` file format; `add_memory`/`search` semantics.
- **Observed problems.** **Two parallel abstractions** — core `MemoryClient` ABC vs skill `MemoryBackend` ABC — that don't share types and diverge (REVIEW_REQUIRED whether intentional). `memory/__init__.py:3,16` calls the ABC a "protocol" (Protocol-vs-ABC convention not unified). No factory dispatch in core: `ARI_MEMORY_BACKEND` is set (`config/__init__.py:316`) but no core dispatch consumes it. Possible **JSON-vs-JSONL mismatch**: `FileMemoryClient._load` (file_client.py:44) parses the whole file as one JSON array while the canonical path is `.jsonl` and `auto_migrate` reads line-wise (runtime impact unconfirmed).
- **Likely refactoring direction (ADAPT).** Reconcile the two ABCs behind one `BaseMemoryClient` contract in `ari.protocols`; drive backend selection from `ARI_MEMORY_BACKEND`; resolve the JSON/JSONL loader discrepancy. Preserve MCP tools + file format.
- **Related subtasks.** Memory-client protocol unification; backend dispatch; file-format guard (§24).

---

## 12. Artifact / Checkpoint / Trace / Workspace

### Component block — Storage / Paths

- **Current files.** `ari/paths.py` (**303 LOC**, `PathManager`, re-exported verbatim by `ari/public/paths.py`, 6 LOC), `ari/checkpoint.py` (197 LOC, JSON tree I/O), `ari/container.py` (481), `ari/env_detect.py`, `ari/pidfile.py`, `ari/migrations/v05_to_v07/{legacy_axes,memory,node_reports}.py`.
- **Current responsibility.** `PathManager` is the single source of truth: takes `workspace_root` (default cwd), derives `checkpoints_root`/`experiments_root`/`staging_root`/`paper_registry_root`; `checkpoint_dir(run_id)` = `checkpoints/{run_id}/`; `node_work_dir` = `experiments/{run_id}/{node_id}/`; `new_staging_dir()` = `staging/{YYYYmmddHHMMSS}/`. Logs are **not** a separate tree — `log_dir()`/`log_file()` return the checkpoint dir + `ari.log` (paths.py:153-158). `ARI_CHECKPOINT_DIR` is the one canonical run pin (paths.py:238-274; `checkpoint_dir_from_env`, `from_env`, `from_checkpoint_dir`).
- **Inbound dependencies.** CLI hand-off at `cli/commands.py:128`, `cli/run.py:280-283/538`, `cli/bfts_loop.py:378`, `cli/migrate.py:59`; viz handlers; pipeline.
- **Outbound dependencies.** Filesystem; `ari_skill_memory` (JSONL store lives in the checkpoint dir).
- **Runtime role.** Every artifact/trace/report path resolves through `PathManager`.
- **Public contract.** `ari.public.paths.PathManager`; the checkpoint directory layout and `META_FILES` set (paths.py:51-76: `experiment.md, launch_config.json, meta.json, tree.json, nodes_tree.json, bfts_tree.json, results.json, idea.json, cost_trace.jsonl, cost_summary.json, workflow.yaml, ari.log, .ari_pid, .pipeline_started, evaluation_criteria.json, viz_access.jsonl, memory_access.jsonl, memory_access.summary.json, node_report.json` + `.log` + regex `memory_access.*.jsonl`).
- **Observed problems.** **Workspace-root disagreement**: `config/__init__.py:588-592 auto_config` defaults to `{repo_root}/workspace/checkpoints/{run_id}` but the shipped `ari-core/config/default.yaml:14,39` still say `./checkpoints/{run_id}/` (root-level). The root `checkpoints/` dir exists **empty** alongside populated `workspace/checkpoints/` — legacy coexistence confirmed on disk. Checkpoint is a **flat directory of ~45 sibling files** (figs `fig_1.pdf/png/svg`, paper `full_paper.tex/pdf/bbl`, `refs.bib`, `ors_*.json`, `repro_sandbox/`, `paper/`, `uploads/`, stray `ari_run_*.log`); **no `artifacts/`, `traces/`, or `reports/` subdirs exist today** — the concrete driver for a proposed `runs/<id>/{workspace,checkpoints,artifacts,traces,reports}` consolidation. `checkpoint.py` `load_nodes_tree()` has 3-tier precedence (`tree.json → nodes_tree.json → newest non-empty `node_*/tree.json``, L86-137, legacy per-node layout). All runtime storage is **git-ignored** (`.gitignore` lines 26/31/70/83/84; `git ls-files` = 0 tracked) so a `runs/<id>/…` consolidation has **no git-tracking migration cost**, only on-disk/back-compat concerns.
- **Likely refactoring direction (ADAPT).** Consolidate flat checkpoints into typed subtrees behind `PathManager` accessors (add `artifacts_dir`/`traces_dir`/`reports_dir`) with a back-compat reader; reconcile the `default.yaml` vs `auto_config` workspace-root disagreement; formally retire the empty root `checkpoints/` (MOVE_TO_LEGACY). Keep `PathManager` symbol + `META_FILES` stable, or provide a migration shim.
- **Related subtasks.** Checkpoint subtree layout; workspace-root reconciliation; root-`checkpoints/` retirement (§24).

`ari/migrations/v05_to_v07/memory.py:26` is the **sole** legitimate accessor of legacy `~/.ari/global_memory.jsonl`; all other code avoids `~/.ari` (v0.5.0 checkpoint-scoped design), enforced by `refactor-guards.yml` (§21).

---

## 13. Config System

The "config/configs/sonfigs" concern resolved: **there is no `sonfigs/`**. The confusable trio is:

| Path | Kind | Contents | LOC |
|---|---|---|---|
| `ari-core/ari/config/` | Python **code** | `finder.py` (145, workflow/profile YAML discovery; `package_config_root()` L28-42 returns `ari-core/config/`), `__init__.py` (628, Pydantic models + `ARI_*` env overrides + `auto_config`), `README.md` | 773 |
| `ari-core/ari/configs/` | packaged **data + loader** | `_loader.py` (58, `ConfigLoader` Protocol + `FilesystemConfigLoader` `.yaml→.yml→.json`), `defaults.yaml` (only `models.lineage_decision_default: gpt-4o-mini`), `model_prices.yaml`, `README.md` | 69 |
| `ari-core/config/` | shipped rubric/profile/workflow **data** | `default.yaml`, `workflow.yaml` (~23.6 KB), `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml` (**23 venues**: acl, aer, ahr, apsr, chi, cvpr, econometrica, generic_conference, iclr, icml, icra, journal_generic, nature, neurips, osdi, philreview, pmla, qje, sc, siggraph, stoc, usenix_security, workshop) + `reviewer_rubrics/fewshot_examples/neurips/*.json` (3 examples) | data |

### Component block — Config

- **Current files.** `ari/config/__init__.py` (628), `ari/config/finder.py` (145), `ari/configs/_loader.py` (58), plus data trees above.
- **Current responsibility.** Pydantic schema (`ARIConfig` with `extra="allow"`, `LLMConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LoggingConfig`, `SkillConfig`, `CustomAxisSpec`) + `load_config()` + `auto_config()` + workflow/profile discovery.
- **Inbound dependencies.** Everywhere; re-exported via `ari/public/config_schema.py`.
- **Outbound dependencies.** PyYAML, Pydantic v2; the data trees.
- **Runtime role.** Loads and validates run configuration; resolves the active `workflow.yaml`/profile.
- **Public contract.** `ari.public.config_schema.*` (`ARIConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LLMConfig`, `LoggingConfig`, `SkillConfig`); YAML file formats under `config/` and `configs/`.
- **Observed problems.** `load_config()` (L326) is a monolith interleaving Pydantic parse with heavy `ARI_*` env-override glue (`_apply_*_env_overrides` L382-545) and env-string substitution — not DI-friendly. `finder.find_workflow_yaml` has **four fallback tiers spread across two dir trees** (`{checkpoint}/workflow.yaml|pipeline.yaml → {pkg}/profiles/{profile}.yaml → {pkg}/default.yaml → {pkg}/workflow.yaml`, finder.py:60-100). Two unrelated "defaults" files (`config/default.yaml` vs `configs/defaults.yaml`). `config/__init__.py` is **628 LOC** — unexpectedly large for a config-*locator* package. The `config/` (code) vs `configs/` (data) naming is a persistent confusable — REVIEW_REQUIRED for a rename with a compatibility shim.
- **Likely refactoring direction (ADAPT).** Split `load_config` parse from env-override application; collapse the 4-tier discovery behind one `WorkflowLocator`; consider a clearer name for the `config/` (code) package with import shims. Keep `ari.public.config_schema` symbols and YAML formats stable.
- **Related subtasks.** Config-locator consolidation; env-override separation; directory-naming policy (§24).

---

## 14. Public API Surface

### Component block — Public API

- **Current files.** `ari/public/` (9 files, **148 LOC total**): `__init__.py` (27, **docstring-only — re-exports nothing at top level**), `claim_gate.py` (29), `config_schema.py` (28), `container.py` (11, `from ari.container import *`), `cost_tracker.py` (11, star-import), `llm.py` (10), `paths.py` (5), `run_env.py` (15, star-import), `verified_context.py` (15).
- **Current responsibility.** The stable Python API that skills and external callers import.
- **Inbound dependencies.** All 14 skills (universally `cost_tracker`; also `claim_gate`, `container`, `run_env`, `verified_context`); docs.
- **Outbound dependencies.** Re-exports internals: `claim_gate` ← `ari.pipeline.claim_gate`; `config_schema` ← `ari.config`; `container` ← `ari.container`; `cost_tracker` ← `ari.cost_tracker`; `llm.LLMClient` ← `ari.llm.client`; `paths.PathManager` ← `ari.paths`; `run_env` ← `ari.agent.run_env`; `verified_context` ← `ari.pipeline.verified_context`.
- **Runtime role.** The sanctioned core↔skill seam.
- **Public contract.** Every symbol here is frozen: `claim_gate.{run_hard_gate,check_emission,classify_concept,scan_science_data,CONCEPT_INVARIANTS}`; `config_schema.{ARIConfig,BFTSConfig,CheckpointConfig,EvaluatorConfig,LLMConfig,LoggingConfig,SkillConfig}`; `container.*`; `cost_tracker.{bootstrap_skill,record,init_from_env,...}`; `llm.LLMClient`; `paths.PathManager`; `run_env.{capture_env,shell_capture_snippet}`; `verified_context.{render_grounded_block,write_verified_context,build_verified_context}`.
- **Observed problems.** `ari/public/__init__.py` re-exports **nothing** despite the README saying "import from `ari.public.*`" — callers must import submodules. `ari/__init__.py` is empty (no `ari.__version__`). Several public modules are star-imports (`container`, `cost_tracker`, `run_env`) with dynamic `__all__`, weakening the explicit-contract guarantee. `ari/core.py:83 build_runtime` and `:235 generate_paper_section` are **internal** (used by CLI), **not** part of `ari.public`.
- **Likely refactoring direction (ADAPT).** Add explicit top-level re-exports + `__all__` to `ari/public/__init__.py`; add `ari.__version__`; replace star-imports with named exports. No breakage — additive only. A candidate `check_public_api_contracts.py` snapshot gate would freeze this surface (do not implement now).
- **Related subtasks.** Public-API re-export + snapshot gate; `__version__` (§24).

---

## 15. CLI

Root Typer `app = typer.Typer(name="ari")` in `ari/cli/__init__.py` (175 LOC). Order pinned by `_reorder_commands_for_compat()` (L148-170). Single console script (CONTRACT): `ari = ari.cli:app`.

**Top-level commands** (file:line — args; options): `clone` (commands.py:53 — `ref, [dest]`; `--expect-sha256 --no-extract --registry --token`); `run` (run.py:168 — `experiment`; `--config --profile --virsci-live/--no-virsci-live --virsci-k --virsci-team-size --virsci-n-authors --virsci-n-papers`, sets `ARI_IDEA_VIRSCI_*`); `resume` (run.py:446 — `checkpoint_dir`; `--config`); `paper` (projects.py:61 — `checkpoint_dir`; `--experiment --config --rubric --fewshot-mode --num-reviews-ensemble --num-reflections`, sets `ARI_RUBRIC/ARI_FEWSHOT_MODE/...`); `status` (projects.py:171); `skills-list` (commands.py:143); `viz` (commands.py:169 — `--port` 8765); `projects` (projects.py:222); `show` (projects.py:284); `delete` (commands.py:105 — `--yes/-y`); `settings` (commands.py:196 — `--model --api-key --partition --cpus --mem`).

**Sub-typers via `add_typer`** (loaded under broad `try/except Exception` import guards, L82-100): `memory` (`memory_cli.py`: migrate, backup, restore, start-local, stop-local, prune-local, compact-access, health); `ear` (`cli_ear.py`: curate, status, publish, promote); `registry` (`registry/cli.py`: serve + nested `token` typer: issue, revoke, list); `migrate` (`cli/migrate.py`: node-reports).

**Observed problems.** `cli/bfts_loop.py` is **911 LOC** (scheduling + workspace + persistence + lineage — §5). `cli/lineage.py` is **not** a typer command despite the name (holds `_execute_lineage_decision`; imported by `cli/__init__.py:70`, `cli/run.py`, `cli/bfts_loop.py`) and creates a **core→viz dependency** (imports `viz.api_orchestrator._api_launch_sub_experiment`, cli/lineage.py:151). The `try/except Exception` guards (L82-100) mean **a broken import silently drops a whole command group** — REVIEW_REQUIRED. Lazy-delegator monkeypatch anti-pattern at `cli/run.py:41`, `cli/projects.py:39`.

**Public contract (MUST NOT break).** Command names, option flags, and their env-var side effects.

---

## 16. Viz / Dashboard Backend

### Component block — Viz backend

- **Current files.** `ari/viz/` (27 files, **8,131 LOC**): `routes.py` (**1197**, request handler + dispatch), `server.py` (threads), `state.py`/`state_sync.py`/`websocket.py`, `api_experiment.py` (929), `api_paperbench.py` (813) + `api_paperbench_worker.py`, `api_workflow.py`, `api_wizard.py`, `api_settings.py` (553), `api_state.py` (76, thin re-export facade), `api_tools.py`, `api_process.py`, `api_publish.py`, `api_orchestrator.py`, `api_memory.py`, `api_ollama.py`, `api_fewshot.py`, `checkpoint_api.py`, `checkpoint_finder.py`, `checkpoint_lifecycle.py`, `ear.py`, `file_api.py`, `node_work_api.py`, `ui_helpers.py`.
- **Current responsibility.** HTTP + WebSocket dashboard backend.
- **Inbound dependencies.** React frontend `services/api.ts` (863 LOC) + WebSocket; CLI `ari viz`.
- **Outbound dependencies.** **Direct internal (non-`ari.public`) imports in handlers**: `ari.paths.PathManager`, `ari.checkpoint`, `ari.config.auto_config`, `ari.llm.client.LLMClient`, `ari.clone`, `ari.orchestrator.web_provenance`, `ari.container`, `ari.pidfile`, `ari_skill_memory.backends.get_backend` (routes.py:203-205) — bypassing the stable surface.
- **Runtime role.** Serves the dashboard; launches experiments/stages via subprocess; streams state.
- **Public contract.** Every endpoint path + method + response shape (consumed by `services/api.ts`); the WS `{"type":"update","data":<tree>,"timestamp":...}` message.
- **Observed problems.** **Python stdlib `http.server` — no Flask/FastAPI/aiohttp.** `_DualStackServer(ThreadingHTTPServer)` (server.py:82-96) + a single `BaseHTTPRequestHandler` subclass `_Handler` (routes.py:77). **Routing is one giant if/elif chain** on `self.path` inside `do_GET` (routes.py:144-1026, ~86 branches) and `do_POST` (1028-1188, ~51 branches) — no route table (an abandoned declarative `WIZARD_ROUTES` dict at `api_wizard.py:30` shows the intent). No schema/validation/DTO layer; POST bodies are raw `bytes`→`json.loads` per handler; two response conventions coexist (`{"ok":...}` vs `{"error":...}`); status codes smuggled via `r.pop("_status", 200)`. **The `GET /state` handler is inlined at routes.py:219-666 (~450 lines)** doing dozens of `Path.exists`/`read_text`/`json.loads`, glob scans, YAML profile merging, `cost_trace.jsonl` tail-parsing, and reaching into `_st._last_proc.poll()`/`ari.pidfile`. SSE loops written inline in the route (PaperBench logs 934-1000, `/api/logs` 901-908). **Subprocess spawning inside handlers** (`api_experiment._api_run_stage` Popen 129-136; `_api_launch` 782; `api_orchestrator._api_launch_sub_experiment` 287; `api_process` Popen/pkill/pgrep; `api_memory` subprocess.run). **Mutable module-global state** in `state.py` (`_checkpoint_dir`, `_last_proc`, `_running_procs`, `_launch_config`, `_clients`, `_sub_experiments`) read/written directly by handlers; PaperBench uses an in-memory `_JOBS` dict + lock (lost on restart). **No authentication/authorization anywhere** and `Access-Control-Allow-Origin: *` on GET (8 wildcard sites); hand-rolled, inconsistent path-traversal guards. **Duplicate pipeline** in `api_paperbench_worker.py:168` (§7).
- **Likely refactoring direction (ADAPT).** Replace if/elif with a route registry; extract the 450-line `/state` builder into a `StateService`; move subprocess/env orchestration into a launch service/adapter; introduce request DTOs + a unified `_json` response wrapper; wrap internal `ari.*`/`ari_skill_memory` access behind adapters so routes depend only on `ari.public.*`; one `FileService` for serving + traversal checks. **Every endpoint path + shape is a contract** — refactor behind adapters, do not rename endpoints.
- **Related subtasks.** Route registry; StateService; launch adapter; viz→`ari.public` boundary; viz API schema gate (§24).

---

## 17. Dashboard Frontend

### Component block — Frontend

- **Current files.** `ari-core/ari/viz/frontend/` — Vite 5 + React 18.3 + TypeScript 5.5, ESM. `src/App.tsx` (hash router, `PAGE_MAP` 12 routes, `lazy()`+`Suspense`), `src/services/api.ts` (**863 LOC**, ~90 typed wrappers), `src/context/AppContext.tsx` (120, single Context, 5s polling of `/state`+`/checkpoints`), `src/hooks/useWebSocket.ts`, `src/i18n/{en 444, ja 441, zh 441}.ts`, `src/styles/dashboard.css`. Worst-offender components: `Results/resultSections.tsx` (**1590**), `Wizard/StepResources.tsx` (1160), `Settings/SettingsPage.tsx` (1049), `Workflow/WorkflowPage.tsx` (964), `Workflow/workflowNodes.tsx` (770), `Wizard/StepGoal.tsx` (528), `Results/PaperWorkspace.tsx` (519), `Monitor/MonitorPage.tsx` (502).
- **Current responsibility.** The React dashboard SPA.
- **Inbound dependencies.** Served by the viz backend (`viz/static/dist/`, git-ignored line 114).
- **Outbound dependencies.** Same-origin `fetch` (`API_BASE=''`); WebSocket on `port+1`.
- **Runtime role.** Operator UI for launching/monitoring experiments and reviewing results.
- **Public contract.** The endpoint families it depends on (must stay wire-compatible with `services/api.ts` typed shapes: `Settings` 35 fields, `AppState`, `NodeReport`, `MemoryEntry`/`MemoryAccessEvent`).
- **Observed problems.** No CSS framework — single `dashboard.css` + pervasive inline `style={{}}`. Hand-rolled hash router (no react-router); nav mirror hardcoded in `Layout/Sidebar.tsx:12-23` (Sidebar omits `paperbench` — manual route-drift risk). Single Context, no Redux/Zustand/react-query; components hold large `useState` clusters (SettingsPage ~30 hooks). **Two error regimes coexist** (contract hazard): `get/post` **throw** on non-2xx (api.ts:18-32) but PaperBench `pbGet/pbPost` **never throw**, returning `{error}` bodies. **No auth/token/CSRF header anywhere.** Provider/model lists are **hardcoded and stale-prone** (`settingsConstants.ts:9-15`, e.g. `gpt-5.2`, `claude-opus-4-5`). Minor i18n key drift (en 444 vs ja/zh 441). **CORRECTION to prior skeletons:** committed `node_modules/` is **NOT present** — `git ls-files` matches **0** files under `node_modules`; `.gitignore` line 113 ignores it; `package-lock.json` (140 KB) is tracked; `node_modules/` exists on disk (~112 MB) only as a normal working install.
- **Likely refactoring direction (ADAPT).** Split the 1590/1160/1049-line god-components into section modules; unify the throw-vs-`{error}` regimes behind one client helper; drive provider/model lists from a backend endpoint; add a route/nav single-source. Keep `services/api.ts` wire shapes stable.
- **Related subtasks.** Component decomposition; API-client error unification; nav single-source; frontend UX gate (§18/§24).

---

## 18. Dashboard UX

`SettingsPage.tsx` (1049 LOC) renders **9 `<Card>` sections** top-to-bottom (no tabs/search): Language (en/ja/zh); LLM Backend (provider openai/anthropic/gemini/ollama/cli-shim + model + temperature + API key + Base URL, L383-478); Paper Retrieval (semantic_scholar/alphaxiv/both + SS key, 481-509); VLM Figure Review (512-523); Memory/Letta (base URL, API key, embedding provider+model, deployment auto/docker/singularity/pip, Restart, 526-695); SLURM/HPC (partitions + Detect, CPUs, Mem, walltime, 698-770); Container (mode, pull policy, image, Detect, 773-827); Available Skills (read-only, 830-877); SSH Remote Host (880-943); Project Management (delete checkpoints, 946-1035). Save posts a flat 24-key object (235-260).

**Settings/UX split to flag.** The `Settings` type declares `model_idea/bfts/coding/eval/paper/review` + `vlm_review_enabled/max_iter/threshold` (`types/index.ts:59-71`) that have **no UI in SettingsPage** — per-phase models live in `StepResources`, not global Settings.

**Dangerous / raw-debug UI currently exposed** (REVIEW_REQUIRED for a `check_dashboard_ux.py` gate — do not implement now):
- DetailPanel "{ } Raw" tab dumps full node JSON (`DetailPanel.tsx:364,411-419`).
- `/api/env-keys` returns actual env secret **values** to the browser; `StepResources.autoReadApiKey` reads `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` (`api.ts:382`, `StepResources.tsx:333-342`); API keys editable and persisted to `.env` via `/api/settings`.
- GPU Monitor "SLURM Auto-Resubmit" continuously submits SLURM jobs; only guard is `window.confirm`, and `gpuMonitorAction` always sends `confirmed:true` (`GpuMonitor.tsx:46-55`).
- `dangerouslySetInnerHTML` in `StepScope.tsx:137`; raw `innerHTML` error-stack write in `main.tsx:38`; ErrorBoundary prints full stack to the page.
- Raw `JSON.stringify` dumps in `monitorSections.tsx`, `TraceTab.tsx`, `ExperimentsPage.tsx`, `resultSections.tsx`; raw-YAML editor `PublishYamlEditor`.

---

## 19. Prompt Locations

Core loader `ari/prompts/_loader.py` (49 LOC): `FilesystemPromptLoader` + `PromptLoader` Protocol. `load(key)` reads `{base}/{key}.md`; `load_versioned(key)` returns `(text, sha256[:12])` for reproducibility. Templates are **`.md` (not `.j2`)**, filled via `str.format(...)`. Every core load site uses a lazy in-function import (11 files): `agent/loop.py:51`, `evaluator/llm_evaluator.py:255,413`, `orchestrator/bfts.py:475,553,743`, `orchestrator/lineage_decision.py:293`, `orchestrator/root_idea_selector.py:63`, `pipeline/context_builder.py:117`, `viz/api_tools.py:55,127`.

**Externalized core templates** (11 + 5 READMEs): `agent/system.md` (13L); `evaluator/{extract_metrics 16L, peer_review 12L}.md`; `orchestrator/{bfts_expand 16L, bfts_expand_select 8L, bfts_select 15L, lineage_decision 6L, root_idea_selector 6L}.md`; `pipeline/keyword_librarian.md` (352 B, populated); `viz/{wizard_chat_goal 607 B, wizard_generate_config 257 B}.md`.

**Skill-local (externalized but bypass the core loader — `Path.read_text`, no versioning/hash):** `ari-skill-replicate/src/prompts/{skeleton 143L, subtree 115L, adversarial_reviewer 208L, rubric_audit 28L}.md`; `ari-skill-paper-re/src/prompts/replicator.md` (154L) + `mpi_aggregate_skel.py` (code skeleton, not a prompt). Mechanism inconsistency — REVIEW_REQUIRED.

**Still-hardcoded prompts (candidate `EXTRACT_TEMPLATE`):** `ari-skill-evaluator/src/server.py:790 _SEMANTIC_SYSTEM_PROMPT` (~18L), `:191 _METRIC_EXTRACT_SYS` (~11L); `ari-skill-paper/src/server.py` 5 inline "You are…" prompts (542, 1487, 1638, 1660, 2544 `_GLOBAL_COHERENCE`); `ari-skill-plot/src/server.py:90,560,663`; `ari-skill-vlm/src/server.py:97,112`; `ari-skill-transform/src/server.py:834,867`; `ari-skill-web/src/server.py:465,483`. **MERGE_DUPLICATE / REVIEW_REQUIRED:** `ari-skill-paper/src/review_engine.py:79,443` (peer reviewer / Area Chair) vs core `evaluator/peer_review.md`; `ari-skill-evaluator/src/server.py:191` vs core `evaluator/extract_metrics.md`. **KEEP_INLINE:** `ari-skill-idea/src/server.py:252-266` (fallback only; primary path execs vendored VirSci `utils/prompt.py`); `ari-skill-paper-re/src/_paperbench_bridge.py` (2376L, 59 triple-quotes — mostly vendored PaperBench templates, keep for upstream parity).

A candidate `check_prompts.py` externalization-inventory scan would be NEW (do not implement now); note `report/scripts/check_prompt_snapshots.py` (Gate 10) already byte-verifies `ari/prompts/**/*.md` snapshots — the snapshot slice OVERLAPS.

---

## 20. Scripts

Existing quality tooling (all confirmed by reading source):

- **Repo tooling.** `scripts/readme_sync.py` (per-directory README `## Contents` drift, `--check`/`--write`, stdlib only); `scripts/git-hooks/pre-commit` (runs `readme_sync.py --write`, **non-blocking**, `exit 0` on failure); `scripts/run_all_tests.sh` (per-skill pytest in isolated processes, **not referenced by any workflow**); `scripts/sc_paper_dogfood.py`, `scripts/sc_paper_stage23_chain.py`, `scripts/gpu_ollama_monitor.sh`, `scripts/build_pb_images.sh`.
- **`scripts/docs/`** (convention: `argparse` + `--json`, PyYAML-only, staged warning→error): `check_doc_sources.py`, `check_doc_links.py`, `check_i18n_js.py`, `check_readme_parity.py`, `check_ref_coupling.py` (diff gate, advisory), `check_report_cochange.py` (diff gate, hard), `check_site_i18n.py`, `check_translation_freshness.py`, `sync_report_pdf.sh`, `assemble_site.sh`.
- **`report/scripts/`** (`Gate N` convention): `check_prompt_snapshots.py` (Gate 10), `snapshot_prompts.py`, `check_i18n.py` (Gate 6), `check_bib/glossary/figures/notation/tikz/toc_consistency/logs_for_secrets.py`.

**Tooling availability:** ruff 0.15.2 **installed** (unused in CI); radon **not installed**; `python compileall`/pytest/node/npm available; **no pnpm**.

**MISSING checkers (to be designed as subtasks — do NOT implement now).** `grep` confirms **none of the 11 proposed names exist**. Status vs existing coverage:

| Proposed | Status |
|---|---|
| `check_complexity.py` | MISSING (no LOC/cyclomatic gate; radon absent, ruff `C901` not enabled) |
| `check_import_boundaries.py` | MISSING (nearest analog is `refactor-guards.yml`'s `~/.ari` diff-grep — a content ban, not an import graph) |
| `check_docs_source_sync.py` | **OVERLAP** with `check_doc_sources.py` + `check_ref_coupling.py` — likely redundant unless it adds a new direction |
| `check_directory_policy.py` | **PARTIAL OVERLAP** with `readme_sync.py`; placement/naming policy (`config/` vs `configs/`) is MISSING |
| `check_public_api_contracts.py` | MISSING (no gate/snapshot over `ari.public.*`) |
| `check_viz_api_schema.py` | MISSING (no gate coupling `viz/routes.py`+`api_*.py` to `services/api.ts`) |
| `check_prompts.py` | **OVERLAP** with Gate 10 snapshots for the snapshot slice; the inline-prompt inventory would be NEW |
| `check_dashboard_ux.py` | MISSING (only `check_i18n_js.py`, landing JS not React `i18n/*.ts`) |
| `analyze_references.py` | MISSING as a code cross-reference analyzer (name collides conceptually with `check_ref_coupling.py`) |
| `check_dead_code.py` | MISSING (no vulture; ruff `F401` available but unwired) |
| `generate_quality_report.py` | MISSING (every checker emits `--json` building blocks; nothing aggregates) |

---

## 21. GitHub Workflows

`.github/` contains **only** `workflows/` (5 files). Confirmed absent: `ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`, `.github/actions/`. All 12 scripts referenced by workflows exist on disk.

1. **`refactor-guards.yml`** — the only workflow touching Python source and the only one targeting `refactoring` branches. Job `no-home-ari-writes` runs `pytest ari-core/tests/ -q` under a redirected `HOME`, failing if `$HOME/.ari` is created (ignoring 4 live-infra tests). Job `no-new-home-ari-refs` computes `base=$(git merge-base origin/<base_ref> HEAD)` and greps added lines in `ari-core/ari/**.py` for `Path.home().*.ari|~/.ari`, excluding comments + a 14-path allow-list. **Does NOT** check public API, import boundaries, viz schema, complexity, or directory policy — proposed checkers do not overlap functionally but should reuse (a) the `git merge-base` diff idiom and (b) the path-exclude allow-list. Note `docs-change-coupling.yml`'s header critiques the `origin/<base_ref>` idiom as inferior to `github.event.pull_request.base.sha` — new workflows should prefer `base.sha`.
2. **`docs-change-coupling.yml`** — hard gate `check_report_cochange.py --base-ref <base.sha>`; advisory `check_ref_coupling.py`.
3. **`docs-sync.yml`** — job `docs-sync` hard gates (`check_doc_sources`, `check_i18n_js`, `check_site_i18n`, `check_doc_links --html-only`, `check_readme_parity`, `report/scripts/check_i18n.py`) + advisory (`check_translation_freshness`, `check_doc_links` markdown); job `vitepress-build` (`sync_report_pdf.sh --check` → `npm ci` → `docs:build`).
4. **`pages.yml`** — the only deploy workflow (`push` to `main` filtered to `docs/**`,`report/**`,`README.md`); builds `_site/` and deploys to GitHub Pages. Path filter references only `README.md`, not the ja/zh mirrors (unconfirmed whether intentional).
5. **`readme-sync.yml`** — `readme_sync.py --check`.

**Cross-cutting.** All quality gating is documentation/i18n-oriented (5 of 6 jobs). **No workflow runs ruff, compileall, import-boundary, complexity, or public-API/viz-schema checks.** No push CI except `pages.yml`; all gating is PR-time; no scheduled/matrix/reusable workflows, no local actions. **Do not rewrite these wholesale** — new gates should be added as separate workflows reusing proven patterns.

---

## 22. Docs

`docs/` is the VitePress `srcDir`; `docs/.vitepress/config.ts` (135 LOC) drives an fs-driven, auto-localized, Diátaxis sidebar (`getting-started`, `concepts`, `guides`, `guides/paperbench`, `reference`, `about`). i18n: `root=en`, `ja/`, `zh/` mirror all content **except** `reference/internal_boundaries.md` (en-only by design). Net per-locale: en 42 md, ja/zh 41 each. Static landing assets: `index.html`, `site.css`, `tokens.css`, `i18n/*.js`, `version.json` (`{"version":"v0.9.0"}`), `.vitepress/theme/`.

**Docs↔source coupling** validated two ways: front-matter `sources:` (repo-root-relative `path:` + `last_verified`, hard-gated by `check_doc_sources.py`; every declared path currently resolves) and root README triples (`check_readme_parity.py` heading-shape parity; README CLI table L318-328 + REST table L285-302; port **8765** consistent across README/quickstart/rest_api/viz).

**Confirmed drift candidates.** (1) `docs/_archive/` is **MISSING but still referenced** — `docs/README.md:86,135` link `_archive/refactor_audit.md`; VitePress `srcExclude` + `check_doc_sources` exempt `_archive`, so hard gates stay green and the broken markdown links are caught only by the **advisory** markdown-link check → silent drift. (2) `reference/environment_variables.md:211` documents `ARI_AGENT_ENV_PATH` "falls back to `~/.ari/agent.env`" — a live `~/.ari/` reference contradicting the same file (L19), `guides/migration.md`, and `concepts/architecture.md:541` which state `~/.ari` was removed in v0.5.0 (whether code still falls back is **unconfirmed**). Negative confirmations: **no `sonfigs`**, no `howto/` legacy refs.

**report/ tree.** Separate LaTeX build (en/ja/zh chapters, `shared/`, `scripts/`, `html/`, `audit/`); triple PDF copy currently byte-in-sync (`report/{lang}/main.pdf` == `docs/public/report/{lang}.pdf` == `docs/assets/report/{lang}.pdf`), maintained by `sync_report_pdf.sh --check`. Hygiene nit: `report/scripts/.venv/` and `__pycache__/` appear tracked.

`docs/refactoring/` (this planning workspace) is **not** part of the published VitePress IA; its interaction with `check_doc_sources --require-all` coverage is **unconfirmed**.

---

## 23. Observed Architectural Risks

Ranked, each grounded above:

1. **God-files concentrate risk.** Production Python >1200 LOC: `ari-skill-paper/src/server.py` (2956), `ari-skill-transform/src/server.py` (2465), `ari-skill-paper-re/src/_paperbench_bridge.py` (2376), `agent/loop.py` (1630), `ari-skill-paper-re/src/server.py` (1395); 10 more in 800-1200 (incl. `viz/routes.py` 1197, `pipeline/orchestrator.py` 913, `cli/bfts_loop.py` 911, `orchestrator/bfts.py` 845). Frontend: `resultSections.tsx` (1590), `StepResources.tsx` (1160), `SettingsPage.tsx` (1049). Data-derived split thresholds: **>500 warn / >800 review / >1200 split-required**.
2. **Layering violations bypass the stable seam.** Four skill→private-core imports (paper-re→`ari.clone`, idea→`ari.lineage`, transform→`ari.orchestrator`+`ari.publish`); viz handlers import `ari.paths`/`ari.checkpoint`/`ari.config`/`ari.llm`/`ari.clone`/`ari_skill_memory` directly; core→viz edge in `cli/lineage.py:151`. No `check_import_boundaries.py` exists.
3. **Duplication.** Two ReAct loops (`agent/loop.py` vs `agent/react_driver.py`); two pipeline drivers (`pipeline/orchestrator.py` vs `viz/api_paperbench_worker.py`); two memory ABCs (`MemoryClient` vs `MemoryBackend`); duplicated `workflow.yaml` discovery (3+ sites); 3 `evaluate_sync` + 5 memory-summary blocks in `loop.py`.
4. **Concrete-class monoliths, no injection seams.** No `BaseModelBackend`/`BaseCostTracker`/`BaseEvaluator`; composites are functions in `_COMPOSITES`; three ad-hoc string dispatchers (`publish._load_backend`, `llm.resolve_litellm_model`, memory clients) with no central registry; `ari/registry/` is an **HTTP artifact registry, not DI** (naming trap).
5. **Reliability gaps in the LLM path.** No retry/backoff; hardcoded 1800/120s timeouts; evaluator bypasses `LLMClient` (L585); process-wide litellm monkeypatch at `init()`; `latency_ms` never captured; `_reload_existing` drops fields.
6. **Dashboard security posture.** No auth anywhere; `Access-Control-Allow-Origin: *`; subprocess launch / file write / checkpoint delete / ollama proxy all open; `/api/env-keys` returns secret values; auto-resubmit SLURM guarded only by `window.confirm`; raw-JSON debug panels. (Unconfirmed whether intentional for a localhost tool.)
7. **Storage flatness.** ~45-file flat checkpoint dir with no `artifacts/`/`traces/`/`reports/` split; `default.yaml` vs `auto_config` workspace-root disagreement; empty legacy root `checkpoints/`.
8. **Manifest/tool-list drift across skills.** Version triplication, stale `mcp.json` tool lists, `requires-python` fragmentation, missing `pyproject.toml` (orchestrator), unused `server:main` scripts.
9. **CI blind spots.** All gates are docs/i18n; no ruff/compileall/complexity/public-API/viz-schema gate; 661 ruff findings (341 `F401`) unaddressed; `try/except Exception` CLI guards can silently drop command groups.
10. **Docs drift.** `_archive/` broken links (advisory-only) and the `~/.ari/agent.env` fallback contradiction.

---

## 24. Related Subtasks

Candidate subtask families for later planning phases (all **planning only** here; nothing below is authorized for implementation in this document). Each preserves the §0 contracts unless a compatibility-adapter note is attached.

**A. Component decomposition (ADAPT).**
- A1 BFTS: extract `BFTSPromptBuilder` + `NodeReport` repository (§5).
- A2 AgentLoop: split into PromptAssembler / MessageWindow / ToolResultRouter / NodeEvaluationPersister (§6).
- A3 ReAct unification: MERGE `agent/loop.py` and `agent/react_driver.py` (§6).
- A4 Pipeline: `BasePipelineStage` + `BaseWorkflowDriver` + `StageContext` + `WorkflowLocator` + `OutputSink`; unify with `viz/api_paperbench_worker._run_pipeline` (§7).
- A5 Viz backend: route registry, `StateService`, launch adapter, DTO/response wrapper, `ari.public`-only boundary, `FileService` (§16).
- A6 Frontend: decompose `resultSections`/`StepResources`/`SettingsPage`; unify error regimes; nav single-source (§17).

**B. Contracts & interfaces (ADAPT, additive).**
- B1 `ari.public.__init__` explicit re-exports + `__all__`; add `ari.__version__` (§14).
- B2 `BaseModelBackend` / `BaseEvaluator` / composite protocol under `ari.protocols`; route evaluator through `LLMClient` (§9/§10).
- B3 Memory-client protocol unification (`MemoryClient` vs `MemoryBackend`) + backend dispatch from `ARI_MEMORY_BACKEND` (§11).
- B4 MCP tool namespacing with a bare-name compatibility adapter (§8).

**C. Reliability (ADAPT).**
- C1 LLM retry/backoff + config-driven timeouts (§9).
- C2 De-monkeypatch cost capture; populate `latency_ms`; fix `_reload_existing` (§9).

**D. Storage (ADAPT + MOVE_TO_LEGACY).**
- D1 Checkpoint subtree layout (`artifacts/`/`traces/`/`reports/`) behind `PathManager` with back-compat reader (§12).
- D2 Reconcile `default.yaml` vs `auto_config` workspace root; retire empty root `checkpoints/` (§1/§12).

**E. Prompts (EXTRACT / MERGE / REVIEW).**
- E1 Externalize skill inline prompts (evaluator, paper, plot, vlm, transform, web) via a shared loader (§19).
- E2 MERGE/reconcile overlapping peer-review + metric-extract prompts across core + skill (§19).

**F. Skill hygiene (REVIEW_REQUIRED).**
- F1 Unify server idioms (FastMCP vs low-level Server); fix `mcp.json` tool-list drift; add missing `pyproject.toml` (orchestrator); resolve version skew (§3).
- F2 Fix the 4 skill→private-core boundary violations (§3).

**G. Quality gates (NEW checkers — design only).**
- `check_complexity.py`, `check_import_boundaries.py`, `check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_directory_policy.py` (placement/naming portion), `check_dashboard_ux.py`, `check_dead_code.py`, `generate_quality_report.py`; reuse the `git merge-base`/`base.sha` diff idiom and allow-list convention from `refactor-guards.yml`; avoid redundant `check_docs_source_sync.py`/`check_prompts.py` snapshot slices that overlap existing gates (§20/§21).

**H. Config (ADAPT + REVIEW_REQUIRED).**
- H1 Split `load_config` parse from env-overrides; collapse the 4-tier `find_workflow_yaml` (§13).
- H2 Directory-naming policy for `config/` (code) vs `configs/` (data) with import shims (§13).

**I. Docs drift (fix in a docs-only pass).**
- I1 Resolve `_archive/refactor_audit.md` broken links (§22).
- I2 Reconcile the `ARI_AGENT_ENV_PATH` → `~/.ari/agent.env` contradiction after verifying code behavior (§22).

---

*End of report. Grounded against `/home/t-kotama/workplace/ARI` at planning date 2026-07-01. Any item marked "unconfirmed" above was not verified beyond the cited inspection and must be confirmed before implementation.*

## Retirement Condition

This is a **program-level planning document**, not a per-subtask artifact. It
stays live for the duration of the refactoring program and may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources — never on assumption:

1. Every subtask this document governs is marked **DONE** in
   `docs/refactoring/007_subtask_index.md`, **or** this document has been
   explicitly **superseded** by a named replacement (the superseding document
   must reference this file by name).
2. Any conclusions worth keeping have been folded into the permanent
   documentation / architecture.

Before any `git rm`, re-read this document's own conditions and check each one
against the current repository. See the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
