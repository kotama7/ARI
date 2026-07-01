# 010 — Contract Preservation Policy

> **Status:** Planning (no runtime code changes). This document enumerates the
> contracts the v0.9.0+ refactor must preserve, classifies each surface, and
> defines the compatibility-adapter and limited-deprecation policies that later
> implementation phases MUST obey.
>
> **Scope note:** This is a policy/inventory document only. It does **not**
> modify any code, prompt, config, workflow, or directory. The only artifact it
> produces is this file.
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI` — git branch `main`,
> `ari-core` version `0.9.0` (`ari-core/pyproject.toml:7`). Planning date
> 2026-07-01.

## How to read this document

Each contract surface is classified with the master-prompt vocabulary:

| Tag | Meaning in this refactor |
|---|---|
| **KEEP** | Contract is correct as-is; preserve byte-for-byte behavior. |
| **ADAPT** | Internals may change, but a compatibility adapter must hold the external shape constant (see §10). |
| **MERGE** | Duplicated/triplicated surfaces to be consolidated behind one canonical definition without changing the observable contract. |
| **MOVE_TO_LEGACY** | Retain only as a back-compat shim / legacy path; not the going-forward surface. |
| **DELETE_CANDIDATE** | Removable once nothing depends on it; requires a dependency sweep first. |
| **REVIEW_REQUIRED** | Ambiguity that must be resolved by a human before any phase touches it. |

**Terminology discipline.** The word **"deprecated"** is reserved in this
document for *external* contracts only: the public Python API (`ari.public.*`),
the `ari` CLI surface, MCP tool contracts, the dashboard REST/WebSocket API, the
documented on-disk file formats, and the `ari-skill-* → ari-core` stable
interface. Internal-only code that we intend to retire is described with
**MOVE_TO_LEGACY** or **DELETE_CANDIDATE**, never "deprecated". This mirrors the
repo's own usage: `ari-core/ari/_deprecation.py` and the
`.github/workflows/refactor-guards.yml` `~/.ari/` guard are the sanctioned
mechanism, and they exist specifically to police *external*/legacy surfaces.

**No `sonfigs/`.** Several upstream planning prompts reference a `sonfigs/`
directory. It **does not exist** anywhere in the repo (`find -iname '*sonfig*'`
returns nothing). The real, confusable trio is `ari-core/ari/config/` (Python
code), `ari-core/ari/configs/` (packaged default data), and top-level
`ari-core/config/` (rubric/profile/workflow data). See §7.

**Existing enforcement.** Three contract-guard tests already exist and MUST stay
green through every phase:
`ari-core/tests/test_public_api_boundary.py` (public API surface),
`ari-core/tests/test_api_schema_contract.py` (dashboard response schemas),
`ari-core/tests/test_workflow_contract.py` (1606 LOC, workflow.yaml shape). The
contributor-facing reference docs under `docs/reference/` (`public_api.md`,
`internal_boundaries.md`, `rest_api.md`, `cli_reference.md`, `mcp_tools.md`,
`file_formats.md`, `configuration.md`, `environment_variables.md`, `skills.md`)
are the human-readable statement of these same contracts and are themselves
gated by the docs-sync workflows (see §9).

---

## 1. CLI Contracts

**Classification: KEEP (names/flags/env side-effects) + ADAPT (internal command
module layout).**

The console entry point is a single script — this is the load-bearing contract:

- `ari = ari.cli:app` (`ari-core/pyproject.toml:34`, `[project.scripts]`). The
  Typer app is `app = typer.Typer(name="ari")` in `ari-core/ari/cli/__init__.py`
  (175 lines). Documented in `README.md:214-215,318-328` and
  `docs/reference/cli_reference.md`.

The command tree below is a contract at the level of **command name + option
flag names + their environment-variable side-effects**. Internals were already
split into sibling modules in "Phase 3A" (`cli/run.py`, `cli/projects.py`,
`cli/commands.py`, `cli/bfts_loop.py`, `cli/lineage.py`, `cli/migrate.py`);
further internal reshaping is **ADAPT**-class as long as the surface below is
byte-stable.

Top-level commands (file:line of the callback):

| Command | Source | Contract-bearing options / side effects |
|---|---|---|
| `clone` | `cli/commands.py:53` (`cmd_clone`) | `ref`, `[dest]`; `--expect-sha256 --no-extract --registry --token` |
| `run` | `cli/run.py:168` | `experiment`; `--config --profile --virsci-live/--no-virsci-live --virsci-k --virsci-team-size --virsci-n-authors --virsci-n-papers` → sets `ARI_IDEA_VIRSCI_*` |
| `resume` | `cli/run.py:446` | `checkpoint_dir`; `--config` |
| `paper` | `cli/projects.py:61` | `checkpoint_dir`; `--experiment --config --rubric --fewshot-mode --num-reviews-ensemble --num-reflections` → sets `ARI_RUBRIC` / `ARI_FEWSHOT_MODE` / … |
| `status` | `cli/projects.py:171` | `checkpoint_dir` |
| `skills-list` | `cli/commands.py:143` | `--config` |
| `viz` | `cli/commands.py:169` | `checkpoint_dir`; `--port` (default 8765) |
| `projects` | `cli/projects.py:222` | `--checkpoints` |
| `show` | `cli/projects.py:284` | `checkpoint`; `--checkpoints-dir` |
| `delete` | `cli/commands.py:105` | `checkpoint`; `--checkpoints-dir --yes/-y` |
| `settings` | `cli/commands.py:196` | `--config --model --api-key --partition --cpus --mem` |

Sub-typers registered via `add_typer` (contract = group name + subcommands):

- `ari memory` (`memory_cli.py`): `migrate, backup, restore, start-local, stop-local, prune-local, compact-access, health`
- `ari ear` (`cli_ear.py`): `curate, status, publish, promote`
- `ari registry` (`registry/cli.py`): `serve` + nested `token` typer (`issue, revoke, list`)
- `ari migrate` (`cli/migrate.py`): `node-reports`

**Contract hazards to preserve deliberately (not "fix" silently):**

1. **`--help` ordering is a pinned contract.** `_reorder_commands_for_compat()`
   (`cli/__init__.py:148-170`) forces the canonical order
   `clone → run → resume → paper → status → skills-list → viz → projects →
   show → delete → settings` so `ari --help` stays byte-identical across the
   Phase-3A split. Any command-module refactor MUST keep this reorder (or
   reproduce its output). Classification: **KEEP**.
2. **Silent command-group drop on import failure.** The `memory`/`ear`/
   `registry` sub-typers load under broad `try/except Exception` guards
   (`cli/__init__.py:82-100`) that only log a warning. This is a robustness
   *hazard* (a broken import silently removes a whole command group), but the
   *contract* is that these groups appear when their deps are present.
   Classification: **REVIEW_REQUIRED** — tightening the guard is desirable but
   must not change which commands are visible under a healthy install.

**Env-var side effects are part of the CLI contract.** `run`/`paper` translate
flags into `ARI_*` environment variables consumed downstream; the canonical list
lives in `docs/reference/environment_variables.md`. Changing a flag→env mapping
is a breaking change.

---

## 2. Public Python API Contracts

**Classification: KEEP (every exported symbol) + ADAPT (re-export mechanism).**

`ari.public` is the **only** module surface `ari-skill-*` packages may import
from (`docs/reference/public_api.md`; enforced by
`ari-core/tests/test_public_api_boundary.py`). It is a thin re-export layer so
core can refactor the private `ari.<module>` implementations freely while the
skill-facing contract stays fixed. Introduced v0.7.1 (Phase 4).

Stable exported symbols per submodule (verified by reading each file):

| Submodule (file) | Exported (`__all__`) | Backed by |
|---|---|---|
| `public/claim_gate.py` (29 L) | `run_hard_gate`, `check_emission`, `classify_concept`, `scan_science_data`, `CONCEPT_INVARIANTS` | `ari.pipeline.claim_gate*` |
| `public/config_schema.py` (28 L) | `ARIConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LLMConfig`, `LoggingConfig`, `SkillConfig` | `ari.config` |
| `public/container.py` (11 L) | `from ari.container import *` (dynamic `__all__`) | `ari.container` |
| `public/cost_tracker.py` (11 L) | `from ari.cost_tracker import *` (docstring names `bootstrap_skill`/`record`/`init_from_env`) | `ari.cost_tracker` |
| `public/llm.py` (10 L) | `LLMClient` | `ari.llm.client` |
| `public/paths.py` (5 L) | `PathManager` | `ari.paths` |
| `public/run_env.py` (15 L) | `from ari.agent.run_env import *` (`capture_env`, `shell_capture_snippet`) | `ari.agent.run_env` |
| `public/verified_context.py` (15 L) | `render_grounded_block`, `write_verified_context`, `build_verified_context` | `ari.pipeline.verified_context` |

**Preserve these exact symbols.** A private implementation may move (e.g. the
`ari.pipeline.claim_gate` package could be reorganized) **only** if the re-export
in `ari/public/*.py` keeps resolving the same names. This is the canonical
ADAPT-via-re-export pattern (§10).

**Known gaps to handle carefully, not silently:**

- `ari/public/__init__.py` (28 L) is **docstring-only** — it re-exports nothing
  at package top level, so `from ari.public import cost_tracker` works but
  `from ari.public import bootstrap_skill` does not. The README/docs say "import
  from `ari.public.*`" (submodule-qualified), which is consistent. Adding
  top-level re-exports would be additive (**ADAPT**, non-breaking) but is
  **REVIEW_REQUIRED** because it changes what `dir(ari.public)` advertises.
- `ari/__init__.py` is **empty** (0 bytes) — there is no `ari.__version__`;
  version lives only in the manifest. Introducing `__version__` would be
  additive but must not shadow or reorder any existing import. **REVIEW_REQUIRED**.
- `ari/core.py:83 build_runtime` and `:235 generate_paper_section` are
  **internal** (used by the CLI), **not** part of `ari.public`. They are free to
  change (**ADAPT**, no external contract).

---

## 3. MCP Tool Contracts

**Classification: KEEP (tool names, `inputSchema`, result envelope,
fully-qualified naming) + MERGE (two divergent server idioms) +
REVIEW_REQUIRED (flat global namespace).**

ARI ships **14** `ari-skill-*` MCP servers, each `ari-skill-*/src/server.py`.
`ari-core` consumes them through `ari-core/ari/mcp/client.py` (484 L,
class `MCPClient`, the sole public symbol per `ari/mcp/__init__.py`). Catalogued
in `docs/reference/mcp_tools.md`, with `mcp.json` (next to each skill's
`pyproject.toml`) documented there as the source of truth for tool *names*.

**Client-side contract (must not break):**

- Discovery: `MCPClient.list_tools()` (`client.py:297`) →
  `[{name, description, inputSchema, skill_name}]`.
- Invocation: `MCPClient.call_tool()` (`client.py:336`) returns the envelope
  **`{"result": <text>}`** on success or **`{"error": <message>}`** on failure
  (`client.py:236-237`, `:383`, `:393`, `:422`). This two-key envelope is a hard
  contract consumed throughout `ari-core` and the dashboard.
- Fully-qualified naming for the Claude CLI subprocess:
  `to_claude_mcp_config()` (`client.py:437`) emits `mcp__<skill>__<tool>`
  (`client.py:482`). These qualified names are passed to `--allowedTools` and
  MUST stay stable.
- Timeout tiers are behavioral contract for long tools:
  `DEFAULT_TOOL_TIMEOUT=300`, `SLOW_TOOL_TIMEOUT=3600`,
  `VERY_SLOW_TOOL_TIMEOUT=13h`, `MAX_RETRIES=3` (`client.py`).

**Per-skill tool inventory (server.py LOC, framework):** benchmark (175,
FastMCP), coding (644, low-level `Server`), evaluator (983, `Server`), hpc (304,
`Server`), idea (775, FastMCP), memory (238, FastMCP), orchestrator (1043,
`Server`), paper (2956 — largest, FastMCP, 14 `@mcp.tool`), paper-re (1395,
FastMCP), plot (802, FastMCP), replicate (194, FastMCP), transform (2465,
FastMCP), vlm (355, FastMCP), web (712, FastMCP). Tool names are **bare
snake_case in one flat namespace** (`make_metric_spec`,
`claim_evidence_hard_gate`, `generate_ideas`, `add_memory`, `build_reproduce_sh`,
…). These names are the contract.

**Contract-relevant refactor items:**

1. **Two divergent server idioms — MERGE, contract-preserving.** 10 skills use
   `FastMCP` (`@mcp.tool()`, `mcp.run()`); 4 use low-level
   `mcp.server.Server` + `@server.list_tools()`/`@server.call_tool()` returning
   `list[TextContent(type="text", text=json.dumps(...))]` (coding, evaluator,
   hpc, orchestrator). Consolidating onto one idiom is desirable **only if** the
   emitted tool `name`, `inputSchema`, and wire result shape are unchanged. Do
   not change the return payload semantics while merging.
2. **Flat global tool namespace — REVIEW_REQUIRED.**
   `MCPClient._tool_registry` (`client.py:283`) maps `tool_name → skill.name`
   **globally**, so a cross-skill name collision silently clobbers (last skill
   wins). Any renaming/namespacing fix is a **breaking change to tool names** and
   must ship with a compatibility alias (§10) — it cannot be done silently.
3. **`mcp.json` drift — MERGE / REVIEW_REQUIRED (documentation contract).**
   `mcp.json` is documented as the name source of truth but is stale: memory
   advertises 4 tools vs 15 `@mcp.tool`; web 5 vs 9; paper 12 vs 14;
   coding/hpc/vlm/orchestrator list `[]`; **transform has no `mcp.json` at all**
   (only `skill.yaml`). Reconciling these files changes the *documented* surface,
   not the *runtime* tool names — but because `docs/reference/mcp_tools.md`
   treats `mcp.json` as canonical, updates must go through the docs-sync gate.
4. **Console-script inconsistency — DELETE_CANDIDATE (internal).** Only
   `ari-skill-replicate` and `ari-skill-paper-re` declare
   `[project.scripts] … = "server:main"`, and the loader launches skills by
   filesystem path (`python <skill>/src/server.py`), so these entries are unused.
   Removing them is internal cleanup (not "deprecation"); it does not touch any
   external contract. **REVIEW_REQUIRED** only to confirm no external tooling
   invokes them.

---

## 4. Dashboard API Contracts

**Classification: KEEP (endpoint method+path, response schemas, WS message
shape) + ADAPT (stdlib-`http.server` dispatch internals).**

The dashboard backend is `ari-core/ari/viz/` (27 py files). It runs on the
Python **stdlib `http.server`** (NOT Flask/FastAPI): `_DualStackServer`
(`server.py:82-96`) + a single `BaseHTTPRequestHandler` subclass `_Handler`
(`routes.py:77`). Routing is a manual `if/elif` chain on `self.path` inside
`do_GET` (`routes.py:144-1026`, ~86 branches) and `do_POST`
(`routes.py:1028-1188`, ~51 branches). The public REST surface is documented in
`docs/reference/rest_api.md` and consumed by the React frontend
(`services/api.ts`, 863 L) plus `websocket.py`.

**Contract A — endpoint method + path.** The endpoint families below are a
contract (the frontend hard-codes them; external integrations may call them).
Non-exhaustive but representative, grouped by owning module:

- **State/tree:** `GET /state` (the ~450-line inline builder,
  `routes.py:219-666`), `GET /memory/<node_id>`, `GET /codefile?path=`,
  `GET /api/models`, `GET /api/active-checkpoint`, `GET /api/experiment-detail`,
  `GET /api/resource-metrics`, `GET /api/lineage-decisions/<ckpt>`.
- **Checkpoints** (`checkpoint_api`, `checkpoint_lifecycle`, `file_api`,
  `node_work_api`): `GET /api/checkpoints`,
  `GET /api/checkpoint/<id>/{summary,memory,files,filetree,filecontent}`,
  `GET /api/checkpoint/<id>/file[/raw]`,
  `GET /api/checkpoint/<id>/paper.(pdf|tex)`,
  `GET /api/checkpoint/<id>/memory_access`, `POST /api/switch-checkpoint`,
  `POST /api/delete-checkpoint`, `POST /api/checkpoint/file/{save,delete}`,
  `POST /api/checkpoint/compile`, `POST /api/checkpoint/<id>/file/upload`.
- **Experiment** (`api_experiment`, 929 L): `POST /api/launch`,
  `POST /api/run-stage`, `GET /api/logs` (SSE).
- **Settings/workflow:** `GET|POST /api/settings`, `GET|POST /api/env-keys`,
  `GET|POST /api/workflow`, `GET /api/workflow/{default,flow}`,
  `POST /api/workflow/{flow,skills,disabled-tools}`, `GET /api/skills`,
  `GET /api/skill/<name>`, `GET /api/profiles`, `GET /api/rubrics`,
  `GET /api/scheduler/detect`, `GET /api/slurm/partitions`.
- **PaperBench** (`api_paperbench`, 813 L, `_worker`):
  `GET /api/paperbench/papers`, `GET /api/paperbench/arxiv/<id>`,
  `GET /api/paperbench/papers/<id>/license`,
  `POST /api/paperbench/papers/{import,<id>/delete,<id>/metadata}`,
  `POST /api/paperbench/run`, `POST /api/paperbench/cost-estimate`,
  `GET /api/paperbench/run/<jid>[/logs|/results|/report|status]`.
- **Tools/wizard** (`api_tools`): `POST /api/chat-goal`,
  `POST /api/config/generate`, `POST /api/upload`, `POST /api/upload/delete`,
  `POST /api/ssh/test`.
- **Orchestrator/memory/EAR/publish/fewshot/process/ollama:** the
  `api_orchestrator`, `api_memory`, `ear`, `api_publish`, `api_fewshot`,
  `api_process`, `api_ollama` families as inventoried in `docs/reference/rest_api.md`.

**Contract B — typed response schemas (guarded).** `test_api_schema_contract.py`
pins the always-present keys of the highest-traffic GET endpoints as a **subset**
(additive: extra/optional fields allowed). These are hard contracts:

| Endpoint | Frontend type | Always-present keys |
|---|---|---|
| `GET /state` | `AppState` | `running_pid, is_running, exit_code, running, pid, status_label`; `cost` is the `CostSummary` **object** (parsed `cost_summary.json`), not a number |
| `GET /api/settings` | `Settings` | full defaults dict (`llm_model, llm_provider, ollama_host, temperature, …`, nested `ors`); `{**defaults, **saved}` passthrough |
| `GET /api/checkpoints` | `Checkpoint[]` | `id, path, status, node_count, review_score, best_metric` (always `null`), `mtime` |
| `GET /api/checkpoint/<id>/summary` | `CheckpointSummary` | `id, path` (or `{error:"not found"}`); `reproducibility_report` is a parsed **object** (legacy: string) |

**Contract C — response conventions.** Two conventions coexist and both are
observed on the wire: `{"ok": bool, ...}` (launch/stage) and `{"error": str}`
with a non-2xx code (file APIs). Status codes are smuggled via
`r.pop("_status", 200)` (`routes.py:1047-1057`). `Access-Control-Allow-Origin: *`
is set at 8 GET sites; some inline handlers omit it (`routes.py:667-672`) — a
wire-behavior inconsistency. **REVIEW_REQUIRED:** unifying `{ok}` vs `{error}`
or normalizing CORS is a wire-behavior change and must be verified against
`services/api.ts`'s two error regimes (see §5) before any phase touches it.

**Contract D — WebSocket.** Single endpoint `ws://host:(port+1)/ws`
(`server.py:172-179`, `websocket.py`). On connect the server pushes one
`{"type":"update","data":<tree>,"timestamp":...}` snapshot, then ignores inbound
frames. Push updates originate from `state_sync._watcher_thread` (polls
`tree.json`/`nodes_tree.json` mtimes every 1s). Only ONE message `type`
(`update`) exists — that shape is the contract.

