# 003 — Dependency Boundary Report

> **Phase:** Refactoring — Planning only. **No runtime code, imports, prompts, configs,
> workflows, frontend, or directory names are changed by this document.**
> **Repo:** `/home/t-kotama/workplace/ARI` (branch `main`, `ari-core` version `0.9.0`).
> **Date:** 2026-07-01. **Author role:** senior software architect.
> **Companion enforcement subtask:** [`026 — import-boundary checker`](#12-enforcement-roadmap-subtask-026) (`scripts/check_import_boundaries.py`, does not exist yet — to be designed).

This report defines the **target dependency boundaries** for ARI and assesses the
**current state** of each boundary against verified repository facts. Every boundary
section states: (a) the rule, (b) the as-built reality with cited evidence, (c) the
target, and (d) a KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE /
REVIEW_REQUIRED classification for the follow-up implementation subtasks.

---

## 1. Scope, method, and vocabulary

### 1.1 What a "boundary" means here

A dependency boundary is a directed rule of the form *"module set A may depend on
module set B (and nothing else across the seam)."* This document is about **allowed
import direction and allowed coupling surface**, not about internal code quality.
Internal refactors (splitting a 2956-line `server.py`, etc.) are covered by other
subtasks; here we only fix *who is allowed to import whom*.

### 1.2 Classification vocabulary

Applied per finding, following the master refactoring prompt:

| Tag | Meaning in this document |
|---|---|
| **KEEP** | Boundary is already respected; encode it in a guard, do not change code. |
| **ADAPT** | Boundary is violated by a thin edge; route it through an existing stable surface (e.g. `ari.public.*`) or a new adapter, preserving the contract. |
| **MERGE** | Two overlapping mechanisms should collapse into one seam. |
| **MOVE_TO_LEGACY** | Code/path is superseded; quarantine behind a legacy marker, keep for compatibility. |
| **DELETE_CANDIDATE** | Appears unused; propose removal only after a reference sweep. |
| **REVIEW_REQUIRED** | Direction/intent unclear from static facts; needs owner confirmation before action. |

### 1.3 "deprecated" usage

Per house rule, **"deprecated" is reserved for external contracts only** (public API,
CLI, MCP tools, dashboard API, documented import paths, ari-skill stable interfaces).
Internal code that we want to retire is tagged `MOVE_TO_LEGACY` or `DELETE_CANDIDATE`,
never "deprecated."

### 1.4 Contracts that must not break (compatibility fences)

The following are frozen. Any boundary fix that touches them must ship a
**compatibility adapter** rather than a rename/removal:

- Console script `ari = ari.cli:app` and all CLI command names / option flags /
  env-var side effects (`ari-core/pyproject.toml:33`, `ari/cli/__init__.py`).
- Public Python API `ari.public.*` (every symbol re-exported from the 8 submodules).
- MCP tool contracts: bare snake_case tool names, `inputSchema`, the
  `{"result"|"error"}` return envelope, and `mcp__<skill>__<tool>` fully-qualified
  naming (`ari/mcp/client.py`).
- Dashboard API endpoint paths + response shapes consumed by the React frontend
  (`ari/viz/routes.py` + `api_*.py`, `frontend/src/services/api.ts`).
- Checkpoint / output / config file formats (`ari/checkpoint.py`, YAML under
  `config/` and `ari/configs/`).
- The `ari-skill-* → ari-core` stable interface (`ari.public.*`).
- README/docs usage examples and the scripts invoked by `.github/workflows/`.

### 1.5 A note on non-existent paths ("sonfigs")

Some upstream planning prompts reference a `sonfigs/` directory. **It does not exist**
anywhere in the repo. The only confusable trio is:
`ari-core/ari/config/` (Python code that *locates* config files) vs
`ari-core/ari/configs/` (packaged default DATA: `defaults.yaml`, `model_prices.yaml`) vs
top-level `ari-core/config/` (rubric/profile DATA). This trio is a **naming-clarity**
concern for a later subtask, not a dependency-boundary concern, and is called out here
only to prevent a spurious "sonfigs boundary."

---

## 2. Target boundary map (layer overview)

Allowed import direction (arrows point to the dependency; nothing may point "up"):

```
                    ┌───────────────────────────────────────────┐
   dashboard        │  frontend/  (React + TS)                   │
   frontend  ─────▶ │  depends ONLY on: DTO/TS types (src/types) │
                    │  + services/api.ts (HTTP)                   │
                    └───────────────┬───────────────────────────┘
                                    │  HTTP / JSON over the wire
                    ┌───────────────▼───────────────────────────┐
   viz backend      │  viz/ route handlers (thin)                │
                    │  ─▶ service / adapter / schema / store      │
                    └───────────────┬───────────────────────────┘
                                    │
   ari-core         │  agent · pipeline · orchestrator · evaluator · llm ·
   internals        │  memory · publish · clone · registry · cost_tracker
                    │                 │
                    ▼                 ▼
   stable surface   │  ari.public.*  +  ari.protocols.*  (contracts)
                    ▲
                    │  (ONLY allowed skill→core surface)
   MCP skills       │  ari-skill-*  (14 servers)  ── may import ──▶ ari.public.*
                    │
   sanctioned       │  ari-core  ── one allowed edge ──▶  ari_skill_memory
   exception        │  (see §11)
```

Rules encoded by this map (detailed per boundary below):

1. **B1** ari-skill-* → **only** `ari.public.*` / stable interfaces.
2. **B2** ari-core → **not** ari-skill-* (single sanctioned exception: `ari_skill_memory`).
3. **B3** viz route handlers stay thin; I/O and domain logic live in
   service/adapter/schema/store layers.
4. **B4** dashboard frontend → DTO/TS types + `api.ts`, **not** backend internals.
5. **B5** evaluator independent of CLI/dashboard/file-layout.
6. **B6** model backend independent of dashboard/evaluator internals.
7. **B7** pipeline stages separated behind a stage interface.
8. **B8** storage responsibilities (artifact/checkpoint/trace/workspace) clarified.
9. **B9** long prompts externalized, not inline.
10. **B10** `scripts/` limited to quality / static-analysis / report.
11. **B11** `.github` runs `scripts/check_*` in staged warning→regression→strict modes.

---

## 3. Boundary B1 — ari-skill-* depend only on `ari.public.*` / stable interfaces

**Target rule.** Every one of the 14 `ari-skill-*/src/server.py` servers (and their
helper modules) may import from `ari-core` **only** via `ari.public.*`. Any use of a
private `ari.<internal>` module across the skill→core seam is a violation.

**Contract present and correct.** `ari-core/ari/public/__init__.py` is a docstring-only
declaration that literally states *"Skills must only import from `ari.public.*`"* and
enumerates the 8 exported submodules (`claim_gate`, `config_schema`, `container`,
`cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`). The skill→core contract
is deliberately **lazy, optional, unpinned**: no skill lists `ari-core` in its
`pyproject.toml` dependencies; every touch is an in-function `try/except ImportError`.
The near-universal touchpoint `from ari.public import cost_tracker` appears in
evaluator/idea/paper/paper-re/plot/replicate/vlm/web/transform. **This part is KEEP.**

**Current state: VIOLATED at 4 confirmed edges + 3 private-fallback edges** (verified by
grep, 2026-07-01):

| Skill | Violating import | Location | Should route to |
|---|---|---|---|
| idea | `from ari.lineage import …` | `ari-skill-idea/src/server.py:614` | new `ari.public.lineage` surface (does not exist) |
| paper-re | `from ari.clone import clone, CloneError` | `ari-skill-paper-re/src/server.py:146` | new `ari.public.clone` surface (does not exist) |
| transform | `from ari.orchestrator import node_selection` | `ari-skill-transform/src/server.py:681, 2083` | new `ari.public.node_selection` surface (does not exist) |
| transform | `from ari.publish import publish, promote, PublishError` | `ari-skill-transform/src/server.py:2433, 2451` | new `ari.public.publish` surface (does not exist) |
| coding | private fallback `from ari.container import …` | `ari-skill-coding/src/server.py:569` | already primary-imports `ari.public.container`; fallback is the private path |
| coding | private fallback `from ari.agent.run_env import capture_env` | `ari-skill-coding/src/server.py:583` | primary is `ari.public.run_env`; fallback is private |
| hpc | `from ari.agent.run_env import shell_capture_snippet` | `ari-skill-hpc/src/slurm.py:211` | `ari.public.run_env` (public symbol exists) |

**Classification.**
- idea→`ari.lineage`, paper-re→`ari.clone`, transform→`ari.orchestrator`,
  transform→`ari.publish`: **ADAPT.** These are real cross-seam violations. The fix is
  to widen `ari.public.*` with thin re-export shims (`ari.public.lineage`,
  `ari.public.clone`, `ari.public.publish`, `ari.public.node_selection`) and repoint the
  skill imports at them — preserving the private module as the implementation and the
  MCP tool contract unchanged. Adding new `ari.public.*` submodules is contract-*widening*
  (backward compatible), not contract-breaking.
- coding/hpc private fallbacks: **ADAPT.** The primary import is already public; the
  `except ImportError` fallback reaches into `ari.container`/`ari.agent.run_env`. Once the
  public surface is guaranteed present in the pinned setup, the private fallback can be
  dropped (or itself pointed at `ari.public.*`).
- The 8-symbol `ari.public.*` surface and the universal `cost_tracker` usage: **KEEP.**

**Enforcement.** These 7 edges are exactly the seed test-set for
`scripts/check_import_boundaries.py` (subtask 026): grep each `ari-skill-*/` tree for
`from ari\.` / `import ari\.` and fail on any module segment not in the
`ari.public` / `ari.protocols` allowlist.

---

## 4. Boundary B2 — ari-core must not depend on ari-skill-* (one sanctioned exception)

**Target rule.** `ari-core/ari/**` must not import any `ari-skill-*` package, with a
**single sanctioned exception**: the direct `ari_skill_memory` edge (documented in §11).

**Current state: RESPECTED except for the sanctioned `ari_skill_memory` edge.** A
repo-wide grep for `ari_skill_memory` inside `ari-core/ari/` returns exactly the memory
edge (13 Python sites + one incidental TS *comment*, not an import):

```
ari-core/ari/memory_cli.py
ari-core/ari/cli/run.py
ari-core/ari/cli/commands.py
ari-core/ari/pipeline/verified_context.py
ari-core/ari/pipeline/orchestrator.py
ari-core/ari/agent/loop.py
ari-core/ari/memory/letta_client.py
ari-core/ari/memory/auto_migrate.py
ari-core/ari/viz/api_memory.py
ari-core/ari/viz/routes.py
ari-core/ari/viz/node_work_api.py
ari-core/ari/viz/checkpoint_lifecycle.py
ari-core/ari/viz/frontend/src/components/Settings/settingsConstants.ts   ← COMMENT only (line 36), not an import
```

No `ari-skill-benchmark`, `ari-skill-paper`, etc. package is imported by core. The one
skill core depends on is `ari_skill_memory`, and it is present in **13 core modules**,
not centralized behind a single seam.

**Classification.**
- The existence of the `ari_skill_memory` edge: **KEEP** (sanctioned — see §11), but
  the **13-site sprawl is REVIEW_REQUIRED → ADAPT**: those call sites all reach
  `ari_skill_memory.backends.get_backend`, so they should funnel through the existing
  `ari.memory.MemoryClient` ABC / `LettaMemoryClient` (`ari/memory/letta_client.py:27`)
  rather than importing the skill backend directly in `agent/loop.py`, `pipeline/`,
  `viz/`, `cli/`. Collapsing the edge to ~1–2 seams is what makes the "single sanctioned
  exception" enforceable by a checker.
- The rest of B2: **KEEP** — encode "no `import ari_skill_*` in `ari-core/ari/**` except
  `ari_skill_memory`" as a guard rule.

**Note on the `settingsConstants.ts:36` hit:** it is a source *comment* referencing
`ari_skill_memory.MemoryConfig` for documentation, not a Python/TS import. The checker
must scope to import statements to avoid flagging it.

---

## 5. Boundary B3 — viz route handlers stay thin (service / adapter / schema / store)

**Target rule.** `ari/viz/` HTTP handlers should parse the request, call a service, and
serialize a response. File I/O, subprocess spawning, business logic, and internal `ari.*`
access belong in **service / adapter / schema / store** layers behind the handlers.

**Current state: HEAVILY VIOLATED.** The viz backend is 27 Python files built directly on
stdlib `http.server` (no Flask/FastAPI). Routing is a **single ~86-branch if/elif chain**
in `_Handler.do_GET` (`routes.py:144-1026`) plus ~51 branches in `do_POST`
(`routes.py:1028-1188`). Concrete thin-route violations:

- The `GET /state` handler is **inlined at `routes.py:219-666` (~450 lines)** doing dozens
  of `Path.exists()`/`read_text()`/`json.loads()` calls, glob scans, YAML profile merging,
  `cost_trace.jsonl` tail-parsing, and reaching into `_st._last_proc.poll()` +
  `ari.pidfile`. This is a service, not a route.
- **Subprocess spawning inside handlers:** `api_experiment._api_run_stage` (Popen),
  `_api_launch`, `api_orchestrator._api_launch_sub_experiment` (Popen),
  `api_process` (`Popen`/`pkill`/`pgrep`), `api_memory` (`subprocess.run`).
  `_api_run_stage` also inlines `.env` parsing + 15+ `ARI_*` env mappings — pure business
  logic in a route helper.
- **Direct internal (non-`ari.public`) imports in handlers:** `ari.paths.PathManager`,
  `ari.checkpoint`, `ari.config.auto_config`, `ari.llm.client.LLMClient`, `ari.clone`,
  `ari.orchestrator.web_provenance`, `ari.container`, `ari.pidfile`, and
  `ari_skill_memory.backends.get_backend` (`routes.py:203-205`).
- **No schema/DTO/validation layer:** POST bodies are raw `bytes` → `json.loads` per
  handler; responses are ad-hoc dicts with two coexisting conventions (`{"ok":…}` vs
  `{"error":…}`) and status smuggled via `r.pop("_status", 200)` (`routes.py:1047-1057`).
- **Mutable module globals as the store:** `state.py` (`_checkpoint_dir`, `_last_proc`,
  `_running_procs`, `_launch_config`, `_clients`, `_sub_experiments`) and PaperBench's
  in-memory `_JOBS`/`_JOBS_LOCK` (`api_paperbench.py:496-497`, lost on restart).
- **Abandoned intent already present:** `api_wizard.py:30` defines an unused
  `WIZARD_ROUTES` dict — a partial declarative route table. `api_state.py` (76 lines) is
  already a thin re-export facade (Phase 3B) forwarding to `checkpoint_finder`,
  `state_sync`, `checkpoint_api`, `ear`, `file_api`, `checkpoint_lifecycle`,
  `node_work_api` — evidence the "route → module" split has started.

**Classification: ADAPT (large).** Introduce, behind the frozen endpoint paths:
- a **StateService** owning the 450-line `/state` builder;
- a **LaunchService/adapter** owning subprocess + env orchestration
  (`_api_run_stage`/`_api_launch`/`_api_launch_sub_experiment`);
- a **FileService** owning file serving + the per-handler path-traversal guards
  (currently inconsistent: `file_api` uses `relative_to`, `/codefile` uses substring
  `"checkpoints" in str(p)` at `routes.py:692`);
- request **schema/DTO** + a `_json` response wrapper unifying `{ok}`/`{error}` and
  killing the `_status` smuggle;
- **adapters** so handlers depend on `ari.public.*` instead of `ari.paths`/`ari.checkpoint`
  /`ari.llm.client`/`ari_skill_memory` directly.

**KEEP** the endpoint paths and JSON response shapes (frozen dashboard-API contract) and
the existing `api_state.py` facade pattern (extend it, do not revert it). The `if/elif`
dispatch itself is **MERGE** into a single route registry (finishing `WIZARD_ROUTES`).

---

## 6. Boundary B4 — dashboard frontend depends on DTO/TS types, not backend internals

**Target rule.** `ari/viz/frontend/` React code depends only on (a) the typed HTTP client
`services/api.ts` and (b) the shared **DTO/TS type** declarations. It must not encode
backend Python internals.

**Current state: RESPECTED at the type seam.** `frontend/src/services/api.ts` (863 LOC)
is the single typed HTTP client (`API_BASE = ''`, generic `get<T>`/`post<T>` helpers) and
imports its types from a dedicated barrel: `import type { AppState, Checkpoint,
CheckpointSummary, ResourceMetrics, Settings, WorkflowData, WorkflowStage } from
'../types'`. The DTO layer physically exists at `frontend/src/types/index.ts` (7909 bytes,
with its own `README.md`), and per-feature type modules exist (e.g.
`Results/resultTypes.ts`). The frontend talks to the backend **only over HTTP/JSON**; no
Python module is importable from TS. The one `ari_skill_memory` string in
`Settings/settingsConstants.ts:36` is a **comment** documenting field parity with Letta's
SDK, not a coupling.

**Residual risk (not a hard violation):** the DTO types in `src/types/index.ts` are
hand-authored and are **not generated from the backend response shapes**, so they can
silently drift from `api_*.py` dicts (which themselves have no schema). This is the
frontend-facing symptom of B3's missing DTO layer.

**Classification: KEEP** the `api.ts` + `src/types` seam. **REVIEW_REQUIRED** on drift:
once B3 introduces backend response schemas, a later subtask should decide whether TS DTOs
are generated from them (a `check_viz_api_schema.py` guard, listed as a missing checker,
would compare the two). Separately, the **committed `node_modules/` under
`frontend/`** is a git-hygiene issue (vendored deps tracked) — **DELETE_CANDIDATE** for a
hygiene subtask, unrelated to the dependency direction.

---

## 7. Boundary B5 — evaluator independent of CLI / dashboard / file layout

**Target rule.** `ari/evaluator/` scores nodes given inputs; it must not import the CLI,
the dashboard, or hard-wired workspace file paths, and it must be drivable in isolation.

**Current state: MOSTLY RESPECTED, with a provider-routing leak.** The evaluator package
(3 files, 1261 LOC) has no `ari.cli` / `ari.viz` imports. `LLMEvaluator`
(`llm_evaluator.py:240`) is the single concrete evaluator; a `@runtime_checkable`
`Evaluator` Protocol already exists (`ari/protocols/evaluator.py:18-40`) and
`LLMEvaluator` satisfies it structurally. Composites are pure functions in a registry
`_COMPOSITES` (`llm_evaluator.py:165-170`) keyed to the `EvaluatorConfig.composite`
Literal (`config/__init__.py:212`). Axes are injected via `dynamic_axes.build_axes_for_run`
and wired at the composition root `core.py:195-202`. So the evaluator is decoupled from
CLI/dashboard and takes its inputs by argument, not by globbing the workspace.

**One real leak:** `LLMEvaluator.evaluate` calls `litellm.acompletion` **directly**
(`llm_evaluator.py:585`), passing `api_base` by hand and relying on the global litellm
monkeypatch for provider routing — it **bypasses `LLMClient`/`resolve_litellm_model`**.
This is a B6 crossing (evaluator reaching around the model-backend seam), not a
CLI/dashboard/file-layout one.

**Classification: KEEP** the evaluator↔CLI/dashboard independence and the existing
`Evaluator` Protocol (**KEEP**, and adopt it at call sites so `build_runtime` accepts the
Protocol, not the concrete class). **ADAPT** the direct-`litellm` call to go through the
model backend (see B6). No file-layout coupling to fix here.

---

## 8. Boundary B6 — model backend independent of dashboard / evaluator internals

**Target rule.** The LLM/model backend (`ari/llm/`, `ari/cost_tracker.py`) exposes a
stable client + provider-routing seam and does not import the dashboard or reach into
evaluator internals; conversely, all model calls flow *through* the backend.

**Current state: BACKEND IS CLEAN; CALLERS BYPASS IT.** `ari/llm/` (4 files, 1234 LOC)
has a single routing source of truth `resolve_litellm_model` (`routing.py:37`) and a
concrete `LLMClient` (`client.py:26`) that wraps `litellm.completion`, forwards
`node/phase/skill` via `metadata`, and detects the cli-shim target. It does **not** import
`ari.viz` or `ari.evaluator`. The dependency direction is therefore respected *from* the
backend outward.

The violation is **inbound**: the evaluator calls `litellm` directly (§7,
`llm_evaluator.py:585`), so a second, uncontrolled model-call path exists that does not go
through `LLMClient`. Related backend-shape facts (for downstream subtasks, not boundary
violations): no `BaseModelBackend` ABC exists (`LLMClient` is concrete); no retry/backoff
anywhere; timeouts are hardcoded (`client.py:180` `timeout=1800`); cost capture is a
**process-wide litellm monkeypatch** installed at `cost_tracker.init()`
(`cost_tracker.py:288, 312-326`).

**Classification.**
- Backend→dashboard/evaluator independence: **KEEP.**
- Evaluator's direct `litellm` call: **ADAPT** — route through `LLMClient` so
  `resolve_litellm_model` is the only provider-routing decision (removes reliance on the
  global monkeypatch for correctness).
- Introduce `BaseModelBackend` Protocol (roadmapped in `protocols/__init__.py`):
  **REVIEW_REQUIRED** (design), then **ADAPT** call sites — but the concrete `LLMClient`
  name and `ari.public.llm.LLMClient` export are frozen, so this is Protocol-*adds-behind*,
  not a rename.
- The global cost-tracker monkeypatch: **REVIEW_REQUIRED** (process-wide side effect;
  changing it risks the cost-file format contract).

---

## 9. Boundary B7 — pipeline separated by stage interface

**Target rule.** The post-BFTS pipeline runs stages through a **stage interface** so that
each stage is independently testable and the driver is pure scheduling; there is exactly
one driver.

**Current state: NO STAGE INTERFACE EXISTS.** The pipeline is 100% data-driven from
`ari-core/config/workflow.yaml` (629 LOC, ~30 stages). A "stage" is a plain `dict`; there
are **no stage classes, no registry, no state object**. Execution is a single imperative
while-loop in `ari/pipeline/orchestrator.py:548-911` (`run_pipeline`, a 913-LOC function)
that hand-rolls per stage: `disabled_tools` skip, `depends_on` resolution, `skip_if_exists`,
`{{var}}` template resolution (regex, not Jinja — `yaml_loader.py:84`), tool-specific
fallback injection, dispatch, output persistence with **type-sniffing side-effects**
(`.tex`→`result["latex"]`, `.pdf`→copy-if-distinct, `:757-801`), and `loop_back_to` cursor
rewind. Two dispatch modes are forked by `if stage_cfg.get("react")`
(`stage_runner.py`): a subprocess-MCP path (default) and a dormant ReAct path
(`grep -c 'react:' config/workflow.yaml == 0` — confirmed unused in the shipped config).

**Worse: the driver is duplicated across the boundary.** `viz/api_paperbench_worker.py:168`
defines a second `_run_pipeline` (thread `:313`) — a parallel pipeline runner in the
dashboard layer. And there are **core→viz** and file-layout crossings inside the pipeline:
`cli/lineage.py:151` imports `viz.api_orchestrator._api_launch_sub_experiment`
(**core depends on viz** — confirmed by grep), and `viz/api_publish.py`/`viz/ear.py` call
`ari.publish`/`ari.clone` directly. Hardwired filenames (`nodes_tree.json`,
`science_data.json`, `idea.json`, `full_paper.tex`, …) and duplicated `config/workflow.yaml`
discovery appear in `core.py:252-259`, `orchestrator.py:328-336`, `cli/lineage.py:57-60`.

**Classification: ADAPT / MERGE.**
- Define a `BasePipelineStage` interface (`resolve_inputs / should_skip / run /
  persist_outputs / evaluate_loopback`) with `SubprocessMCPStage` and `ReActStage`
  subclasses replacing the `if stage_cfg.get("react")` fork: **ADAPT** (behavior-preserving;
  `workflow.yaml` schema stays a frozen config format).
- Collapse `run_pipeline` and `viz/api_paperbench_worker._run_pipeline` into one
  `BaseWorkflowDriver`: **MERGE**.
- The `cli/lineage.py → viz.api_orchestrator` edge is a **core→viz inversion**:
  **ADAPT** — invert via a callback/port so `viz` supplies the launcher, not the reverse.
- Dormant ReAct path + the second, cleaner generic ReAct loop in
  `ari/agent/react_driver.py` (442 LOC, used by `pipeline/stage_runner.py:143`) vs
  `ari/agent/loop.py`: **REVIEW_REQUIRED** then **MERGE** (unify the two ReAct
  implementations).

---

## 10. Boundary B8 — storage responsibilities (artifact / checkpoint / trace / workspace)

**Target rule.** Four storage responsibilities are separated behind clear owners:
**checkpoint** (run state/format), **artifact** (curated publishable bundles),
**trace** (per-call cost/telemetry logs), **workspace** (transient run scratch). Callers
resolve paths through an owner, not by re-deriving `__file__`-relative paths.

**Current state: RESPONSIBILITIES EXIST BUT ARE SCATTERED / DUPLICATED.**

| Responsibility | Current owner(s) | Evidence / issue |
|---|---|---|
| Checkpoint | `ari/checkpoint.py`, `ari/paths.py`, `ari/public/paths.py:PathManager`, `ari/migrations/` | Root-level `checkpoints/` coexists with `workspace/checkpoints/<ts_slug>/` — the root dir "appears legacy." |
| Artifact (EAR) | HTTP artifact registry `ari/registry/` (5 files, FastAPI, content-addressed sha256[:16]) + `ari/publish/` backends | **Naming trap:** `ari/registry/` is an *artifact* registry, NOT a DI/component registry. |
| Trace | `ari/cost_tracker.py` → `cost_trace.jsonl`; viz writes `viz_access.jsonl` per request (`routes.py:69-74`) | Trace paths hard-coded at call sites; cost trace read again inline in `/state`. |
| Workspace | `workspace/{checkpoints,experiments,staging}/`, `ari/container.py`, `ari/env_detect.py` | Hardwired filenames threaded manually through the pipeline (see B7). |

The core defect is **path discovery duplication**: `config/workflow.yaml` is re-derived by
parent-hopping `__file__` in at least three places (`core.py:252-259`,
`orchestrator.py:328-336`, `cli/lineage.py:57-60`), and hardwired output filenames are
spread across the pipeline.

**Classification: ADAPT.**
- Introduce a single `WorkflowLocator` + `OutputSink`/path registry (per B7) so the four
  storage responsibilities each have one resolver; callers stop re-deriving paths:
  **ADAPT** (path *formats* and checkpoint format are frozen contracts — only the
  resolution seam changes).
- Root-level `checkpoints/` vs `workspace/checkpoints/`: **REVIEW_REQUIRED** — confirm
  the root dir is legacy before any **MOVE_TO_LEGACY**; migrations under
  `ari/migrations/` and the v0.5.0 checkpoint-scoping already exist, so this must not
  break the checkpoint format.
- Rename clarity for `ari/registry/` (artifact registry) vs any future DI registry:
  **REVIEW_REQUIRED** (documented naming collision; `ari/registry/` is wired into the CLI
  at `cli/__init__.py:97-98`, a frozen `registry` subcommand — do not rename the command).

---

## 11. The single sanctioned exception — ari-core → `ari_skill_memory`

This is the **one** allowed `ari-core → ari-skill-*` edge and is documented explicitly so
the B2 checker whitelists it precisely.

**What it is.** `ari-core` imports `ari_skill_memory.backends.get_backend` — the first and
only core→skill dependency (introduced v0.6.0). It is **deliberately not declared** in
`ari-core/pyproject.toml` `dependencies` (comment lines 27–31); it is editable-installed
by `setup.sh` (`pip install -e ari-skill-memory` **before** `ari-core`, as enforced in
`.github/workflows/refactor-guards.yml`). The skill is not on PyPI.

**The interface.** Core does not (and should not) talk to the skill's MCP tool surface for
this edge; it consumes the **library API** `ari_skill_memory.backends.get_backend(...)`,
which returns a `MemoryBackend` (ABC at
`ari-skill-memory/src/ari_skill_memory/backends/base.py:8`, with `in_memory`/`letta`
impls). On the core side this is wrapped by the `MemoryClient` ABC
(`ari/memory/client.py:8`) and `LettaMemoryClient` (`ari/memory/letta_client.py:22`, which
does the `get_backend` import at `:27`). The coupling is **bidirectional at the edge**:
`ari-skill-memory/.../letta_backend.py:157` lazily imports back `ari.public.cost_tracker`
(that direction is a normal, sanctioned B1 skill→`ari.public.*` use).

**The problem to fix (without breaking the exception).** The `get_backend` import is
sprawled across **13 core sites** (§4), several of which are in layers that should not
touch it directly (`agent/loop.py:1047`, `pipeline/`, `viz/`). Target: funnel all 13
through the `MemoryClient` seam so the sanctioned exception is a **single, auditable edge**
(ideally only `ari/memory/*`), which is what lets the checker assert "exactly one core→skill
package, reached through exactly one module."

**Classification.** The edge itself: **KEEP** (sanctioned). The 13-site sprawl: **ADAPT**
(centralize behind `ari.memory.MemoryClient`). The two divergent memory abstractions
(core `MemoryClient` ABC vs skill `MemoryBackend` ABC, which do not share types):
**REVIEW_REQUIRED** — confirm whether the divergence is intentional before any **MERGE**.

**Checker rule (026).** Allowlist = `ari-skill-memory` package name `ari_skill_memory`,
reached from `ari-core/ari/**`. Every *other* `import ari_skill_*` in `ari-core/ari/**` is
a hard failure.

---

## 12. Boundary B9 — long prompts externalized, not inline

**Target rule.** Prompt text longer than a trivial one-liner lives in versioned template
files loaded by a loader, not as inline string literals inside logic modules.

**Current state: PARTIALLY EXTERNALIZED.** The externalization mechanism exists and is
used: `ari/prompts/` has a loader (`_loader.py`, exposed as `PromptLoader` and re-exported
via `ari/protocols/__init__.py`), and `.md` templates already live under
`ari/prompts/{agent/system.md, evaluator/*.md, orchestrator/*.md, pipeline/*.md,
viz/*.md}`. Two skills carry their own prompt trees (`ari-skill-paper-re/src/prompts/`,
`ari-skill-replicate/src/prompts/`). **This mechanism is KEEP.**

But **heavy inline prompt/context construction remains** in the largest logic files:
- `ari/orchestrator/bfts.py` loads templates from `prompts/orchestrator/*.md` (`:475-483`,
  `:553-562`, `:743-760`) yet still hand-builds large context blocks inline
  (`expand` `:604-760`; candidate descriptions `:451-470`, `:537-550`).
- `ari/agent/loop.py` assembles the system prompt inline (`:489-554`) and root/child user
  content (`:570-621`) plus `build_working_context_messages` (`:164-355`).
- Large `server.py` files (`ari-skill-paper` 2956 LOC, `ari-skill-transform` 2465,
  `ari-skill-evaluator` 983) and `pipeline`/`evaluator` modules are flagged as likely
  holding inline prompts, to be inventoried by a `check_prompts.py` guard (does not exist).

**Classification: ADAPT.** Move the remaining inline context/prompt assembly into
`PromptLoader`-loaded templates + a `BFTSPromptBuilder`/`PromptAssembler` (the context
*serialization* can stay in code, but the natural-language scaffolding should move to
`.md`). Prompt *content* is not an external contract, so this is internal **ADAPT** with
no compatibility fence — but changes may shift model behavior, so pair with regression
tests. A `check_prompts.py` (missing checker) enforces "no NL block over N lines inline."

---

## 13. Boundary B10 — `scripts/` limited to quality / static-analysis / report

**Target rule.** `scripts/` holds only quality gates, static analysis, and
report/documentation tooling — never runtime/business logic that the app imports.

**Current state: MOSTLY RESPECTED.** Existing `scripts/` content is docs/quality tooling:
`scripts/docs/check_*` (doc links, doc sources, i18n JS, README parity, ref coupling,
report cochange, site i18n, translation freshness) + `readme_sync.py`,
`git-hooks/pre-commit`, `run_all_tests.sh`, `gpu_ollama_monitor.sh`, `build_pb_images.sh`,
and the `sc_paper_*` dogfood drivers. None of these is imported by `ari-core/ari/**` at
runtime (they are invoked as processes). The dashboard *shells out* to some of them, but
does not import them as modules.

**Gaps (design new checkers as subtasks — do NOT implement now):**
`check_complexity.py`, `check_import_boundaries.py` (subtask 026),
`check_docs_source_sync.py` (**note: overlaps the existing
`scripts/docs/check_doc_sources.py`** — MERGE, don't duplicate), `check_directory_policy.py`,
`check_public_api_contracts.py`, `check_viz_api_schema.py`, `check_prompts.py`,
`check_dashboard_ux.py`, `analyze_references.py`, `check_dead_code.py`,
`generate_quality_report.py`. Tooling availability constrains design: **`radon` is NOT
installed** (so `check_complexity.py` must use an available analyzer or vendor its own),
**`ruff` IS available**, `python compileall`/`pytest` available, node+npm available
(**no pnpm**).

**Classification: KEEP** the current `scripts/` scope. **REVIEW_REQUIRED** on the two
dogfood drivers (`sc_paper_dogfood.py`, `sc_paper_stage23_chain.py`) — confirm they are
tooling, not smuggled runtime. New checkers: **ADAPT** (design), with
`check_docs_source_sync.py` vs `check_doc_sources.py` explicitly a **MERGE**.

---

## 14. Boundary B11 — `.github` runs `scripts/check_*` in staged warning→regression→strict

**Target rule.** CI invokes the `scripts/check_*` guards through a **staged severity
ladder**: (1) *warning* (report only, never fail), (2) *regression* (fail only on
newly-introduced violations vs `main`), (3) *strict* (fail on any violation). This lets a
new guard land without blocking unrelated PRs and ratchet up as debt is paid down.

**Current state: STAGING NOT PRESENT; the diff-vs-main ratchet pattern EXISTS in one
guard.** There are 5 workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`,
`readme-sync.yml`, `refactor-guards.yml`). `refactor-guards.yml` already implements a
*regression-style* guard: it **diffs against `main`** and fails on **new** `~/.ari/`
references outside `migrations/`, plus a no-`$HOME/.ari/`-writes-during-pytest assertion —
this is exactly the "regression mode" shape, applied to one rule. `docs-change-coupling.yml`
is the only workflow whose text mentions warning/regression/strict-adjacent wording. There
is **no shared staged-mode harness** and **no** wiring of the (not-yet-existing)
`scripts/check_import_boundaries.py` / `check_*` guards into CI. Absent scaffolding:
`ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md`, `dependabot.yml`, `CODEOWNERS`,
`.github/actions/`.

**Classification: ADAPT (add, don't rewrite).** Design a single staged-mode convention
(e.g. `CHECK_MODE=warning|regression|strict` env consumed by each `check_*` script), reuse
`refactor-guards.yml`'s diff-vs-`main` technique for regression mode, and add a new
workflow (or job) that runs the boundary/quality checkers at the appropriate stage per
rule. **Do NOT rewrite the 5 existing workflows** — they are the frozen "scripts called by
`.github/workflows`" contract; extend alongside them. Each new checker enters at *warning*,
graduates to *regression* once the seed violations (B1's 7 edges, B2's sprawl) are fixed,
and reaches *strict* when the debt is zero.

---

## 15. Enforcement roadmap — subtask 026 (import-boundary checker)

`scripts/check_import_boundaries.py` **does not exist yet**; it is the primary enforcement
artifact for boundaries **B1, B2, and the §11 exception**, and is the referenced subtask
026 for this report. Design constraints grounded in the facts above:

1. **Allowlist model.** For `ari-skill-*/`: permit `import`/`from` targeting only
   `ari.public.*` and `ari.protocols.*`; flag any other `ari.<segment>`. Seed failing set
   (must all be caught): the 7 edges in §3's table.
2. **Core→skill rule.** For `ari-core/ari/**`: forbid `import ari_skill_*` **except**
   package `ari_skill_memory` (§11). Prefer to additionally restrict the allowed
   `ari_skill_memory` import to `ari/memory/**` once B2's ADAPT lands, so the exception is
   a single seam.
3. **AST, not grep.** Must parse import statements (skip the `settingsConstants.ts:36`
   comment-style false positive and the `try/except ImportError` guard blocks — those are
   still real imports and should be flagged).
4. **Direction checks beyond skills.** Also assert **no `ari-core → ari.viz`** from CLI/core
   (catches `cli/lineage.py:151`) and **no `ari.viz` handler → non-`ari.public` core**
   (catches B3's direct internal imports) — these can be separate rules in the same tool or
   split into `check_public_api_contracts.py` / `check_viz_api_schema.py`.
5. **Staged rollout (B11).** Ships in *warning* mode first; the seed violations are fixed
   under the B1/B2/§11 ADAPT items; then flip to *regression*, finally *strict*.
6. **Contract safety.** The tool only *reads*; the fixes it drives must widen
   `ari.public.*` (backward-compatible) rather than move private modules, preserving the
   frozen skill→core interface and MCP tool contracts.

---

## 16. Boundary status summary

| # | Boundary | Current state | Evidence anchor | Primary classification |
|---|---|---|---|---|
| B1 | skill → only `ari.public.*` | **Violated** (4 edges + 3 private fallbacks) | idea:614, paper-re:146, transform:681/2083/2433/2451, coding:569/583, hpc/slurm:211 | ADAPT (widen `ari.public.*`) |
| B2 | core ↛ skill (except memory) | **Respected** except sanctioned memory edge; edge is sprawled | grep `ari_skill_memory` = 13 core sites | KEEP + ADAPT (centralize) |
| B3 | viz routes thin | **Heavily violated** | routes.py:219-666, 144-1188; state.py globals | ADAPT (services/DTO/store) |
| B4 | frontend → DTO/TS types | **Respected**; drift risk | api.ts imports `../types`; `types/index.ts` | KEEP + REVIEW_REQUIRED |
| B5 | evaluator ⟂ CLI/dashboard/layout | **Respected**; one provider leak | llm_evaluator.py:585 | KEEP + ADAPT (route via LLMClient) |
| B6 | model backend ⟂ dashboard/evaluator | **Backend clean; callers bypass** | routing.py:37, client.py:26; llm_evaluator:585 | KEEP + ADAPT |
| B7 | pipeline stage interface | **Absent** (god-loop + dup driver) | orchestrator.py:548-911; api_paperbench_worker:168; cli/lineage:151 | ADAPT + MERGE |
| B8 | storage responsibilities | **Scattered/duplicated** | 3× workflow.yaml discovery; root vs workspace checkpoints | ADAPT + REVIEW_REQUIRED |
| B9 | prompts externalized | **Partial** | prompts/ loader used; inline in bfts.py/loop.py | ADAPT |
| B10 | scripts = quality/analysis/report | **Mostly respected**; checkers missing | scripts/docs/check_*; 11 missing | KEEP + ADAPT |
| B11 | CI staged warning→regression→strict | **Not staged**; ratchet exists in 1 guard | refactor-guards.yml diff-vs-main | ADAPT (add) |
| §11 | core → `ari_skill_memory` (sanctioned) | **Allowed**; 13-site sprawl | pyproject.toml:27-31; letta_client.py:27 | KEEP + ADAPT |

---

## 17. Sequencing note for implementation subtasks

Recommended order so each boundary fix lands behind a green guard:

1. **026 checker in *warning* mode** (this report's dependency) — makes B1/B2 measurable.
2. **B1 ADAPT** (widen `ari.public.*` with `lineage`/`clone`/`publish`/`node_selection`
   shims; repoint 7 skill edges) — smallest, contract-widening only.
3. **§11 / B2 ADAPT** (funnel the 13 `ari_skill_memory` sites through `MemoryClient`).
4. **B3 ADAPT** (viz service/DTO/store extraction) → unblocks **B4** DTO generation.
5. **B7/B8 ADAPT+MERGE** (stage interface, single driver, `WorkflowLocator`/`OutputSink`)
   → removes the core→viz inversion and path duplication.
6. **B5/B6 ADAPT** (evaluator through `LLMClient`; `BaseModelBackend` Protocol).
7. **B9 ADAPT** (prompt externalization), **B10** (new checkers), then **B11** flip each
   guard warning → regression → strict as its seed violations reach zero.

All items preserve the §1.4 frozen contracts; where a fix would touch one, it ships a
compatibility adapter (widened `ari.public.*`, retained CLI/MCP names, unchanged file
formats) rather than a breaking rename or removal.

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
