# 013 — Reference Graph and Dead Code Detection Plan

> **Status:** PLANNING ONLY. This document proposes a methodology and a set of
> tooling subtasks. It changes **no** runtime code, imports, prompts, configs,
> workflows, frontend, or directory names. The only artifact produced by this
> plan is this Markdown file; implementation lands later under the subtasks
> named in §10.
>
> **Scope anchor:** `ari-core` version `0.9.0`, git branch `main`, planning date
> `2026-07-01`. All file paths are repository-relative to
> `/home/t-kotama/workplace/ARI`.
>
> **Vocabulary.** Directory/module-level decisions use the master classification
> KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED.
> Symbol-level dead-code decisions use the finer set defined in §7:
> SAFE_DELETE_CANDIDATE / QUARANTINE_CANDIDATE / TEST_ONLY / DOCS_ONLY /
> DYNAMIC_REFERENCE_RISK / PUBLIC_CONTRACT / REVIEW_REQUIRED.

## 1. Purpose

ARI has grown to **30,277 LOC in `ari-core/ari`** plus **~25.5k LOC across the
14 `ari-skill-*` packages** and a substantial React/TypeScript dashboard under
`ari-core/ari/viz/frontend/`. As the refactoring program proceeds (directory
policy, prompt externalization, public-API hardening, registry/DI consolidation),
we need an evidence base for a recurring question: **is this symbol/module/file
actually reachable, or is it dead weight we can retire?**

This document defines how ARI will:

1. Enumerate the **root entrypoints** from which all "live" code is reachable
   (§3), so reachability has a well-defined starting set.
2. Build a **reference graph** over Python symbols, TypeScript modules, and the
   cross-language edges that connect the dashboard frontend to the `viz` backend
   (§4, §6).
3. Model the **dynamic reference sources** that static import analysis cannot
   see — registry/factory string keys, config-path and rubric lookups, prompt
   keys, and MCP tool dispatch — and treat the symbols they reach as **live**
   even when no `import` statement mentions them (§5).
4. Classify unreachable-looking symbols into actionable buckets (§7), of which
   **only `SAFE_DELETE_CANDIDATE` is ever deleted, and only in subtask 057** (§9).

The deliverable of the tooling this plan describes is a *reference graph plus a
classified dead-code candidate list*, not a bulk deletion. Deletion is a separate,
gated step.

Note on a recurring confusion carried from earlier audits: there is **no
`sonfigs/` directory** anywhere in the repository. The confusable trio is
`ari-core/ari/config/` (Python *locator* code), `ari-core/ari/configs/`
(packaged default DATA + `_loader.py`), and top-level `ari-core/config/`
(rubric/profile DATA). The reference-graph tooling must key on these exact three
paths and must not fabricate a `sonfigs/` node.

## 2. Why Static Analysis Alone Is Not Enough

A naive "grep for `import X`; if nothing imports it, delete it" pass would be
actively dangerous in this codebase. ARI is import-driven at its extensibility
seams, and several categories of live code are **reachable only through string
keys, filesystem paths, subprocess boundaries, or cross-language calls** that a
Python AST import graph never records. Concrete, verified examples:

- **String-keyed backend dispatch.** `ari/publish/__init__.py:198`
  `_load_backend(name)` is an `if/elif` chain that lazily imports one of
  `ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` **by string
  name**. Those four backend modules have **no static importer** — a pure import
  graph would flag all of them as dead, yet they are the live implementation of
  the `ari publish`/EAR path. The valid names are additionally duplicated as an
  enum in `ari/schemas/publish.schema.json`.

- **Prompt keys as filesystem paths.** Prompts were already externalized to
  `.md` templates loaded via `ari/prompts/_loader.py`
  (`FilesystemPromptLoader.load(key)`). Call sites pass **string keys** that map
  to files, e.g. `ari/evaluator/llm_evaluator.py:255`
  `.load("evaluator/extract_metrics")`, `:413` `.load("evaluator/peer_review")`,
  `ari/orchestrator/bfts.py:744` `.load("orchestrator/bfts_expand")`,
  `ari/orchestrator/root_idea_selector.py:63`
  `.load("orchestrator/root_idea_selector")`,
  `ari/pipeline/context_builder.py:117` `.load("pipeline/keyword_librarian")`,
  `ari/viz/api_tools.py:55` `.load("viz/wizard_chat_goal")`. The `.md` files
  under `ari/prompts/` are referenced by **no import at all**; they are live data
  reached by string.