**Refactor latitude (ADAPT, non-breaking):** the internal dispatch may move from
the `if/elif` chain to a route registry (the abandoned `WIZARD_ROUTES` dict in
`api_wizard.py:30` shows prior intent); the 450-line `/state` builder may move
into a StateService; handlers may be wrapped so they depend only on
`ari.public.*` instead of the current direct internal imports
(`routes.py:203-205` imports `ari_skill_memory.backends.get_backend`, `ari.paths`,
`ari.checkpoint`, `ari.container`, `ari.pidfile`, etc.). All of this is allowed
**iff** endpoints A–D above stay identical on the wire.

---

## 5. Frontend Field Dependency Contracts

**Classification: KEEP (fields the FE reads from backend responses) +
REVIEW_REQUIRED (the two error regimes).**

The frontend (`ari-core/ari/viz/frontend/`, Vite 5 + React 18.3 + TS 5.5) is a
*consumer* of the §4 backend contracts. The binding surface is
`src/services/api.ts` (863 L, ~90 typed wrappers, `API_BASE=''` same-origin) and
`src/types/index.ts`. These field dependencies constrain what the backend may
rename/remove:

- **`Settings`** (35 fields, `types/index.ts:38-75`) — the flat object POSTed by
  `SettingsPage.tsx:235-260` (24 keys) and read across the UI. Backend
  `GET /api/settings` must keep returning these keys.
