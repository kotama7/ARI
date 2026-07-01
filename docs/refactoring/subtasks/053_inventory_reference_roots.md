# Subtask 053: Inventory Reference Roots

> Phase 1: Measurement and Inventory · Risk: Low · Runtime code change: **No** · Depends on: — (root inventory) · Enables: 054 (→ 055 → 056 → 057 → 058)
>
> Planning document only. Nothing here modifies runtime code, imports, prompts,
> configs, workflows, frontend, or directory names. It hands a fresh coding session
> an executable plan to produce a **read-only inventory** of the repository's
> *reference roots* — the fixed set of entrypoints plus the dynamic/string-keyed
> reference sources from which all "live" code is reachable. All file paths and line
> counts are repository-real and verified against the tree at planning date
> **2026-07-01** (ari-core `0.9.0`, branch `main`, HEAD `dcfeacd`, path root
> `/home/t-kotama/workplace/ARI`).
>
> **Vocabulary.** Directory/module-level decisions use the master classification
> KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED. The
> word "deprecated" is reserved for **external contracts** (public API, CLI, MCP,
> dashboard API, documented import paths, ari-skill stable interfaces) and is not
> used for internal code here.

## 1. Goal

Produce a **complete, verifiable inventory of ARI's reference roots** so that the
downstream dead-code chain (054 → 055 → 056 → 057) can compute reachability from a
**well-defined, frozen starting set** and never mistake live-by-string code for dead
weight. Concretely, 053 delivers one reference artifact that enumerates:

1. the **static root set** (console script, CLI command tree, MCP servers/tools,
   dashboard HTTP/WS routes, public Python API, frontend entry, tests, docs
   examples, CI-invoked scripts, registry/EAR HTTP surface), each pinned to a real
   `file:line` anchor;
2. the **dynamic reference sources** — string-keyed dispatchers, prompt/config/rubric
   filesystem-path lookups, MCP tool dispatch across the stdio boundary,
   cross-language HTTP/WS edges, `ARI_*` env-var writer/reader pairs, and
   guarded/lazy imports — that a naive AST import graph cannot see (§7);
3. the **live-by-string allow-list**: the concrete files and symbols that have **no
   static importer** yet are the live implementation surface (the four publish
   backends being the canonical hazard), which subtask 057 must treat as a hard
   deletion firewall;
4. the explicit **negatives** — nodes that look like roots but are not (internal
   CLI-only functions, entrypoint noise) — so downstream tooling does not over-seed.

This inventory is the **frozen baseline** that subtask 054 (`analyze_references.py`)
seeds its root set from, 055 (`check_dead_code.py`) classifies against, and 057 uses
as its "never delete" allow-list. 053 writes **no runtime code**; its only output is
a reference document (with an optional machine-readable companion) under
`docs/refactoring/reports/`. Per the master dependency note, 053 is one of the nine
inventory subtasks (`001, 002, 020, 036, 045, 053, 059, 060, 067`) that **must
precede any runtime code change**, and is the **head** of the linear dead-code chain
`053 -> 054 -> 055 -> 056 -> 057 -> 058`.

## 2. Background