- **Config/rubric DATA reached by name.** Rubric and profile YAML under
  `ari-core/config/` (`paperbench_rubrics/*.yaml`, and **23** files under
  `reviewer_rubrics/*.yaml`, plus `reviewer_rubrics/fewshot_examples/neurips/*.json`)
  are selected at runtime by identifier (e.g. via the `ari paper --rubric` flag
  and its `ARI_RUBRIC` env side effect). No `import` references these files.

- **MCP tool dispatch across a subprocess boundary.** The 14 `ari-skill-*/src/server.py`
  servers expose tools that `ari-core` invokes through `ari/mcp/client.py`
  (`MCPClient.call_tool(tool_name, args)`, `client.py:227`). Tools are declared
  in two idioms: **59 `@mcp.tool` decorators** across the 10 FastMCP skills, and
  **~27 low-level `Tool(name=...)`** entries across the four
  `mcp.server.Server` skills (coding 5, evaluator 3, hpc 9, orchestrator 11 by
  live count). Every tool handler is reachable only by its **string tool name**
  over stdio; ari-core never imports skill modules for tool dispatch. A
  server-side handler that looks unreferenced within its package is in fact the
  live contract surface.

- **CLI subcommand groups behind import guards.** `ari/cli/__init__.py:82-100`
  registers `memory`, `ear`, and `registry` sub-typers inside broad
  `try/except Exception` guards. The imported modules (`ari/memory_cli.py`,
  `ari/cli_ear.py`, `ari/registry/cli.py`) are live, but a fragile static walker
  that trips on the guard could mis-mark them.

- **Cross-language edges.** The React frontend calls the `viz` backend over HTTP
  and WebSocket. `ari/viz/frontend/src/services/api.ts` (863 LOC) and
  `websocket.py` consumers reach endpoints defined across `ari/viz/routes.py`
  (1197 LOC) and the **14 `ari/viz/api_*.py`** modules. A Python-only import graph
  never sees these edges; a TypeScript-only graph never sees the handlers.

- **Empty package `__init__` masking exports.** `ari/__init__.py` is **empty**
  (no `__version__`, no re-exports) and `ari/public/__init__.py` is
  **docstring-only** (re-exports nothing at top level). Callers must import
  `ari.public.<submodule>` directly. A tool that assumes "public API = names in
  `__init__.__all__`" would conclude the public surface is empty and mark it all
  dead — the opposite of the truth.

The unifying lesson: **absence of a static import edge is necessary but not
sufficient evidence of deadness.** The reference graph must overlay the dynamic
edge sources of §5 before any symbol is called a deletion candidate.

## 3. Root Entrypoints

Reachability is computed from a fixed root set. Anything reachable from a root
(through static edges in §4 or dynamic edges in §5) is **live**. The roots below
are grounded in the current manifest, CLI, MCP, dashboard, and CI wiring.