- **`AppState`** (`types/index.ts:87-129`) — note the backend adds JS-compat
  aliases `running` / `pid` / `llm_model` in addition to `running_pid` /
  `is_running`; both the canonical and alias fields are consumed and are a
  contract.
- **`NodeReport`** (`api.ts:124-153`), **`MemoryEntry` / `MemoryAccessEvent`**
  (`api.ts:53-104`), **`Checkpoint[]` / `CheckpointSummary`** — shapes pinned by
  `test_api_schema_contract.py` (§4 Contract B).

**Two error regimes — REVIEW_REQUIRED (real contract hazard).** `get`/`post`
**throw** on non-2xx (`api.ts:18-32`), but the PaperBench helpers `pbGet`/`pbPost`
**never throw** and instead return `{error}` bodies (`api.ts:787-799`, comment
780-785). Any backend response-shape unification (§4 Contract C) must preserve
*both* regimes or update both sides in lockstep.

**Nav/route mirror drift — REVIEW_REQUIRED.** Routing is a hand-rolled hash
router: `App.tsx:32-56` `parseHash()` + `PAGE_MAP` (12 top routes incl.
`paperbench/{import,run,results}`), mirrored by hardcoded `NAV_ITEMS` in
`Layout/Sidebar.tsx:12-23`. The `new → wizard` legacy alias is a KEEP contract
(external bookmarks may use `#new`). The Sidebar omitting `paperbench` is manual
drift, not a contract, but any route rename must update both mirrors.