The companion planning document
`docs/refactoring/013_reference_graph_and_dead_code_plan.md` already describes the
*methodology* for reference-graph construction and dead-code detection. Subtask 053
is the **executable inventory** that 013 §3 ("Root Entrypoints") and §5 ("Dynamic
Reference Sources") reference: it turns that prose into a single, machine-checkable,
`file:line`-grounded reference so a fresh coding session (and the 054 analyzer it
feeds) need not re-derive the root set from scratch.

**Why a root inventory is a prerequisite, not busywork.** ARI is import-driven at its
extensibility seams. A "grep for `import X`; if nothing imports it, delete it" pass
would be actively dangerous. The canonical proof, re-verified live at planning date:

- `ari-core/ari/publish/__init__.py:198` `def _load_backend(name)` is an `if/elif`
  chain that lazily imports one of
  `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`
  (**213 / 48 / 139 / 134 LOC**) **by string name**. Those four backend modules have
  **no static importer** — a pure import graph flags all four as dead, yet they are
  the live implementation of the `ari publish` / EAR path. The valid names
  (`"ari-registry" | "local-tarball" | "zenodo" | "gh"`) are additionally mirrored as
  an enum in `ari-core/ari/schemas/publish.schema.json`.

The unifying lesson (013 §2): **absence of a static import edge is necessary but not
sufficient evidence of deadness.** The reference graph must overlay the dynamic edge
sources before any symbol is a deletion candidate — and to do that it needs the
inventory this subtask freezes.

**Prior context (grounded).** v0.5.0 made ARI checkpoint-scoped (no more `~/.ari/`);
the `ari-skill-memory` JSONL store lives at
`{ARI_CHECKPOINT_DIR}/memory_store.jsonl`. `ari-core` imports `ari_skill_memory`
directly (the first core→skill dependency, v0.6.0); it is editable-installed by
`setup.sh`, not on PyPI. The `ari/__init__.py` file is **empty** and
`ari/public/__init__.py` is **docstring-only** (re-exports nothing at top level) — a
tool that equates "public API" with `__init__.__all__` would wrongly conclude the
public surface is empty, so the root inventory must list `ari.public.*` **submodules**
explicitly, not rely on package re-exports.

**Numbering note (record, do not resolve here).** `013 §10` lists subtask **053** as
delivering `analyze_references.py`, but `007_subtask_index.md:100-101` assigns
`analyze_references.py` to **054** (`add_reference_graph_analyzer`) and defines **053**
(`inventory_reference_roots`) as a read-only inventory with "Runtime code change: No".
This subtask follows the `007` index and the master dependency note (053 = inventory,
no runtime code; 054 = the analyzer). Flag the 013 §10 wording as a **REVIEW_REQUIRED**
documentation discrepancy in the artifact; do not edit `013` from 053.

## 3. Scope

In scope (read-only inventory only):

- **Static root set (R1–R12), grounded in the current tree** — the anchors below are
  all verified present at planning date:
  - R1 console script `ari = "ari.cli:app"` (`ari-core/pyproject.toml`
    `[project.scripts]`, the only console script).
  - R2 CLI app + top-level command tree (`ari-core/ari/cli/__init__.py`, 174 LOC;
    commands in `cli/{commands,run,projects}.py`; order pinned by
    `_reorder_commands_for_compat()`).
  - R3 guarded CLI sub-typers (`memory`→`ari/memory_cli.py`, `ear`→`ari/cli_ear.py`,
    `registry`→`ari/registry/cli.py`, `migrate`→`ari/cli/migrate.py`; registered under
    `try/except Exception` guards at `cli/__init__.py:82-100`).
  - R4 the 14 `ari-skill-*/src/server.py` MCP servers and every `@mcp.tool` /
    `Tool(name=...)` handler.
  - R5 the MCP client bridge `ari-core/ari/mcp/client.py` (`MCPClient`, 483 LOC) and
    the `mcp__<skill>__<tool>` fully-qualified names emitted by
    `to_claude_mcp_config()`.
  - R6 dashboard HTTP/WS routes: `ari/viz/routes.py` (1197) + the 14 `ari/viz/api_*.py`
    modules + `websocket.py`, `server.py`, `state.py`, `state_sync.py`.
  - R7 public Python API submodules `ari.public.{claim_gate,config_schema,container,
    cost_tracker,llm,paths,run_env,verified_context}`.
  - R8 frontend entrypoint `ari/viz/frontend/src/App.tsx` + Vite build; endpoints
    referenced by `services/api.ts` (863 LOC).
  - R9 test suites under `ari-core/tests/` and per-skill / frontend `__tests__/`
    (roots for TEST_ONLY classification only, **not** for justifying production
    liveness).
  - R10 documented `ari …` invocations in `README*.md` and `docs/` (validated by
    `scripts/docs/check_doc_sources.py`).
  - R11 scripts actually invoked by `.github/workflows/*` (the 12 targets already
    frozen by subtask 045's inventory).
  - R12 registry / EAR HTTP surface (`ari/registry/app.py` `build_app(data_dir)`,
    served via `ari registry serve`).
- **Dynamic reference sources (D1–D6)** with `file:line` evidence for every edge (§7).
- **Live-by-string allow-list**: the publish backends (4), prompt `.md` templates
  (11), reviewer rubrics (23), paperbench rubrics (4), profiles (3), fewshot JSON,
  JSON schemas (2), `workflow.yaml`, and the `_COMPOSITES` callables (4).
- **The "not a root" negatives** (§7.7).

Out of scope (belongs to the downstream chain):

- Writing `analyze_references.py` (the static Python/TS reference graph builder) →
  subtask **054**.
- Writing `check_dead_code.py` (the §7-vocabulary classifier) → subtask **055**.
- Classifying individual unused functions/files → subtask **056**.
- **Any deletion** of code → subtask **057** (the only deletion step).
- Folding dead-code counts into the quality report → subtask **058**
  (`generate_quality_report.py`).
- The `config/` vs `configs/` vs top-level `config/` disambiguation (directory-policy
  stream, subtasks 003/005) and consolidating the string dispatchers under a DI
  registry (subtasks 007/014). 053 records these seams; it does not restructure them.

## 4. Non-Goals

- **Do not** create, edit, delete, or rename any runtime file (`ari-core/**`,
  `ari-skill-*/**`), any prompt `.md`, any config/rubric YAML/JSON, any workflow, any
  frontend file, or any directory.
- **Do not** write `analyze_references.py`, `check_dead_code.py`,
  `generate_quality_report.py`, or any other checker — those are 054/055/058.
- **Do not** delete, quarantine, or MOVE_TO_LEGACY anything. 053 produces an
  inventory; even reclassification of a symbol is out of scope (that is 056).
- **Do not** consolidate or rename the publish backends, the `_COMPOSITES` dict, the
  LLM routing `if/elif`, or the three §7.1 string dispatchers. Record them as
  DYNAMIC_REFERENCE_RISK seams; the registry/DI stream owns any consolidation.
- **Do not** touch the empty `ari/__init__.py` or docstring-only
  `ari/public/__init__.py`; the public-API hardening stream owns those shells.
- **Do not** invent a `sonfigs/` directory: it **does not exist** anywhere in the
  repo (verified). The confusable trio is `ari-core/ari/config/` (Python *locator*
  code), `ari-core/ari/configs/` (packaged default DATA + `_loader.py`), and top-level
  `ari-core/config/` (rubric/profile DATA + `workflow.yaml`). Record all three exact
  paths; fabricate no fourth.
- **Do not** run any LLM as part of building the inventory (determinism, design
  principle P2).

## 5. Current Files / Directories to Inspect

All paths repository-real, verified 2026-07-01 (HEAD `dcfeacd`).

**Static root anchors:**

- `/home/t-kotama/workplace/ARI/ari-core/pyproject.toml` — `[project.scripts]`
  `ari = "ari.cli:app"` (44 LOC; the only console script). Note the two skills that
  declare an *unused* `server:main` console script:
  `/home/t-kotama/workplace/ARI/ari-skill-replicate/pyproject.toml` and
  `/home/t-kotama/workplace/ARI/ari-skill-paper-re/pyproject.toml` (§7.7 negatives).
- `/home/t-kotama/workplace/ARI/ari-core/ari/cli/__init__.py` (174 LOC) — Typer root,
  `_reorder_commands_for_compat()`, the `try/except Exception` sub-typer guards at
  `:82-100`.
- `/home/t-kotama/workplace/ARI/ari-core/ari/cli/{commands,run,projects,bfts_loop,lineage,migrate}.py`,
  `cli/__main__.py`.
- CLI sub-typer modules:
  `/home/t-kotama/workplace/ARI/ari-core/ari/memory_cli.py`,
  `.../ari/cli_ear.py`, `.../ari/registry/cli.py`, `.../ari/cli/migrate.py`.
- MCP servers: `/home/t-kotama/workplace/ARI/ari-skill-*/src/server.py` (14 files;
  FastMCP: benchmark, idea, memory, paper, paper-re, plot, replicate, transform, vlm,
  web; low-level `mcp.server.Server`: coding, evaluator, hpc, orchestrator).
- MCP client: `/home/t-kotama/workplace/ARI/ari-core/ari/mcp/client.py` (483 LOC),
  `.../ari/mcp/__init__.py`.
- Dashboard backend: `/home/t-kotama/workplace/ARI/ari-core/ari/viz/routes.py` (1197),
  the 14 `ari/viz/api_*.py` modules, `ari/viz/websocket.py`, `server.py`, `state.py`,
  `state_sync.py`.
- Public API: `/home/t-kotama/workplace/ARI/ari-core/ari/public/` (9 files; 148 LOC
  total) — `claim_gate.py, config_schema.py, container.py, cost_tracker.py, llm.py,
  paths.py, run_env.py, verified_context.py`, `__init__.py` (docstring-only).
- Frontend entry: `/home/t-kotama/workplace/ARI/ari-core/ari/viz/frontend/src/App.tsx`;
  API client `.../frontend/src/services/api.ts` (863 LOC).
- Tests: `/home/t-kotama/workplace/ARI/ari-core/tests/` (heaviest: `test_server.py`
  1844, `test_gui_errors.py` 1650, `test_workflow_contract.py` 1606).
- Registry HTTP: `/home/t-kotama/workplace/ARI/ari-core/ari/registry/app.py`.

**Dynamic reference seams (the load-bearing inputs):**

- `/home/t-kotama/workplace/ARI/ari-core/ari/publish/__init__.py:198` `_load_backend`
  and `/home/t-kotama/workplace/ARI/ari-core/ari/publish/backends/`
  (`ari_registry.py` 213, `local_tarball.py` 48, `zenodo.py` 139, `gh.py` 134).
- `/home/t-kotama/workplace/ARI/ari-core/ari/evaluator/llm_evaluator.py:165-169`
  `_COMPOSITES` dict (`harmonic_mean, arithmetic_mean, weighted_min, geometric_mean`)
  → `weighted_harmonic_mean` (`:75`), `weighted_arithmetic_mean` (`:102`),
  `weighted_min` (`:122`), `weighted_geometric_mean` (`:141`). Keys mirror
  `EvaluatorConfig.composite` Literal in `ari/config/__init__.py`.
- `/home/t-kotama/workplace/ARI/ari-core/ari/llm/routing.py:37` `resolve_litellm_model`
  (`anthropic|claude|ollama|cli-shim` prefix routing).
- Prompt loader `/home/t-kotama/workplace/ARI/ari-core/ari/prompts/_loader.py` (49 LOC)
  and the **11** `.md` templates under `ari-core/ari/prompts/` (agent/system.md;
  evaluator/{extract_metrics,peer_review}.md;
  orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md;
  pipeline/keyword_librarian.md; viz/{wizard_chat_goal,wizard_generate_config}.md).
  Skill-local prompts:
  `/home/t-kotama/workplace/ARI/ari-skill-paper-re/src/prompts/`,
  `/home/t-kotama/workplace/ARI/ari-skill-replicate/src/prompts/`.
- Config/rubric DATA:
  `/home/t-kotama/workplace/ARI/ari-core/ari/configs/` (`defaults.yaml`,
  `model_prices.yaml`, `_loader.py`), `ari-core/ari/config/finder.py`, and top-level
  `/home/t-kotama/workplace/ARI/ari-core/config/` (`default.yaml`, `workflow.yaml`
  [23,661 bytes], `profiles/{cloud,hpc,laptop}.yaml`, `paperbench_rubrics/*.yaml` [4],
  `reviewer_rubrics/*.yaml` [**23**], `reviewer_rubrics/fewshot_examples/neurips/*.json`).
- JSON schemas `/home/t-kotama/workplace/ARI/ari-core/ari/schemas/__init__.py` (20 LOC;
  `schema_path(name)`, `load(name)`) + `node_report.schema.json`, `publish.schema.json`.
- Pipeline workflow graph: `/home/t-kotama/workplace/ARI/ari-core/config/workflow.yaml`
  loaded by `ari/cli/run.py` (`:91`, `:245`, `:400`, `:429`; copied into each
  checkpoint for reproducibility).

**Companion / index references (read for alignment, do not modify):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/013_reference_graph_and_dead_code_plan.md`
  — the governing methodology (§2 dynamic-reference examples, §3 root table R1–R12,
  §5 dynamic sources, §7 classification, §10 subtask mapping).
- `/home/t-kotama/workplace/ARI/docs/refactoring/007_subtask_index.md:100-105`,
  `:164-166`, `:602`, `:633` — the 053→058 chain, the "live-by-string roots
  (publish backends)" allow-list requirement, and the dead-code group membership.
- `/home/t-kotama/workplace/ARI/docs/refactoring/subtasks/045_inventory_github_workflows.md`
  — the sibling inventory template whose report structure and CI-safety recipe this
  subtask mirrors.

**Output artifact (the only file this subtask creates):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/reports/053_reference_roots_inventory.md`
  — the inventory itself (a `.json` companion, e.g. `053_reference_roots.json`, is
  encouraged so 054 can ingest the root set programmatically; the
  `docs/refactoring/reports/` directory currently exists but is **empty**).

## 6. Current Problems

These are **observations to record in the inventory**, not defects for 053 to fix
(fixes belong to later subtasks). Each is grounded in a specific `file:line`.

1. **Live code with zero static importers.** The four `publish/backends/*.py`
   (213/48/139/134 LOC) are reached only through `_load_backend`'s string `if/elif`
   (`publish/__init__.py:198`). A naive import graph marks all four dead. → the
   single most important entry in the live-by-string allow-list; **DYNAMIC_REFERENCE_RISK**.
2. **Reference-only data with no import edge.** The 11 prompt `.md` templates, the 23
   reviewer rubrics, 4 paperbench rubrics, 3 profiles, fewshot JSON, and 2 JSON schema
   files are all reached by string key / filesystem path, never by `import`. → record
   every `.load(...)` / `--rubric` / `--profile` selector as a `dynamic.path` seam.
3. **A loader API with no production caller.** `ari/schemas/__init__.py` `load()` /
   `schema_path()` (20 LOC) has **no non-test importer** (verified: repo-wide search
   found only the definition + test-side direct filesystem reads). → the loader
   functions are **TEST_ONLY** surface, while the `.json` files themselves are live
   (referenced by tests + mirrored as enums). Record loader-vs-data separately.
4. **Flat MCP tool namespace with silent collisions.** `MCPClient._tool_registry`
   maps `tool_name → skill.name` **globally**, so two skills exposing the same bare
   snake_case tool name silently clobber (last skill wins). Tool handlers are reachable
   only by string name over stdio. → key MCP tool roots by `(skill, tool_name)` and
   record a **collision report**; do not de-duplicate collisions away.
5. **Two divergent MCP server idioms.** 10 FastMCP skills use `@mcp.tool` (~59
   decorators); 4 low-level `Server` skills use `Tool(name=...)` (~27 entries). A
   root-enumerator must walk **both** idioms or it under-counts tool roots.
6. **CLI groups behind broad import guards.** `cli/__init__.py:82-100` registers
   `memory`/`ear`/`registry`/`migrate` sub-typers under `try/except Exception`; a
   fragile walker that trips on the guard would mis-mark `memory_cli.py`, `cli_ear.py`,
   `registry/cli.py`, `cli/migrate.py` as unreachable. → record them as guarded-but-live
   roots.
7. **Empty package shells mask the public surface.** `ari/__init__.py` is empty (no
   `__version__`); `ari/public/__init__.py` re-exports nothing at top level. → the root
   inventory must enumerate `ari.public.*` **submodules** explicitly (they are the R7
   contract), not derive them from `__init__.__all__`.
8. **Env-mediated coupling invisible to imports.** CLI commands set `ARI_*` env vars
   that downstream code reads (`run` → `ARI_IDEA_VIRSCI_*`; `paper` →
   `ARI_RUBRIC`/`ARI_FEWSHOT_MODE`/…). A reader of `ARI_X` is dynamically coupled to
   the writer command. → enumerate `getenv("ARI_*")` reader/writer pairs.
9. **Two coexisting checkpoint dirs (adjacent, not a reference-root concern).**
   root-level `checkpoints/` (appears legacy) vs `workspace/checkpoints/`. Note only;
   storage-path policy is the 004/005 stream.

## 7. Proposed Design / Policy

053 produces **one inventory artifact** organized as the reference-root register the
054 analyzer will seed from. No runtime changes. Structure:

### 7.1 Static root set (R1–R12)

Reproduce the 013 §3 table with a live `file:line` anchor for each root and a
**verified-present** check, classifying each as **KEEP** (all twelve are live
contract-bearing roots). Where the master facts and 013 diverge in a count, re-count
live and record the observed number with its command.

### 7.2 Dynamic reference sources (D1–D6)

A table, one row per seam, each carrying `file:line` **evidence** so a reviewer can
audit *why* the graph will believe an edge exists (013 §6.1 falsifiability rule):

| ID | Seam | Anchor (file:line) | Live targets |
| --- | --- | --- | --- |
| D1 | String-keyed publish backends | `ari/publish/__init__.py:198` `_load_backend` | `backends/{ari_registry,local_tarball,zenodo,gh}.py` |
| D2 | Evaluator composites dict | `ari/evaluator/llm_evaluator.py:165` `_COMPOSITES` | 4 `weighted_*` callables (`:75,:102,:122,:141`) |
| D3 | LLM backend routing | `ari/llm/routing.py:37` `resolve_litellm_model` | provider-prefix branches |
| D4 | Prompt / config / rubric / schema path lookups | `ari/prompts/_loader.py`, `ari/configs/_loader.py`, `ari/config/finder.py`, `ari/schemas/__init__.py`, CLI `--rubric`/`--profile` | 11 prompt `.md`, `configs/*.yaml`, 23 reviewer + 4 paperbench rubrics, 3 profiles, fewshot JSON, 2 schema JSON, `config/workflow.yaml` |
| D5 | MCP tool dispatch (stdio) | `ari/mcp/client.py` `call_tool`; 14 `ari-skill-*/src/server.py` | every `@mcp.tool` / `Tool(name=...)` handler (+ collision report) |
| D6 | Cross-language HTTP/WS + `ARI_*` env pairs | `viz/frontend/src/services/api.ts` ↔ `viz/routes.py`+`api_*.py`; `getenv("ARI_*")` readers vs CLI writers | matched route handlers; env-coupled readers |

Each D-row is tagged **DYNAMIC_REFERENCE_RISK** (never a deletion candidate).

### 7.3 Live-by-string allow-list (the 057 deletion firewall)

An explicit, `file:line`-cited list of the files/symbols that have **no static
importer** yet must be treated as live: the 4 publish backends, the 4 `_COMPOSITES`
callables, the 11 prompt `.md`, the 23 reviewer rubrics, the 4 paperbench rubrics, the
3 profiles, fewshot JSON, the 2 JSON schema files, and `config/workflow.yaml`. This
allow-list is the contract 057 must honor: "if a candidate deletion appears here, it is
reclassified out of SAFE_DELETE_CANDIDATE and the workflow stops" (013 §9 firewall).

### 7.4 Data reference roots

Record the three-way config split with exact paths and roles — `ari/config/` (locator
*code*), `ari/configs/` (packaged default *data* + `_loader.py`), top-level `config/`
(rubric/profile data + `workflow.yaml`) — and state **`sonfigs/` does not exist**.

### 7.5 TEST_ONLY / DOCS_ONLY carve-outs

Record roots that justify only test/docs liveness, not production liveness: R9 tests
(and the `ari.schemas.load()` loader, which is TEST_ONLY per §6.3) and R10 documented
commands (validated by `scripts/docs/check_doc_sources.py`).

### 7.6 MCP collision report

Enumerate bare tool names across all 14 servers keyed by `(skill, tool_name)`; list any
name that appears in more than one skill as a **collision** (the flat-namespace clobber
hazard). Record even if the set is empty at planning date.

### 7.7 Negatives ("not roots")

Record, so 054 does not over-seed:
- `ari/core.py` `build_runtime` and `generate_paper_section` are **internal** (CLI-only),
  reachable *from* R2 but not independent public roots.
- The `server:main` `[project.scripts]` in `ari-skill-replicate` /
  `ari-skill-paper-re` are **entrypoint noise** (skills launch by filesystem path
  `python <skill>/src/server.py`); mark **REVIEW_REQUIRED**, not R1-class roots.

The artifact should be **regenerable/verifiable** via a documented `find`/`grep`/`wc`
recipe (or a read-only helper under `scripts/`, **not** wired into any workflow — wiring
is a later phase) so future audits can confirm the inventory has not drifted.

## 8. Concrete Work Items

1. **Enumerate the static root set (R1–R12).** For each, record the live `file:line`
   anchor and confirm the target exists (`test -e` / `grep`). Parse
   `ari-core/pyproject.toml [project.scripts]` for R1; walk the Typer tree in
   `ari/cli/` for R2/R3; list `ari.public.*` submodules for R7; enumerate the 14
   `ari-skill-*/src/server.py` for R4 and the 14 `ari/viz/api_*.py` + `routes.py` for R6.
2. **Enumerate the dynamic seams (D1–D6)** with evidence. Transcribe the `_load_backend`
   `if/elif` keys (`publish/__init__.py:199-213`), the `_COMPOSITES` keys→callables
   (`llm_evaluator.py:165-169`), the `resolve_litellm_model` branches (`routing.py:37`),
   every string literal passed to `FilesystemPromptLoader.load(...)` and
   `schemas.load(...)`, the `--rubric`/`--profile` selectors, and every `@mcp.tool` /
   `Tool(name=...)` declaration across the 14 servers.
3. **Build the live-by-string allow-list** (§7.3): 4 backends + 4 composites + 11
   prompts + 23 reviewer rubrics + 4 paperbench rubrics + 3 profiles + fewshot JSON + 2
   schema JSON + `workflow.yaml`, each with `file:line` / path and a one-line rationale.
4. **Enumerate `ARI_*` env writer/reader pairs**: grep CLI command bodies for
   `os.environ[...] = ` / `setenv` of `ARI_*`, and grep the codebase for
   `getenv("ARI_*")` / `environ.get("ARI_*")` readers; pair writer↔reader.
5. **Match cross-language HTTP/WS edges**: extract endpoint path strings from
   `services/api.ts` (fetch/WS) and the route registrations in `viz/routes.py` +
   `api_*.py`; record the matched pairs as `cross_lang.http` seeds for 054 (do not
   resolve exhaustively here — record the method and a representative sample).
6. **Produce the MCP collision report** keyed by `(skill, tool_name)` (§7.6).
7. **Record the negatives** (§7.7): `core.py` internals; the two `server:main`
   entrypoint-noise declarations.
8. **Record the config triple** (§7.4) with exact paths and roles; assert
   `sonfigs/` "does not exist" (`ls` → No such file or directory).
9. **Record the numbering discrepancy** between `013 §10` (053=analyzer) and
   `007_subtask_index.md:100-101` (053=inventory, 054=analyzer) as REVIEW_REQUIRED.
10. **Write the artifact** to
    `docs/refactoring/reports/053_reference_roots_inventory.md` (+ optional
    `053_reference_roots.json` for 054 ingestion).
11. **CI self-check**: confirm whether `docs/refactoring/` or
    `docs/refactoring/reports/` has a directory README managed by
    `scripts/readme_sync.py` (at planning date **neither README exists**, so no index
    edit is expected). Run `python scripts/readme_sync.py --check` to confirm the new
    report does not redden `readme-sync.yml`; only if it does, regenerate the relevant
    `## Contents` with `--write`.
12. **Cross-check** the finished artifact against `013` §3/§5 and
    `007_subtask_index.md`; record any discrepancy in the artifact rather than editing
    those planning docs.

## 9. Files Expected to Change

**Created (single new inventory artifact, optional companion):**

- `/home/t-kotama/workplace/ARI/docs/refactoring/reports/053_reference_roots_inventory.md`
  — the reference-roots inventory.
- (Optional) `/home/t-kotama/workplace/ARI/docs/refactoring/reports/053_reference_roots.json`
  — machine-readable root set + allow-list, for direct ingestion by subtask 054.

**Possibly touched (index bookkeeping only, if — and only if — such an index exists):**

- A `## Contents` index under `docs/refactoring/` **only** if
  `scripts/readme_sync.py` manages one there, and only via `readme_sync.py --write`.
  At planning date neither `docs/refactoring/README.md` nor
  `docs/refactoring/reports/README.md` exists and `scripts/readme_sync.py` does not
  reference `refactoring`/`reports`, so **no index edit is expected**; verify with
  `--check` before assuming.

**Explicitly NOT changed:** any file under `ari-core/**` or `ari-skill-*/**`; any
prompt `.md`; any config/rubric YAML/JSON; any `.github/workflows/**`; any
`scripts/**` checker; any frontend file; any README variant content; any directory
name. 053 adds documentation only.

## 10. Files / APIs That Must Not Be Broken

This subtask is read-only inventory; it must not perturb any contract. The following
are recorded as protected surfaces that the *downstream* dead-code chain (especially
057) must preserve, and which 053 itself must not alter:

- **CLI `ari`** (`ari = ari.cli:app`) — the single console script and all command
  names/flags and their `ARI_*` env side effects.
- **`ari.public.*`** — every submodule symbol
  (`claim_gate, config_schema, container, cost_tracker, llm, paths, run_env,
  verified_context`).
- **MCP tool contracts** — the 14 `ari-skill-*/src/server.py` servers; every tool
  name + `inputSchema` + the `{"result"|"error"}` return envelope + the
  `mcp__<skill>__<tool>` fully-qualified naming.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` endpoints + `websocket.py`
  consumed by `services/api.ts`.
- **Checkpoint / output / config file formats** — `ari/checkpoint.py`; the config/
  rubric YAML under `ari-core/config/` + packaged `ari-core/ari/configs/`; the JSON
  schemas under `ari/schemas/`.
- **`ari-skill-* → ari-core` stable interfaces** — including the direct
  `ari_skill_memory` import from core.
- **Scripts invoked by `.github/workflows/*`** and **README/docs usage**.
- **The live-by-string allow-list (§7.3) is itself a contract firewall**: the four
  publish backends, prompt `.md`, rubrics, profiles, fewshot JSON, JSON schemas, and
  `workflow.yaml` must never be deleted by 057; 053 records them precisely so that
  firewall is auditable.

No compatibility adapter is required because 053 changes no runtime behavior.

## 11. Compatibility Constraints

- **No runtime behavior changes**, so all public contracts (CLI, `ari.public.*`, MCP,
  dashboard API, file formats, skill→core interfaces) are trivially preserved.
- The inventory artifact **must not** cause any existing workflow to fail. Adding a
  file under `docs/refactoring/reports/` could in principle trip `readme-sync.yml` if a
  directory README there is managed by `readme_sync.py --check`; verify with
  `--check` and regenerate with `--write` only if needed (at planning date no such
  README exists).
- The artifact must remain **consistent with** `013` §3/§5 and
  `007_subtask_index.md:100-105`. If a discrepancy is found (e.g. the 013 §10 vs 007
  numbering of `analyze_references.py`), record it in the artifact; do not silently
  diverge and do not edit those planning docs from 053.
- **Downstream reuse contract:** subtask 054 seeds its analyzer from this root set and
  057 uses the §7.3 allow-list as its deletion firewall. Prefer citing `file:line` for
  every root/seam so drift between 053 and 054 is detectable. If any anchored file
  changes before 054 runs (e.g. `_load_backend` gains a fifth backend), the citation
  makes the drift obvious.
- **Determinism (design principle P2):** the inventory and any helper that builds it
  must be deterministic and make **no LLM calls** — two runs on the same commit must
  produce the same root set. This mirrors the "no LLM calls" contract already declared
  for `ari-skill-memory` and `scripts/readme_sync.py`.

## 12. Tests to Run

This subtask produces documentation, so the runtime gates are for hygiene /
no-regression only (they should be unaffected since no code changes):

- `python -m compileall .` — must pass (no `.py` added or changed by 053; expect no
  new failures).
- `pytest -q` — from repo root; must pass unchanged. (CI's `refactor-guards.yml` runs
  `pytest ari-core/tests/ -q` under a redirected `HOME`, ignoring
  `test_letta_restart_live`, `test_letta_start_scripts`, `test_ollama_gpu`,
  `test_dashboard_html`; mirror those ignores if reproducing that job locally.)
- `ruff check .` — must pass unchanged (**ruff 0.15.2 IS available**; **radon is NOT
  installed**, so do not rely on it). Note the frozen baseline for context: ruff
  reports 661 findings on `ari-core` (341 `F401`, 135 `E402`, …) — 053 must not change
  that count.
- **Docs/CI gate self-check** (because the artifact lands under `docs/refactoring/`):
  `python scripts/readme_sync.py --check` — must be green after the artifact is added.
- **Frontend `npm test` / `npm run build` are NOT applicable** — 053 adds no frontend
  code (the frontend lives at `ari-core/ari/viz/frontend/` with `vitest` / `vite build`,
  but this subtask does not touch it; **node+npm available, no pnpm**).
- Optional sanity for the inventory itself: re-run the `find`/`grep`/`wc` recipe used to
  build it and confirm the numbers match what the artifact records (e.g. 4 publish
  backends, 11 prompt `.md`, 23 reviewer rubrics, 14 MCP servers, 8 `ari.public.*`
  submodules).

## 13. Acceptance Criteria

- [ ] A single inventory artifact exists at
  `docs/refactoring/reports/053_reference_roots_inventory.md` (optionally with a
  `.json` companion for 054 ingestion).
- [ ] It enumerates all twelve static roots (R1–R12) with a live `file:line` anchor
  each and a verified-present check.
- [ ] It enumerates the dynamic seams (D1–D6) with `file:line` evidence for each,
  including `_load_backend` (`publish/__init__.py:198`), `_COMPOSITES`
  (`llm_evaluator.py:165`), `resolve_litellm_model` (`routing.py:37`), the prompt /
  config / rubric / schema path lookups, MCP tool dispatch, and `ARI_*` env pairs.
- [ ] It contains the live-by-string allow-list (§7.3): 4 publish backends + 4
  `_COMPOSITES` callables + 11 prompt `.md` + 23 reviewer rubrics + 4 paperbench
  rubrics + 3 profiles + fewshot JSON + 2 JSON schemas + `workflow.yaml`, each cited.
- [ ] It records the MCP tool set keyed by `(skill, tool_name)` and a collision report
  (empty or not).
- [ ] It records the config triple (`ari/config/` code, `ari/configs/` data,
  top-level `config/` rubric data) with exact paths and asserts `sonfigs/` "does not
  exist".
- [ ] It records the negatives (§7.7): `core.py` `build_runtime` /
  `generate_paper_section` internals; the two `server:main` entrypoint-noise
  declarations.
- [ ] It records the 013 §10 vs 007 §100-101 numbering discrepancy as REVIEW_REQUIRED.
- [ ] The artifact is regenerable via a documented `find`/`grep`/`wc` recipe (or a
  read-only helper under `scripts/` not wired into any workflow).
- [ ] No file under `ari-core/`, `ari-skill-*/`, `.github/`, `scripts/` (checkers),
  `config/`, or the frontend was modified.
- [ ] `python -m compileall .`, `pytest -q`, `ruff check .`, and
  `python scripts/readme_sync.py --check` all pass unchanged.

## 14. Rollback Plan

Trivial and low-risk, since the subtask is additive documentation only:

1. `git rm docs/refactoring/reports/053_reference_roots_inventory.md` (and the optional
   `053_reference_roots.json`).
2. Revert the single `## Contents` index line if `readme_sync.py --write` added one
   (it is not expected to), or re-run `python scripts/readme_sync.py --write` after
   removal.
3. No workflow, script, or runtime file was changed, so there is nothing else to undo
   and no CI behavior to restore. A single `git revert <commit>` fully reverses the
   subtask.

## 15. Dependencies

Per the DEPENDENCY GRAPH and `007_subtask_index.md:100-105, :164-166`:

- **Upstream (must precede 053):** none. 053 is a **root inventory** subtask (index
  `:100` lists Depends = "—") and one of the nine inventories that gate all runtime
  code change (`001, 002, 020, 036, 045, 053, 059, 060, 067`).
- **Downstream (053 must precede them) — a strict linear chain:**
  `053 -> 054 -> 055 -> 056 -> 057 -> 058`.
  - **054** `add_reference_graph_analyzer` — writes `analyze_references.py`, seeding
    its root set and dynamic-edge overlay from this inventory. (Direct dependent.)
  - **055** `add_dead_code_candidate_checker` — writes `check_dead_code.py` (needs
    054's graph).
  - **056** `classify_unused_functions_and_files` — the classification report (needs
    055).
  - **057** `delete_safe_dead_code_candidates` — the **only** deletion step; **High
    risk**; uses this inventory's §7.3 live-by-string allow-list as its deletion
    firewall (needs 056).
  - **058** `add_dead_code_checker_to_quality_report` — folds dead-code counts into
    `generate_quality_report.py` (needs 057).
- **Companion planning docs (read, not blocking):**
  `013_reference_graph_and_dead_code_plan.md` (methodology),
  `007_subtask_index.md` (dead-code chain + group membership),
  `045_inventory_github_workflows.md` (sibling inventory whose R11 CI-script list this
  subtask reuses).

No other subtask must complete before 053 begins.

## 16. Risk Level

**Low.** Changes runtime code: **No.** This subtask reads existing Python/TS/YAML/JSON
and writes one Markdown report (optionally one JSON companion). No runtime code,
import, prompt, config, workflow, frontend, or directory name is touched; every public
contract (CLI, `ari.public.*`, MCP, dashboard API, file formats, skill→core
interfaces) is trivially preserved. The only CI-visible side effect is the possibility
of a directory-README parity gate under `docs/refactoring/` (not expected — no such
README exists today), mitigated by `readme_sync.py --check`/`--write`. Worst realistic
failure is a **stale or incomplete root inventory**, which would let subtask 057 later
mark a live-by-string module (e.g. a publish backend) as deletable — this is precisely
why the §7.3 allow-list and the `file:line` evidence rule are mandatory, and why the
§12 re-verification recipe and the cross-check against `013`/`007` exist.

## 17. Notes for Implementer

- **Ground everything in `file:line`.** Subtask 054 seeds its analyzer from this
  inventory and 057 uses the §7.3 allow-list as its deletion firewall, so cite anchors
  precisely (`publish/__init__.py:198`, `llm_evaluator.py:165-169`, `routing.py:37`,
  `cli/__init__.py:82-100`). If any anchored file changes before 054/057 run, the
  citation makes the drift obvious.
- **The publish backends are the canonical hazard.** All four
  `publish/backends/*.py` (213/48/139/134 LOC) have **no static importer**; they are
  reached only through `_load_backend`'s string `if/elif`. They MUST be in the
  live-by-string allow-list. This is the concrete example the whole dead-code chain
  exists to protect (013 §2, `007_subtask_index.md:633`).
- **Separate the loader from the data.** `ari/schemas/load()`/`schema_path()` is
  **TEST_ONLY** (no production importer), but `node_report.schema.json` /
  `publish.schema.json` are **live data** (tests + mirrored enums). Classify the
  functions and the files separately; do not fold them together.
- **Walk both MCP idioms.** FastMCP `@mcp.tool` (10 skills, ~59 decorators) and
  low-level `Tool(name=...)` (4 skills, ~27 entries). Key tool roots by
  `(skill, tool_name)` and emit the collision report — do not de-duplicate collisions
  away, since the flat namespace clobbers silently (last skill wins).
- **Tests and docs are second-class roots.** R9 (tests) justifies only TEST_ONLY
  liveness and R10 (docs) only DOCS_ONLY liveness; neither justifies production
  liveness. Keep them in a separate carve-out so 056 does not over-count production
  reachability.
- **No `sonfigs/` anywhere.** Record the real trio — `ari/config/` (locator code),
  `ari/configs/` (packaged default data), top-level `config/` (rubric/profile data +
  `workflow.yaml`) — and state `sonfigs/` "does not exist".
- **Reserve "deprecated" for external contracts.** For the `server:main` entrypoint
  noise, the `origin/<base_ref>`-style idioms, or any internal cleanup, use
  REVIEW_REQUIRED / ADAPT, not "deprecated".
- **Determinism, no LLM.** Any helper that builds the inventory must be deterministic
  and make no network/LLM calls (design principle P2). Prefer a documented
  `find`/`grep`/`wc` recipe or a small read-only script under `scripts/` **not** wired
  into any workflow (wiring is a later phase).
- **Do not resolve open questions in 053.** The 013 §10-vs-007 numbering discrepancy,
  the flat MCP namespace, and the two coexisting checkpoint dirs are **REVIEW_REQUIRED**
  — record them; resolution belongs to 054/014/005, not 053.
- **Cross-check, do not overwrite.** If the inventory disagrees with `013` or
  `007_subtask_index.md`, record the discrepancy in the new artifact; those planning
  docs are owned by other subtasks.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **053** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