| # | Root class | Concrete anchor(s) |
|---|------------|--------------------|
| R1 | Console script | `ari-core/pyproject.toml` `[project.scripts]` `ari = "ari.cli:app"` (the **only** console script). |
| R2 | CLI app + command tree | `ari/cli/__init__.py` (`app = typer.Typer(name="ari")`, 175 LOC); top-level commands in `cli/{commands,run,projects}.py`; order pinned by `_reorder_commands_for_compat()` (`cli/__init__.py:148-170`); `cli/__main__.py`. |
| R3 | CLI sub-typers (guarded) | `memory` → `ari/memory_cli.py`; `ear` → `ari/cli_ear.py`; `registry` → `ari/registry/cli.py`; `migrate` → `ari/cli/migrate.py` (registered `cli/__init__.py:82-100`). |
| R4 | MCP skill registration | 14 `ari-skill-*/src/server.py` servers (FastMCP: benchmark, idea, memory, paper, paper-re, plot, replicate, transform, vlm, web; low-level `Server`: coding, evaluator, hpc, orchestrator). Each server's `@mcp.tool`/`Tool(name=...)` handlers are roots. |
| R5 | MCP client bridge | `ari/mcp/client.py` `MCPClient` (public per `ari/mcp/__init__.py`); `to_claude_mcp_config()` emits `mcp__<skill>__<tool>` names for the Claude CLI subprocess — those fully-qualified names are external roots. |
| R6 | Dashboard HTTP/WS routes | `ari/viz/routes.py` (1197) + the 14 `ari/viz/api_*.py` modules (e.g. `api_experiment.py` 929, `api_paperbench.py` 813, `api_settings.py` 553) + `ari/viz/websocket.py`, `server.py`, `state.py`, `state_sync.py`. Each registered route/handler is a root. |
| R7 | Public Python API | `ari.public.*` submodules: `claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`. Every re-exported symbol (§4, PUBLIC_CONTRACT) is a root. |
| R8 | Frontend entrypoint | `ari/viz/frontend/src/App.tsx` and the Vite build; every reachable component/page under `frontend/src/` and every endpoint referenced by `services/api.ts` (863) is a cross-language root into R6. |
| R9 | Test suites | `ari-core/tests/` (heaviest: `test_server.py` 1844, `test_gui_errors.py` 1650, `test_workflow_contract.py` 1606, `test_wizard.py` 1133) plus per-skill and frontend `__tests__/`. Tests are roots for TEST_ONLY classification (§7), **not** for justifying production liveness. |
| R10 | Examples / documented commands | Documented `ari …` invocations in `README*.md` and `docs/`; usage snippets validated by `scripts/docs/check_doc_sources.py`. |
| R11 | Scripts invoked by CI | Scripts actually called by `.github/workflows/*`: `scripts/docs/{sync_report_pdf.sh,assemble_site.sh,check_doc_sources.py,check_i18n_js.py,check_site_i18n.py,check_doc_links.py,check_readme_parity.py,check_translation_freshness.py}`, `scripts/readme_sync.py`, plus `scripts/docs/{check_report_cochange.py,check_ref_coupling.py}` (docs-change-coupling). `scripts/git-hooks/pre-commit` invokes `scripts/readme_sync.py --write`. |
| R12 | Registry / EAR HTTP surface | `ari/registry/app.py` `build_app(data_dir)` FastAPI endpoints (`/artifact`, `/artifact/{id}/promote`, `/healthz`, `/version`) — served via `ari registry serve`; external HTTP roots distinct from the DI-style "registry" name (see §5). |

**Not roots (important negatives):**
- `ari/core.py:83 build_runtime` and `:235 generate_paper_section` are **internal**
  (CLI-only), not part of `ari.public` — they are reachable *from* R2, but must
  not be treated as an independent public root.
- The two skills that declare `[project.scripts]` `server:main`
  (`ari-skill-replicate`, `ari-skill-paper-re`) are **not** used by the loader
  (skills launch by filesystem path `python <skill>/src/server.py`). Those
  console-script declarations are entrypoint *noise*, not live roots — flag as
  REVIEW_REQUIRED, not as R1-class roots.

## 4. Symbol Categories

The reference graph is a directed graph whose nodes are symbols and whose edges
are references. Nodes carry a **category** used later for classification.

**Node kinds:**
- `py.module` — a Python module file (e.g. `ari/publish/backends/zenodo.py`).
- `py.symbol` — a top-level function/class/constant (e.g.
  `ari.evaluator.llm_evaluator.LLMEvaluator`).
- `ts.module` — a TypeScript/TSX module (e.g. `services/api.ts`).
- `ts.symbol` — an exported TS function/component/type.
- `data.file` — a non-code asset referenced by string (prompt `.md`, rubric/config
  YAML, JSON schema).
- `route` — an HTTP/WS endpoint path exposed by a `viz` or `registry` handler.
- `mcp.tool` — a named MCP tool handler.

**Edge kinds:**
- `static.import` — resolved `import`/`from … import` (Python) or `import`
  (TS/Vite).
- `static.call` — intra-module or resolved cross-module call/attribute use.
- `dynamic.string_key` — reference resolved through a string→impl table (§5).
- `dynamic.path` — reference resolved by filesystem path/basename (prompt key,
  rubric name, JSON schema `load(name)`).
- `dynamic.mcp` — `MCPClient.call_tool("<name>")` → server tool handler across
  the stdio boundary.
- `cross_lang.http` — `services/api.ts` fetch/WS → `viz` route handler.

**Category tags on nodes** (drive §7):
- `PUBLIC_CONTRACT` — reachable via R7 (`ari.public.*` symbols), R2 CLI command
  names/flags and their env side-effects, R4/R5 MCP tool names + `inputSchema` +
  `{"result"|"error"}` envelope, R6 dashboard endpoints/schema, checkpoint/config
  file formats. Never a deletion candidate.