**Out of scope for this policy (flagged, not owned here):** the raw-debug UI
surfaces (DetailPanel "Raw" tab dumping node JSON, `GET /api/env-keys` returning
secret values to the browser, GPU-monitor SLURM auto-resubmit guarded only by
`window.confirm`, `dangerouslySetInnerHTML` at `StepScope.tsx:137`) are UX/safety
concerns for a separate dashboard-UX document, not field-dependency contracts.
Hardcoded, stale-prone provider/model lists (`settingsConstants.ts:9-15`, e.g.
`gpt-5.2`, `claude-opus-4-5`) are data, not contract.

**Hygiene correction (fact-check).** The skeleton claim that `node_modules/` is
committed to git is **false in the current tree**: `git ls-files` matches 0
files under `node_modules`, and `.gitignore:113` ignores
`ari-core/ari/viz/frontend/node_modules/` (`:114` ignores `viz/static/dist/`).
`package-lock.json` (140 KB) *is* tracked. The only confirmable hygiene nit is
minor i18n key drift (`en.ts` 444 L vs `ja.ts`/`zh.ts` 441 L), which the
docs-sync `check_i18n_js.py` gate already watches.

---

## 6. Checkpoint / Output File Contracts

**Classification: KEEP (on-disk file names, JSON keys, precedence) + ADAPT
(directory consolidation behind PathManager) + MOVE_TO_LEGACY (root
`checkpoints/`).**