- `dynamic_target` — the destination of any `dynamic.*` edge, or a node with a
  known dynamic-reference *risk* even if no edge was resolved (§5). Maps to
  DYNAMIC_REFERENCE_RISK unless also PUBLIC_CONTRACT.
- `test_only` — reachable only from R9.
- `docs_only` — reachable only from R10 documentation references.
- `internal` — reachable from a root through static/dynamic edges but not itself
  a contract surface (bulk of the code).
- `orphan` — no inbound edge from any root under any edge kind.

## 5. Dynamic Reference Sources

This is the load-bearing section. Each source below is a place where liveness is
established **without** a static import edge. The tooling MUST enumerate these and
inject `dynamic.*` edges before classification. Grounded inventory:

### 5.1 String-keyed factories / dispatchers
There is **no central DI registry** in ARI today; extensibility is realized as
three ad-hoc string→impl dispatchers plus one dict-registry:

1. **Publish backends** — `ari/publish/__init__.py:198` `_load_backend(name)`
   `if/elif` over `"ari-registry" | "local-tarball" | "zenodo" | "gh"` →
   lazy-imports `ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`
   (213/48/139/134 LOC). **All four modules are `dynamic.string_key` targets and
   MUST be marked live.** Keys are mirrored in
   `ari/schemas/publish.schema.json` (enum).
2. **Evaluator composites** — `ari/evaluator/llm_evaluator.py:165`
   `_COMPOSITES: dict[str, callable]` over
   `"harmonic_mean" | "arithmetic_mean" | "weighted_min" | "geometric_mean"`.
   Keys must stay in sync with the `EvaluatorConfig.composite` Literal
   (`ari/config/__init__.py:212`). This is the closest existing thing to a real
   registry-dict and the mapped callables are `dynamic.string_key` targets.
3. **LLM backend routing** — `ari/llm/routing.py:37` `resolve_litellm_model`
   `if/elif` over `"anthropic" | "claude" | "ollama" | "cli-shim"` → provider
   prefix.
4. **Memory client selection (partial)** — `ari/core.py:130` **hardcodes**
   `LettaMemoryClient(...)`. `ARI_MEMORY_BACKEND` is *set*
   (`config/__init__.py:316`) but no dispatch consumes it in core (unconfirmed
   whether `ari-skill-memory` reads it). Because the env var exists without a
   consumer, any alternative memory backend class is DYNAMIC_REFERENCE_RISK, not
   an orphan.

### 5.2 Config / rubric / schema path lookups
- **Prompt keys** → `.md` files via `ari/prompts/_loader.py`
  `FilesystemPromptLoader.load(key)` / `load_versioned(key)`. Enumerate every
  string literal passed to `.load(...)` (grounded call sites listed in §2) and add
  a `dynamic.path` edge to `ari/prompts/<key>.md`. Skill-local prompts under
  `ari-skill-paper-re/src/prompts/` and `ari-skill-replicate/src/prompts/` need
  the same treatment within their packages.
- **Config DATA** — `ari/configs/_loader.py` `FilesystemConfigLoader` loads
  packaged defaults (`configs/defaults.yaml`, `configs/model_prices.yaml`) by
  string `key`; `ari/config/finder.py` *locates* config files. Both resolve DATA
  that no import references.
- **Rubric/profile DATA** — selected by identifier (`ari paper --rubric`,
  `ARI_RUBRIC` side effect; `--profile`) → `ari-core/config/paperbench_rubrics/*.yaml`,
  `ari-core/config/reviewer_rubrics/*.yaml` (23 files),
  `ari-core/config/profiles/{cloud,hpc,laptop}.yaml`, and
  `reviewer_rubrics/fewshot_examples/neurips/*.json`. All `dynamic.path` targets.
- **JSON schemas** — `ari/schemas/__init__.py` `load(name)` / `schema_path(name)`
  resolve `node_report.schema.json` / `publish.schema.json` by basename.
  **Finding:** the `ari.schemas.load()` API has **no production importer** — a
  repo-wide search found only `tests/test_node_report.py` reading the file by
  direct filesystem path, bypassing the loader. So the loader API is
  TEST_ONLY-reachable surface (§7), while the `.json` files themselves are live
  data (referenced by tests + mirrored enums). Classify the *loader functions*
  and the *schema files* separately.

### 5.3 MCP tool dispatch
`MCPClient` (`ari/mcp/client.py`, 484 LOC) discovers tools via `list_tools()` →
`[{name, description, inputSchema, skill_name}]` and dispatches via
`call_tool(tool_name, args)` returning the `{"result": …}` / `{"error": …}`
envelope. Tool names are **bare snake_case in one flat namespace**;
`MCPClient._tool_registry` (`client.py:283`, `dict tool_name → skill.name`) maps
them globally, so **cross-skill name collisions silently clobber (last skill
wins)** — a reference-graph hazard, because two distinct handlers can map to one
tool-name node. The tooling must key `mcp.tool` nodes by
`(skill, tool_name)` and additionally emit a **collision report** so the flat
namespace risk is visible rather than hidden by node de-duplication. Every
`@mcp.tool`/`Tool(name=…)` handler gets a `dynamic.mcp` inbound edge from R4/R5
and is PUBLIC_CONTRACT.

### 5.4 Cross-language HTTP/WS edges
`ari/viz/frontend/src/services/api.ts` (863) and WebSocket clients reference
endpoint paths served by `ari/viz/routes.py` + the 14 `api_*.py` modules +
`websocket.py`. The tooling adds `cross_lang.http` edges by matching endpoint
path strings between the TS client and the Python route registrations. Any
`viz` handler reachable this way is PUBLIC_CONTRACT (dashboard API surface) and
must never be a deletion candidate.

### 5.5 CLI env-var side effects
Several CLI commands set `ARI_*` env vars that downstream code reads
(`run` → `ARI_IDEA_VIRSCI_*`; `paper` → `ARI_RUBRIC`/`ARI_FEWSHOT_MODE`/…). A
reader of `ARI_X` is dynamically coupled to the writer command. Enumerate
`os.environ`/`getenv("ARI_*")` reads and pair them with the setting command so
env-mediated liveness is not lost.

### 5.6 Guarded / lazy imports
`try/except Exception` import guards (`cli/__init__.py:82-100`) and lazy in-function
imports (`_load_backend`, prompt-loader helpers like `_PL_be()`/`_PL_pipe()`)
must be walked as real static edges, not skipped because they are not
module-top-level `import`s. `ruff` reports **135 `E402`** (import-not-at-top) and
several `F811` redefinitions — the walker must tolerate these patterns.

## 6. Reference Graph Output Format

The tooling emits a machine-readable graph plus human-readable rollups.

### 6.1 Primary artifact — `reference_graph.json`
A single JSON document (written under `docs/refactoring/reports/` when the
tooling runs; **not** created by this planning doc):

```json
{
  "schema_version": 1,
  "generated_at": "<iso8601>",
  "commit": "<git sha>",
  "roots": [
    {"id": "R1:console_script:ari", "kind": "console_script"},
    {"id": "R4:mcp:paper:generate_paper", "kind": "mcp.tool"}
  ],
  "nodes": [
    {
      "id": "py.symbol:ari.publish.backends.zenodo:publish",
      "kind": "py.symbol",
      "file": "ari-core/ari/publish/backends/zenodo.py",
      "loc": 139,
      "category": ["dynamic_target"],
      "reachable_from": ["R2:cli:publish"],
      "edges_in": ["dynamic.string_key"],
      "classification": "DYNAMIC_REFERENCE_RISK"
    }
  ],
  "edges": [
    {
      "from": "py.symbol:ari.publish._load_backend",
      "to": "py.module:ari.publish.backends.zenodo",
      "kind": "dynamic.string_key",
      "evidence": "ari-core/ari/publish/__init__.py:198 if/elif key='zenodo'"
    }
  ],
  "collisions": [
    {"tool_name": "…", "skills": ["…", "…"], "note": "flat MCP namespace clobber"}
  ]
}
```

Every edge carries an **`evidence`** field (file:line + the matched key/path/route
string) so a reviewer can audit *why* the graph believes an edge exists. Dynamic
edges without evidence are not permitted — this keeps the graph falsifiable.

### 6.2 Secondary artifact — `dead_code_candidates.md`
A ranked table (most-confident deletions first) grouped by the §7 classification,
one row per candidate node: `file`, `symbol`, `loc`, `classification`,
`reachable_from` (empty for orphans), `evidence`, and a one-line rationale. This
is the human review surface for subtasks 055–057.

### 6.3 Rollup — dead-code section of the quality report
`generate_quality_report.py` (subtask 058, see §10) folds counts per
classification and the largest orphan modules into the repo quality report,
alongside the existing size/lint baselines (viz = 8,131 LOC / 27% of core;
`public/` = 148 LOC; ruff = 661 findings / 341 `F401`).