A checkpoint is a self-describing flat directory (~45 sibling files on a real
run), documented in `docs/reference/file_formats.md`. Path resolution is
centralized in `ari-core/ari/paths.py` (304 L, `PathManager`), re-exported
verbatim by `ari/public/paths.py`. JSON I/O is centralized in
`ari-core/ari/checkpoint.py` (197 L).

**Contract A — canonical file set (`META_FILES`, `paths.py:51-76`).** These
names are read/written by name and are a contract:
`experiment.md, launch_config.json, meta.json, tree.json, nodes_tree.json,
bfts_tree.json, results.json, idea.json, cost_trace.jsonl, cost_summary.json,
workflow.yaml, ari.log, .ari_pid, .pipeline_started, evaluation_criteria.json,
viz_access.jsonl, memory_access.jsonl, memory_access.summary.json,
node_report.json` + `*.log` + regex `memory_access.*.jsonl`.

**Contract B — JSON I/O + precedence (`checkpoint.py`).** `save_tree_json`
(`:49`), `save_nodes_tree_json` (`:59`), `save_results_json` (`:64`),
`load_tree_json` (`:74`), `load_nodes_tree_json` (`:80`), and the 3-tier
`load_nodes_tree()` (`:86`, precedence `tree.json → nodes_tree.json → newest
non-empty node_*/tree.json`) plus the throttled `save_tree_incremental()`
(`:150`, 1.0s thread-locked). The precedence order is a back-compat contract for
legacy per-node layouts.

**Contract C — env-var run pin.** `ARI_CHECKPOINT_DIR` is the single canonical
run pin (`paths.py:238-274`; `checkpoint_dir_from_env`, `from_checkpoint_dir`
walks up to the outermost `checkpoints/` ancestor). CLI hand-off at
`cli/commands.py:128`, `cli/run.py:280-283/538`, `cli/bfts_loop.py:378`. The
`ari-skill-memory` JSONL store lives at `{ARI_CHECKPOINT_DIR}/memory_store.jsonl`
(v0.5.0 checkpoint-scoped design; no more `~/.ari/`). This env var and path are a
cross-package contract.

**Consolidation latitude (ADAPT).** A proposed
`runs/<id>/{workspace,checkpoints,artifacts,traces,reports}` consolidation is
**permitted** because no runtime storage is git-tracked (`.gitignore` ignores
`checkpoints/`, `experiments/`, `workspace/`, `ari-core/{experiments,checkpoints}/`
at lines 26/31/70/83/84; `git ls-files` returns zero tracked files under any).
There is therefore **no git-migration cost** — only on-disk path resolution,
which must remain funneled through `PathManager` so old checkpoints still load.

**REVIEW_REQUIRED — workspace-root disagreement.** `config/__init__.py:588-592`
(`auto_config`) defaults the checkpoint dir to
`{repo_root}/workspace/checkpoints/{run_id}`, but shipped `ari-core/config/default.yaml:14,39`
still says `./checkpoints/{run_id}/` (root-level). The root `checkpoints/` dir
exists but is empty. **MOVE_TO_LEGACY** the root-level path once confirmed
nothing writes to it; resolve the default.yaml vs auto_config disagreement before
any path phase. `workflow.yaml` uses `{{checkpoint_dir}}/...` templating for ~40
output paths — those templates are a contract with `PathManager`.

**Unconfirmed (do not assume):** the exact `meta.json` / `launch_config.json`
key schemas were not opened here; treat them as opaque contracts until a schema
pass verifies them against `ari-core/ari/schemas/`.

---

## 7. Config File Contracts

**Classification: KEEP (file names, key paths, search precedence) +
REVIEW_REQUIRED (the config/configs/config trio naming).**