### 6.4 Determinism requirement
Per ARI design principle P2, the graph builder MUST be deterministic: stable node
ordering (sort by `id`), no wall-clock in node bodies (only in the top-level
`generated_at`), and **no LLM calls**. Two runs on the same commit must produce
byte-identical `nodes`/`edges` arrays. This mirrors the "no LLM calls" contract
already declared for deterministic tooling like `ari-skill-memory` and
`scripts/readme_sync.py`.

## 7. Dead Code Candidate Classification

Every node that lacks a resolved inbound edge from a *production* root is triaged
into exactly one of the following. Precedence is top-down: the first matching rule
wins (so PUBLIC_CONTRACT and DYNAMIC_REFERENCE_RISK always outrank
SAFE_DELETE_CANDIDATE).

| Class | Definition | Action in this program |
|-------|-----------|------------------------|
| `PUBLIC_CONTRACT` | Reachable via R7 (`ari.public.*`), R2 CLI names/flags/env side-effects, R4/R5 MCP tool name+schema+envelope, R6 dashboard endpoint/schema, or a checkpoint/config file format. | **KEEP.** Never deleted. Any change needs a compatibility-adapter note in a later phase. |
| `DYNAMIC_REFERENCE_RISK` | Target of a `dynamic.*` edge, or a node in a known dynamic seam (§5) where the resolver could not be statically proven. Includes all four `publish/backends/*`, `_COMPOSITES` callables, prompt/rubric/schema data files, memory-backend classes gated by `ARI_MEMORY_BACKEND`. | **REVIEW_REQUIRED / KEEP.** Treated as live. Never auto-deleted. |
| `PUBLIC_CONTRACT`-adjacent `REVIEW_REQUIRED` | Ambiguous entrypoint noise, e.g. the unused `server:main` console scripts in `ari-skill-replicate`/`ari-skill-paper-re`; CLI groups behind `except Exception`. | **REVIEW_REQUIRED.** Human decides ADAPT vs MOVE_TO_LEGACY. |
| `TEST_ONLY` | Reachable only from R9 tests, never from production roots. Example: `ari.schemas.load()`/`schema_path()` (only `tests/test_node_report.py` reaches the loader; production reads none). | **REVIEW_REQUIRED.** Either promote a real production caller, keep as a test helper, or MOVE_TO_LEGACY — never silently deleted (would break tests). |
| `DOCS_ONLY` | Referenced only by `docs/` or `README*` prose (R10), no code edge. | **REVIEW_REQUIRED.** Coordinate with `scripts/docs/check_doc_sources.py`; deletion must update docs in the same change. |
| `QUARANTINE_CANDIDATE` | No production, test, or docs edge, but too intertwined / too recently added / too risky to delete outright (e.g. large modules, anything touching checkpoint/migration formats, `ari/migrations/`). | **MOVE_TO_LEGACY** (quarantine, §9) — retained but isolated for one release cycle before re-evaluation. |
| `SAFE_DELETE_CANDIDATE` | `orphan` node: no inbound edge under **any** edge kind (static, dynamic, cross-lang, test, docs); not in any §5 dynamic seam; not a contract surface; small blast radius. | **DELETE_CANDIDATE.** The **only** class eligible for deletion, and only in **subtask 057**. |
| `REVIEW_REQUIRED` | Anything the tooling cannot confidently place. Default bucket. | Human triage before any action. |

**Hard rule:** a node is `SAFE_DELETE_CANDIDATE` only if it fails *every*
liveness test in §3–§5. When in doubt the classifier must downgrade to
`REVIEW_REQUIRED` or `QUARANTINE_CANDIDATE`, never up to `SAFE_DELETE_CANDIDATE`.
The word "deprecated" is reserved for external contracts (public API, CLI, MCP,
dashboard API, documented import paths, ari-skill stable interfaces) and is not
used to label internal orphans.

**Expected shape of results (grounded expectations, not commitments):** the
publish backends, prompt `.md` templates, and the 23 reviewer rubrics will land in
`DYNAMIC_REFERENCE_RISK` (kept). The `ari.schemas` loader functions will land in
`TEST_ONLY`. The empty `ari/__init__.py` and docstring-only `ari/public/__init__.py`
are *not* dead — they are structural contract shells (PUBLIC_CONTRACT-adjacent) and
are handled by the public-API subtask, not here. The genuine
`SAFE_DELETE_CANDIDATE` set is expected to be small and dominated by leftover
helpers surfaced by ruff (`F401` unused-import chains, `F841` unused variables) and
by fully-superseded internal utilities.