There is **no top-level `pyproject.toml`**; `ari-core/pyproject.toml` is the core
manifest. There is **no `sonfigs/`**. The confusable trio (all real, all
distinct roles):

| Path | Role | Key contents |
|---|---|---|
| `ari-core/ari/config/` | Python **code** | `finder.py` (146 L, workflow/profile YAML discovery; `package_config_root()` → `ari-core/config/`), `__init__.py` (Pydantic models + `auto_config()`), `README.md` |
| `ari-core/ari/configs/` | packaged **default data** + loader | `_loader.py` (58 L, `ConfigLoader` Protocol + `FilesystemConfigLoader`, `.yaml→.yml→.json`), `defaults.yaml` (only `models.lineage_decision_default: gpt-4o-mini`), `model_prices.yaml`, `README.md` |
| `ari-core/config/` | shipped **rubric/profile/workflow data** | `default.yaml`, `workflow.yaml` (23.6 KB), `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/{generic,nature,neurips,sc}.yaml`, `reviewer_rubrics/*.yaml` (23 venues), `reviewer_rubrics/fewshot_examples/neurips/*.json` |

**Contract A — typed config schema.** The Pydantic models
(`ARIConfig, LLMConfig, BFTSConfig, SkillConfig, CheckpointConfig, LoggingConfig,
EvaluatorConfig`) are re-exported through `ari.public.config_schema` (§2), so
their field names are an external contract. YAML key paths consumed by these
models are equally binding. Documented in `docs/reference/configuration.md`.

**Contract B — search precedence (`finder.find_workflow_yaml`,
`finder.py:60-100`).** Order:
`{checkpoint}/workflow.yaml|pipeline.yaml → {pkg}/profiles/{profile}.yaml →
{pkg}/default.yaml → {pkg}/workflow.yaml`. This four-tier fallback across two
directory trees is behavioral contract — reordering changes which config wins.

**Contract C — `workflow.yaml` shape** is pinned by
`ari-core/tests/test_workflow_contract.py` (1606 L). Any change to workflow node
structure must keep this test green.

**REVIEW_REQUIRED — the two "defaults" files.** `ari-core/config/default.yaml`
and `ari-core/ari/configs/defaults.yaml` are two unrelated files both named
"default(s)". Renaming either for clarity is desirable but is a
**documentation/discoverability change, not a runtime rename** — the loader
paths and README references must be updated in lockstep, and the confusable
directory names (`config/` vs `configs/`) are load-bearing import paths that
**cannot** be renamed without a compatibility shim (§10). Classification for the
directory names themselves: **KEEP** (renaming breaks every internal import);
propose only a documentation clarification, not a rename, in the refactor.

---

## 8. ari-skill-* to ari-core Contracts

**Classification: KEEP (sanctioned `ari.public.*` touchpoints + core→memory
edge) + ADAPT (make the contract explicit) + REVIEW_REQUIRED (4 boundary
violations).**

The sanctioned interface is documented in `docs/reference/internal_boundaries.md`
and `docs/reference/public_api.md`, enforced by `test_public_api_boundary.py`.
Its nature today: **lazy, optional, unpinned** — no skill lists `ari-core` in its
`pyproject` dependencies; every touch is an in-function
`try/except ImportError` import.

**Contract A — sanctioned `ari.public.*` consumption (KEEP).** Actual usage
verified across skills:

- `ari.public.cost_tracker` — near-universal (`bootstrap_skill` at top of every
  `server.py`): evaluator, idea, paper, paper-re, plot, replicate, vlm, web,
  transform, coding.
- `ari.public.claim_gate` — coding (`check_emission`), evaluator
  (`classify_concept`, `CONCEPT_INVARIANTS`, `run_hard_gate`), transform
  (`scan_science_data`).
- `ari.public.container` + `ari.public.run_env` — coding, hpc.
- `ari.public.verified_context.render_grounded_block` — paper.

Every symbol above is a two-way contract: skills depend on it AND core promises
to keep re-exporting it (§2).

**Contract B — inverse edge (KEEP, first core→skill dependency).** `ari-core`
imports `ari_skill_memory.backends.get_backend` at **~13 sites** (`memory_cli.py:49`,
`cli/run.py:537`, `cli/commands.py:129`, `pipeline/orchestrator.py:250`,
`pipeline/verified_context.py:74/76`, `agent/loop.py:1047`,
`viz/{checkpoint_lifecycle,api_memory,routes,node_work_api}.py`,
`memory/{letta_client,auto_migrate}.py`). Documented at `pyproject.toml:27` and
deliberately omitted from `dependencies` (editable-installed by `setup.sh`;
`.github/workflows/refactor-guards.yml` installs `ari-skill-memory` before
`ari-core`). The coupling is bidirectional: `letta_backend.py:157` lazily imports
`ari.public.cost_tracker`. The `get_backend` signature and the JSONL store path
(§6C) are the contract.

**REVIEW_REQUIRED — 4 confirmed boundary violations (import private ari-core).**
These bypass `ari.public.*` and MUST be routed through the public surface (adding
new `ari.public.*` re-exports where needed, §10) rather than left as-is:

1. `ari-skill-paper-re/src/server.py:146` → `from ari.clone import clone, CloneError`
2. `ari-skill-idea/src/server.py:614` → `from ari.lineage import …`
3. `ari-skill-transform/src/server.py:681/2083` → `ari.orchestrator.node_selection`;
   `:2433/2451` → `ari.publish.{publish,promote}`
4. Private fallbacks: coding → `ari.container` / `ari.agent.run_env`; hpc →
   `ari.agent.run_env` (these have a public path AND a private fallback; the
   fallback is the violation).