## 8. Tooling Strategy

Constraints from the measured baseline: **radon is NOT installed**; **ruff 0.15.2
IS available**; `compileall`/pytest available; **node+npm available (no pnpm)**.
The strategy therefore leans on ruff + the Python `ast`/`importlib` stdlib and a
lightweight TS scan, and installs no new heavy dependency by default.

### 8.1 Python reference graph — `analyze_references.py` (subtask 053)
- Walk `ari-core/ari/**/*.py` (and optionally `ari-skill-*/src/**`) with the
  stdlib `ast` module to extract module/symbol nodes and `static.import` /
  `static.call` edges. No third-party graph library required.
- Seed roots from §3 by parsing `ari-core/pyproject.toml`
  (`[project.scripts]`), the Typer tree in `ari/cli/`, the `ari.public.*`
  submodule exports, and the `viz` route registrations.
- **Reuse existing ruff signal, do not re-derive it:** ingest
  `ruff check ari-core --output-format=json` to fold in `F401` (341),
  `F841` (39), `F811` (8) as corroborating "possibly-unused" hints, and
  `E402` (135) as "walk lazy/guarded imports" markers. Ruff is the authority on
  unused *imports/locals*; `analyze_references.py` is the authority on
  *cross-module reachability*.
- Emit `reference_graph.json` (§6.1). Deterministic, no network, no LLM.

### 8.2 Dynamic-edge overlay (subtask 054)
- Enumerate the §5 seams by targeted, evidence-carrying scans:
  string literals passed to `_load_backend`, keys of `_COMPOSITES`, arguments to
  `FilesystemPromptLoader.load(...)` and `schemas.load(...)`, rubric/profile
  filenames selected by CLI/env, MCP `@mcp.tool`/`Tool(name=…)` declarations, and
  `getenv("ARI_*")` reader/writer pairs.
- Match TS→Python endpoint strings for `cross_lang.http` edges (regex over
  `services/api.ts` fetch/WS calls vs. `viz` route path registrations). No TS
  compiler needed; a string/AST-lite scan suffices given npm-only tooling.
- Inject `dynamic.*` and `cross_lang.http` edges into the graph. Emit the MCP
  collision report (§5.3).

### 8.3 Classifier — `check_dead_code.py` (subtask 055)
- Consume `reference_graph.json`, apply §7 precedence rules, emit
  `dead_code_candidates.md` (§6.2). Runs in `--report` mode by default (never
  deletes). A `--check` mode can fail CI if a *new* `SAFE_DELETE_CANDIDATE`
  appears above a configured budget, ratcheting dead code downward over time
  (mirrors the `readme_sync.py --check` / `check_*` gate pattern already used in
  `.github/workflows/docs-sync.yml` and `readme-sync.yml`).

### 8.4 Frontend reachability
- For TS/TSX, a Vite/`import` graph from `App.tsx` plus the endpoint-string match
  in §8.2 is sufficient to flag orphan components. Given the size hotspots
  (`Results/resultSections.tsx` 1590, `Wizard/StepResources.tsx` 1160,
  `Settings/SettingsPage.tsx` 1049), frontend dead-code output feeds the
  component-splitting subtasks rather than deletion.
- **Out of scope for deletion:** the committed `node_modules/` under
  `frontend/` is a hygiene issue tracked elsewhere; the dead-code tooling ignores
  `node_modules/` entirely.

### 8.5 Relationship to existing and missing tooling
- **Existing** `scripts/docs/check_ref_coupling.py` and `check_doc_sources.py`
  already model doc↔code coupling; `analyze_references.py` complements them
  (code↔code reachability) and must not duplicate their doc-link logic. Note the
  earlier-flagged `check_docs_source_sync.py` idea **partially overlaps** the
  existing `check_doc_sources.py`; the reference-graph work should extend the
  existing checker rather than add a near-duplicate.
- **Missing** (to be created as the subtasks in §10, not now):
  `analyze_references.py`, `check_dead_code.py`, `generate_quality_report.py`.
- Complexity metrics remain unmeasured (no radon, ruff `C901` not enabled); this
  plan does **not** depend on them. If desired, enabling ruff `C901` is the
  no-new-dependency option, but it is out of scope for dead-code detection.