A future `check_import_boundaries.py` guard (not yet present) would flag these;
until it exists, treat the four as **REVIEW_REQUIRED** and do not add new private
cross-package imports.

**Manifest drift (MERGE, internal — not "deprecation").** Version values diverge
across a skill's own files: paper-re = 0.8.0 (`pyproject`) / 0.4.0 (`mcp.json`) /
0.5.0 (`skill.yaml`); evaluator 1.0.0 vs skill.yaml 0.4.1; replicate 0.2.0 vs
mcp.json 0.1.0. `requires-python` fragments across 3.10/3.11/3.13.
`ari-skill-orchestrator` has **no `pyproject.toml`** (only `src/requirements.txt`).
Consolidating versioning is internal hygiene; it touches no external contract as
long as tool names and the `ari.public.*` touchpoints are unchanged.

**Vendored trees (KEEP as-is).** `ari-skill-idea/vendor/virsci/` and
`ari-skill-paper-re/vendor/paperbench/` are git submodules injected onto
`sys.path` (`_vendor_path.py`). `_paperbench_bridge.py` (2376 L) re-exports
upstream `SimpleJudge`/`TaskNode` with no local fallback — preserving upstream
parity is itself a contract; do not fork these.

---

## 9. Docs / Examples Contracts

**Classification: KEEP (README usage + reference docs) + ADAPT (source-of-truth
front-matter) — gated by existing workflows.**

The documentation is a first-class contract in ARI: it is machine-checked by 5
GitHub workflows and mirrored in 3 languages. Any refactor that changes a cited
symbol/path MUST update the corresponding doc in the same PR or the gate fails.

**Contract A — README usage triple (KEEP).** `README.md` (+ `README.ja.md`,
`README.zh.md`) document the CLI usage (`ari run experiment.md`,
`ari run … --profile hpc`, the command table at `README.md:318-328`) and the
`ari.public.*` boundary (`README.md:81`). Parity across the three READMEs is
enforced by `scripts/readme_sync.py --check` (`.github/workflows/readme-sync.yml`).

**Contract B — reference docs (KEEP, source-linked).** `docs/reference/` files
carry YAML front-matter listing their `sources:` (implementation/test/config
paths) and a `last_verified` date. The load-bearing set for this policy:
`public_api.md`, `internal_boundaries.md`, `rest_api.md`, `cli_reference.md`,
`mcp_tools.md`, `file_formats.md`, `configuration.md`, `environment_variables.md`,
`skills.md`, `registry.md`, `rubric_schema.md`, `api_paperbench.md`. When a
refactor moves a cited source, the front-matter path must move with it.

**Contract C — docs-sync gates (must stay green).** Scripts invoked by workflows
(these are themselves a contract — the workflow calls them by path, so they must
keep their CLIs):

- `.github/workflows/docs-sync.yml`: `scripts/docs/check_doc_sources.py`,
  `check_i18n_js.py`, `check_site_i18n.py`, `check_doc_links.py [--html-only]`,
  `check_readme_parity.py`, `report/scripts/check_i18n.py`,
  `check_translation_freshness.py`, `scripts/docs/sync_report_pdf.sh --check`.
- `.github/workflows/docs-change-coupling.yml`:
  `scripts/docs/check_report_cochange.py`, `check_ref_coupling.py`.
- `.github/workflows/readme-sync.yml`: `scripts/readme_sync.py --check`.
- `.github/workflows/pages.yml`: `scripts/docs/sync_report_pdf.sh`,
  `scripts/docs/assemble_site.sh`.

**Contract D — i18n mirroring (KEEP).** VitePress site under `docs/` ships
`en` (default) + `ja/` + `zh/`; the frontend ships `src/i18n/{en,ja,zh}.ts`.
Translation freshness/parity is gated (Contract C). New docs/UI strings must land
in all three locales (or carry the sanctioned freshness marker).

**Note on `check_docs_source_sync.py`.** The master plan lists a *new*
`check_docs_source_sync.py` to be designed later; it **partially overlaps** the
existing `scripts/docs/check_doc_sources.py` (which already validates the
front-matter `sources:`). Do not duplicate — extend the existing script.
(Designing it is out of scope for this policy doc.)

---

## 10. Compatibility Adapter Policy

This section defines the mechanism every ADAPT-classified change must use. The
governing rule: **an internal implementation may move freely; an external
contract may only change through an adapter that keeps the old shape working
until a limited-deprecation cycle (§11) completes.**

**A. The canonical adapter pattern already exists — reuse it, don't invent.**
`ari.public.*` is precisely this pattern: a thin re-export module
(`from ari.<private> import <symbol>`) with an explicit `__all__`. When a private
module moves, update the *import inside* `ari/public/<x>.py`; the external symbol
path is unchanged. This is the mandated adapter for every §2/§8 change.

**B. Adapter requirements (all mandatory):**

1. **Same name, same signature, same return shape.** The adapter re-exports or
   wraps; it does not change argument names, defaults, or the result envelope
   (e.g. the MCP `{"result"|"error"}` envelope, the dashboard `{ok}`/`{error}`
   conventions, the `mcp__<skill>__<tool>` naming).
2. **Additive-only for schemas.** Response/config schemas may gain optional keys
   (the `test_api_schema_contract.py` subset rule permits this) but may not
   rename or remove existing keys without §11.
3. **Alias, don't relocate, for renames.** A CLI command rename, MCP tool
   rename, or route rename ships the new name **plus** the old name as an alias
   (e.g. the existing `new → wizard` route alias in `App.tsx`, and the CLI
   `_reorder_commands_for_compat` ordering shim). The old name emits a
   deprecation notice (§11) and keeps working for the cycle.