## 9. Deletion / Quarantine Workflow

Deletion is gated, reversible, and separated from analysis. Steps:

1. **Analyze (053/054).** Build `reference_graph.json` with dynamic overlay. No
   code touched. Determinism verified by re-running on the same commit.
2. **Classify (055).** Produce `dead_code_candidates.md`. Human review of every
   `SAFE_DELETE_CANDIDATE`, and of the full `REVIEW_REQUIRED` /
   `QUARANTINE_CANDIDATE` / `TEST_ONLY` / `DOCS_ONLY` lists.
3. **Quarantine (056).** For `QUARANTINE_CANDIDATE`, **MOVE_TO_LEGACY**: relocate
   into a clearly isolated legacy zone (a `legacy/`-style holding area to be named
   by the directory-policy subtask — no directory rename is performed by *this*
   plan), keep it importable, and add a note so a full release cycle can confirm
   nothing dynamic still reaches it. Nothing in a §5 dynamic seam or any
   `PUBLIC_CONTRACT` node may be quarantined.
4. **Delete (057) — the only deletion step.** Remove **only**
   `SAFE_DELETE_CANDIDATE` nodes that survived human review. Each deletion PR:
   - runs the full suite via `scripts/run_all_tests.sh` (and the
     `refactor-guards.yml` / `docs-sync.yml` / `readme-sync.yml` gates) green;
   - re-runs `check_dead_code.py` to confirm the deleted node is gone and no new
     orphan was introduced;
   - is branched off `main` (never committed directly), small, and independently
     revertible.
5. **Report (058).** `generate_quality_report.py` records before/after counts per
   classification so the reduction is auditable.

**Contract firewall (must hold at every step):** the console script
`ari = ari.cli:app`; every `ari.public.*` symbol; all CLI command names, flags,
and their `ARI_*` env side effects; every MCP tool name + `inputSchema` +
`{"result"|"error"}` envelope + `mcp__<skill>__<tool>` naming; all `viz` dashboard
endpoints/schema consumed by `services/api.ts`; checkpoint (`ari/checkpoint.py`)
and config YAML formats; the `ari-skill-*` → `ari-core` stable interfaces; and
scripts invoked by `.github/workflows/*`. If a candidate deletion would touch any
of these, it is reclassified out of `SAFE_DELETE_CANDIDATE` and the workflow stops.

## 10. Related Subtasks

This planning document (013) is realized by the following implementation subtasks.
The `docs/refactoring/subtasks/` and `docs/refactoring/reports/` directories are
currently **empty**; these entries are the planned mapping, to be authored later.
**Only subtask 057 performs deletion.**

| Subtask | Deliverable | Depends on | Deletes code? |
|---------|-------------|-----------|---------------|
| **053** | `analyze_references.py` — static Python/TS reference graph + root seeding; emits `reference_graph.json` (§6.1, §8.1). | 013 | No |
| **054** | Dynamic-edge overlay — enumerate §5 seams (publish backends, `_COMPOSITES`, prompt/rubric/schema paths, MCP tools, `ARI_*` env pairs, cross-lang HTTP) + MCP collision report (§8.2). | 053 | No |
| **055** | `check_dead_code.py` — classifier over §7 vocabulary; emits `dead_code_candidates.md`; `--check` CI-ratchet mode (§8.3). | 053, 054 | No |
| **056** | Quarantine mechanism — `MOVE_TO_LEGACY` holding zone + migration note for `QUARANTINE_CANDIDATE` (§9 step 3). | 055 | No (relocates only) |
| **057** | Execute deletions — remove **only** reviewed `SAFE_DELETE_CANDIDATE` nodes; per-PR test + gate + re-scan (§9 step 4). | 055, 056 | **Yes (only here)** |
| **058** | `generate_quality_report.py` — fold dead-code counts/before-after into the repo quality report (§6.3, §9 step 5). | 055, 057 | No |

**Cross-references to sibling refactoring streams (planning docs, not
implemented here):** the public-API hardening stream owns the empty
`ari/__init__.py` and docstring-only `ari/public/__init__.py`; the registry/DI
stream owns consolidating the three §5.1 string dispatchers under `ari/protocols`;
the directory-policy stream owns naming the legacy quarantine zone and the
`config/` vs `configs/` vs top-level `config/` disambiguation. Dead-code detection
consumes their decisions but does not make them.

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