4. **One-way dependency.** Adapters live on the *provider* side (core exposes
   `ari.public.*`; the dashboard exposes stable endpoints). Consumers
   (`ari-skill-*`, the React FE) never gain an adapter to reach private internals
   — the 4 boundary violations in §8 are fixed by *adding a public re-export*,
   not by blessing the private import.
5. **Guarded.** Every adapter is covered by the existing contract tests
   (`test_public_api_boundary.py`, `test_api_schema_contract.py`,
   `test_workflow_contract.py`) or a new equivalent, so a later phase cannot
   remove the adapter without a red test.

**C. On-disk / path adapters.** Storage consolidation (§6) is done behind
`PathManager` (`ari/paths.py`): new layouts are added as new resolver methods
while `from_checkpoint_dir` / `ARI_CHECKPOINT_DIR` continue to resolve legacy
flat checkpoints. The root `checkpoints/` path is a MOVE_TO_LEGACY read path, not
removed.

**D. What is NOT an adapter case.** Pure internal refactors with no external
surface — splitting `routes.py` (1197 L), `agent/loop.py` (1630 L),
`ari-skill-paper/src/server.py` (2956 L), or `resultSections.tsx` (1590 L) into
smaller modules — need **no** adapter, only preservation of the §3/§4 wire
contracts and the §2/§8 import paths they participate in.

---

## 11. Limited Deprecation Policy

**"Deprecated" is reserved for external contracts only.** Internal-only retirement
uses MOVE_TO_LEGACY / DELETE_CANDIDATE and never the word "deprecated".

**A. What may be deprecated (the external contract set):**

1. `ari` CLI command/flag names and their env-var side effects (§1).
2. `ari.public.*` exported symbols (§2).
3. MCP tool names, `inputSchema`, the `{"result"|"error"}` envelope, and
   `mcp__<skill>__<tool>` naming (§3).
4. Dashboard REST endpoints (method+path), the guarded response schemas, and the
   WS `update` message shape (§4/§5).
5. Documented on-disk file formats and the `ARI_CHECKPOINT_DIR` contract (§6).
6. Documented config key paths / search precedence and the `config/` vs
   `configs/` import paths (§7).
7. The `ari-skill-* ↔ ari-core` interface: `ari.public.*` touchpoints and the
   `ari_skill_memory.backends.get_backend` edge (§8).
8. Documented usage in README/`docs/reference/` (§9).

**B. Deprecation cycle (mandatory ordering):**

1. **Introduce** the replacement behind an adapter (§10); the old surface keeps
   working.
2. **Announce** in `CHANGELOG.md` (129 KB, the canonical change log) and in the
   relevant `docs/reference/` page front-matter (`last_verified` bump). For code
   surfaces, emit a runtime notice through the existing helper
   `ari-core/ari/_deprecation.py` (the sanctioned mechanism) rather than an
   ad-hoc `warnings.warn`.
3. **Overlap** for at least one minor release, during which the contract test
   asserts **both** old and new surfaces resolve.
4. **Remove** the old surface only in a release that documents the removal, and
   only after a dependency sweep (grep across `ari-skill-*`, `services/api.ts`,
   `docs/`, and `.github/workflows/`) confirms zero remaining consumers.

**C. Enforcement alignment.** The removal step is bounded by the existing
`refactor-guards.yml` philosophy: that workflow already fails on *new* `~/.ari/`
references outside `migrations/` and asserts no `$HOME/.ari/` writes during
pytest — the same "old surface allowed only through the sanctioned shim" discipline
this policy applies to all external contracts. Migration shims live in
`ari-core/ari/migrations/` (e.g. `v05_to_v07/`), which is the one place legacy
paths (`~/.ari/global_memory.jsonl` via `LEGACY_GLOBAL_PATH` in
`migrations/v05_to_v07/memory.py:26`) may legitimately be referenced.

**D. Explicitly out of scope for deprecation (internal cleanup, no cycle).**
Empty `ari/__init__.py`, docstring-only `ari/public/__init__.py`, unused
`server:main` console scripts (§3), skill version drift and `requires-python`
fragmentation (§8), the divergent MCP server idioms (§3), and the giant-file
splits (§10D). These are MOVE_TO_LEGACY / DELETE_CANDIDATE / MERGE items handled
by ordinary refactoring once §10 adapters (where any external symbol is touched)
are in place.

---

### Appendix — cross-reference: contract surface → guard

| Contract (section) | Human doc | Automated guard |
|---|---|---|
| CLI (§1) | `docs/reference/cli_reference.md`, `README.md:318-328` | `readme-sync.yml` (usage parity); `--help` order via `_reorder_commands_for_compat` |
| Public API (§2) | `docs/reference/public_api.md` | `tests/test_public_api_boundary.py` |
| MCP tools (§3) | `docs/reference/mcp_tools.md`, `skills.md` | (none yet — `check_import_boundaries.py` proposed) |
| Dashboard API (§4) | `docs/reference/rest_api.md` | `tests/test_api_schema_contract.py` |
| FE fields (§5) | `docs/reference/rest_api.md` | `tests/test_api_schema_contract.py`; `check_i18n_js.py` |
| Checkpoint/output (§6) | `docs/reference/file_formats.md`, `glossary.md` | `refactor-guards.yml` (`~/.ari/`) |
| Config (§7) | `docs/reference/configuration.md`, `environment_variables.md` | `tests/test_workflow_contract.py` |
| Skill↔core (§8) | `docs/reference/internal_boundaries.md`, `public_api.md` | `tests/test_public_api_boundary.py` |
| Docs/examples (§9) | `docs/reference/README.md` | `docs-sync.yml`, `docs-change-coupling.yml`, `readme-sync.yml`, `pages.yml` |

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
