# Subtask 054: Add Reference Graph Analyzer

> **Phase:** Phase 1 — Measurement and Inventory
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `main` · `ari-core` version `0.9.0` · planning date `2026-07-01`
> **Primary output:** `scripts/analyze_references.py` (net-new; **does not exist** today) which emits `docs/refactoring/reports/reference_graph.json`
> **Runtime code change:** **No** (adds a read-only static/dynamic analysis script + its config/test under `scripts/`; touches no runtime code, imports, prompts, runtime config, workflows, or frontend)
> **Classification of the artifact:** KEEP (net-new analyzer) — realizes `docs/refactoring/013_reference_graph_and_dead_code_plan.md` §6/§8. It only *produces* an inventory graph; it never proposes DELETE/MERGE/MOVE_TO_LEGACY on runtime code.
>
> **Vocabulary.** Node/module classification uses the master set KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE / REVIEW_REQUIRED. Symbol-level dead-code buckets (`PUBLIC_CONTRACT`, `DYNAMIC_REFERENCE_RISK`, `TEST_ONLY`, `DOCS_ONLY`, `QUARANTINE_CANDIDATE`, `SAFE_DELETE_CANDIDATE`, `REVIEW_REQUIRED`) are **defined and applied by the classifier subtask 055**, not here — 054 only *builds the graph* those buckets are computed from.

---

## 1. Goal

Deliver `scripts/analyze_references.py`: a deterministic, stdlib-`ast`-based reference-graph analyzer that emits a single machine-readable artifact, `docs/refactoring/reports/reference_graph.json`, over the ARI codebase. The graph:

- Enumerates **nodes** (Python modules/symbols, TS/TSX modules, data files, routes, MCP tools) and **edges** (static import/call, dynamic string-key/path, MCP dispatch, cross-language HTTP/WS) per the schema in `013_reference_graph_and_dead_code_plan.md` §6.1.
- Seeds reachability from the **root set** produced by subtask **053** (`inventory_reference_roots`), i.e. roots R1–R12 of `013` §3 (console script, CLI tree, MCP registration, dashboard routes, public API, tests, docs, CI scripts, registry HTTP).
- **Overlays the dynamic edges** that a naive import graph cannot see (§5 of `013`): string-keyed backend dispatch, prompt/rubric/schema path lookups, MCP tool dispatch across the stdio boundary, cross-language HTTP/WS calls, and `ARI_*` env-var reader/writer pairs. This overlay is the load-bearing reason the analyzer exists — *"absence of a static import edge is necessary but not sufficient evidence of deadness"* (`013` §2).

The analyzer **only reads and writes its own report artifact**. It never edits runtime code, and it is *not* the dead-code classifier — it produces the graph that the classifier (`check_dead_code.py`, subtask 055) consumes. Per ARI design principle **P2**, it must be deterministic: no LLM calls, no network, stable node/edge ordering, byte-identical reruns on the same commit (`013` §6.4).

## 2. Background

`docs/refactoring/013_reference_graph_and_dead_code_plan.md` (512 lines, already authored) is the methodology parent for the entire dead-code chain. It defines the root set (§3), the symbol/edge categories (§4), the six dynamic-reference sources (§5), the `reference_graph.json` schema (§6.1), and the tooling split (§8). This subtask implements the *analyzer* half of that plan.

**Authoritative mapping (`docs/refactoring/007_subtask_index.md` lines 100–105, 149, 164–165):** the dead-code chain is the strict linear sequence **053 → 054 → 055 → 056 → 057 → 058**, all Phase 1 except 057 (Phase 2, the only deletion) and 058 (Phase 8, quality report). The index rows are:

| ID | Name | Deliverable | Depends | Runtime change |
|----|------|-------------|---------|----------------|
| 053 | `inventory_reference_roots` | Reference-roots inventory | — | No |
| **054** | **`add_reference_graph_analyzer`** | **`analyze_references.py`** | **053** | **No** |
| 055 | `add_dead_code_candidate_checker` | `check_dead_code.py` | 054 | No |
| 056 | `classify_unused_functions_and_files` | Dead-code classification report | 055 | No |
| 057 | `delete_safe_dead_code_candidates` | Removal of confirmed-dead code | 056 | **Yes** |
| 058 | `add_dead_code_checker_to_quality_report` | Dead-code section in quality report | 057 | No |

**Reconciliation note.** The parent plan `013` §10 sketched an earlier split where subtask 053 delivered `analyze_references.py` (static only) and 054 was a separate "dynamic-edge overlay". The authoritative subtask index (`007`) reorganizes this: **053 is the roots inventory**, and **054 is the single analyzer script that builds the complete graph — static edges *and* the §5 dynamic overlay *and* cross-language edges *and* the MCP collision report**. This subtask follows the index (the authoritative cross-doc mapping and the human title assigned to 054, "Add Reference Graph Analyzer"). The overlay is folded into 054 because the classifier (055) requires a *complete* graph; a static-only graph would misclassify the dynamic seams of §6 as dead.

**Existing tooling this must not duplicate.** `scripts/docs/check_ref_coupling.py` (6488 B) and `scripts/docs/check_doc_sources.py` (7665 B) already model **doc↔code** coupling. `analyze_references.py` models **code↔code / code↔data** reachability and must not re-derive their doc-link logic. Ruff (`0.15.2`, installed) is the authority on unused *imports/locals* (`F401` 341, `F841` 39, `F811` 8); this analyzer is the authority on *cross-module/cross-language reachability* and ingests ruff's JSON as corroborating hints only.

## 3. Scope

In scope:

- Create `scripts/analyze_references.py` following the established `scripts/docs/` house style (`#!/usr/bin/env python3`, module docstring citing `013`/`007`, `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[1]`, PyYAML as the only non-stdlib import guarded to `SystemExit(2)`, exit `2` on usage/environment error).
- **Static layer:** walk `ari-core/ari/**/*.py` and `ari-skill-*/src/**/*.py` with the stdlib `ast` module; extract `py.module` / `py.symbol` nodes and `static.import` / `static.call` edges at **all depths** (module top-level *and* inside functions/`try` blocks — the guarded/lazy imports are real edges; §5.6 of `013`).
- **Root seeding:** consume the reference-roots manifest produced by **053**; fall back to seeding directly from `ari-core/pyproject.toml` `[project.scripts]`, the Typer tree under `ari-core/ari/cli/`, the `ari.public.*` submodule set, and the `viz` route registrations if the manifest is absent.
- **Dynamic overlay:** inject the six §5 edge sources of `013` (see §7.2) as `dynamic.string_key` / `dynamic.path` / `dynamic.mcp` / `cross_lang.http` edges, each with an **`evidence`** field (`file:line` + matched key/path/route string).
- **MCP collision report:** key `mcp.tool` nodes by `(skill, tool_name)` and emit the flat-namespace collision list (`013` §5.3).
- **Ruff ingestion:** fold `ruff check ari-core --output-format=json` (`F401`/`F841`/`F811` as "possibly-unused" hints; `E402` as "walk lazy/guarded imports" markers) into node metadata — never as the sole liveness verdict.
- Emit `docs/refactoring/reports/reference_graph.json` (§6.1 schema) deterministically.
- Add a unit/smoke test `scripts/tests/test_analyze_references.py` and a small optional config `scripts/quality/analyze_references.yaml` (scan roots, ignore globs).

Out of scope (see §4).

## 4. Non-Goals

- **Do NOT classify dead code or emit `dead_code_candidates.md`.** That is subtask **055** (`check_dead_code.py`), which consumes this graph and applies the §7 precedence rules of `013`. 054 stops at the graph + collision report.
- **Do NOT delete, move, or quarantine any code.** Deletion is subtask **057** only; quarantine (`MOVE_TO_LEGACY`) is subtask **056**. This subtask changes no runtime file.
- **Do NOT wire the analyzer into any `.github/workflows/*`.** The 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are untouched; CI wiring for the quality scripts is subtask **032** / the 058 quality-report chain.
- **Do NOT install new heavy dependencies.** `radon` is NOT installed and is not needed (no complexity analysis here); no third-party graph library (`networkx` etc.) — stdlib `ast`/`importlib` + PyYAML only. No `pnpm` (npm only) — the TS layer uses a string/AST-lite scan, **not** a Node/TS compiler.
- **Do NOT fabricate a `sonfigs/` node.** There is **no `sonfigs/` directory** anywhere in the repo. The analyzer keys strictly on the confusable real trio: `ari-core/ari/config/` (Python *locator* code), `ari-core/ari/configs/` (packaged default DATA + `_loader.py`), and top-level `ari-core/config/` (rubric/profile DATA).
- **Do NOT modify `ari-core/ari/**`, `ari-skill-*/src/**`, prompts, runtime YAML, or the frontend.**
- **No LLM calls, no network, no wall-clock in node bodies** (P2 determinism).

## 5. Current Files / Directories to Inspect

Static-scan targets (verified present):

- `ari-core/ari/**/*.py` — core scan target (**30,277 LOC**; `viz` 8,131, `pipeline` 3,900, `agent` 3,303, `orchestrator` 2,996, `cli` 2,582, top-level `.py` 2,796).
- `ari-skill-*/src/**/*.py` — the 14 skill packages (≈25.5k LOC; largest: `ari-skill-paper/src/server.py` 2956, `ari-skill-transform/src/server.py` 2465, `ari-skill-paper-re/src/_paperbench_bridge.py` 2376).
- `ari-core/pyproject.toml` (44 lines) — `[project.scripts]` `ari = "ari.cli:app"` (the only console script; root R1).
- `ari-core/ari/cli/__init__.py` (175 lines) — Typer tree + `_reorder_commands_for_compat()` (lines 148–170) + guarded sub-typer imports (lines 82–100).
- `ari-core/ari/public/` — the 8 stable submodules (`claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`); `public/__init__.py` is docstring-only (root R7).

Dynamic-seam sources (all verified at the cited lines on 2026-07-01):

- **Publish backends** — `ari-core/ari/publish/__init__.py:198` `def _load_backend(name)`; `if/elif` at lines 199/201/203/208 over `"ari-registry" | "local-tarball" | "zenodo" | "gh"` → `ari-core/ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` (all four files present). Keys mirrored in `ari-core/ari/schemas/publish.schema.json` (enum).
- **Evaluator composites** — `ari-core/ari/evaluator/llm_evaluator.py:165` `_COMPOSITES: dict[str, callable]`; keys `harmonic_mean`/`arithmetic_mean`/`weighted_min`/`geometric_mean` (lines 166–169) → functions `weighted_harmonic_mean`(75)/`weighted_arithmetic_mean`(102)/`weighted_min`(122)/`weighted_geometric_mean`(141). Keys must track the `EvaluatorConfig.composite` Literal (`ari-core/ari/config/__init__.py:212`).
- **LLM backend routing** — `ari-core/ari/llm/routing.py:37` `resolve_litellm_model(model, backend)` over `anthropic`/`claude`/`ollama`/`cli-shim`.
- **Prompt keys → `.md` files** — `ari-core/ari/prompts/_loader.py:41` `FilesystemPromptLoader.load(key)`, `:45` `load_versioned(key, version)`. Templates under `ari-core/ari/prompts/`: `agent/system.md`; `evaluator/{extract_metrics,peer_review}.md`; `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`; `pipeline/keyword_librarian.md`; `viz/{wizard_chat_goal,wizard_generate_config}.md` (11 templates, referenced by **no** import). Skill-local prompts: `ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`.
- **JSON schemas** — `ari-core/ari/schemas/__init__.py:11` `load(name)`, `:18` `schema_path(name)` → `node_report.schema.json`, `publish.schema.json`. (Per `013` §5.2 the *loader functions* have no production importer — TEST_ONLY-reachable; the analyzer records the edges so 055 can classify loader vs data separately.)
- **Config DATA loaders** — `ari-core/ari/configs/_loader.py` `FilesystemConfigLoader` (packaged `defaults.yaml`, `model_prices.yaml`); `ari-core/ari/config/finder.py` locates config files.
- **Rubric/profile DATA** — `ari-core/config/paperbench_rubrics/*.yaml`, `ari-core/config/reviewer_rubrics/*.yaml` (**23 files** verified), `ari-core/config/profiles/{cloud,hpc,laptop}.yaml`, `ari-core/config/reviewer_rubrics/fewshot_examples/neurips/*.json`; selected by `ari paper --rubric`/`ARI_RUBRIC` and `--profile`.
- **MCP dispatch** — `ari-core/ari/mcp/client.py`: `list_tools()` (line 297), `call_tool()` (line 336), `_tool_registry: dict[str,str]` (line 283; assigned line 325; read line 379), `to_claude_mcp_config()` (line 437, emits `mcp__<skill>__<tool>`). The 14 `ari-skill-*/src/server.py` servers declare tools in two idioms (10 FastMCP `@mcp.tool` ≈59 decorators; 4 low-level `Server` `Tool(name=…)` ≈27).
- **Cross-language HTTP/WS** — `ari-core/ari/viz/frontend/src/services/api.ts` (24877 B / 863 LOC) + WebSocket clients ↔ `ari-core/ari/viz/routes.py` (1197) + the **14** `ari-core/ari/viz/api_*.py` modules + `ari-core/ari/viz/websocket.py`.
- **CLI env-var reader/writer pairs** — writers verified: `ari-core/ari/config/__init__.py:316` sets `ARI_MEMORY_BACKEND`; `ari-core/ari/cli/projects.py:81` `ARI_RUBRIC`, `:86` `ARI_FEWSHOT_MODE`; `ari-core/ari/cli/run.py:202` `ARI_IDEA_VIRSCI_REAL`, `:204` `ARI_IDEA_VIRSCI_K`, `:206` `ARI_IDEA_VIRSCI_TEAM_SIZE`.

House-style / spec references (read before writing):

- `docs/refactoring/013_reference_graph_and_dead_code_plan.md` §3 (roots), §4 (categories), §5 (dynamic sources), §6 (output format), §8 (tooling strategy) — the primary spec.
- `docs/refactoring/007_subtask_index.md` lines 100–105, 164–169 — the authoritative chain and the dynamic-root callouts.
- `scripts/docs/check_doc_sources.py`, `scripts/readme_sync.py` — the `#!/usr/bin/env python3` + docstring-citing-spec + `argparse` + `REPO_ROOT = parents[1]` + `SystemExit(2)` idiom.
- The sibling checker plan `docs/refactoring/subtasks/026_add_import_boundary_checker_script.md` §7 — the AST-walk, `scripts/quality/` config, and `scripts/tests/` conventions to mirror.

Directories that **do not exist yet** and are created by this subtask: `docs/refactoring/reports/` currently holds no files (verified empty); `scripts/quality/` does **not** exist (created here, shared with sibling checkers 025–031); `scripts/tests/` does **not** exist (created here).

## 6. Current Problems

1. **No reference graph exists.** There is no artifact from which reachability can be computed; `scripts/analyze_references.py` and `docs/refactoring/reports/reference_graph.json` are both absent (verified negative). Dead-code triage (055/056) has no input.
2. **Import-only analysis would be actively wrong here.** ARI is import-driven at its extensibility seams. Concrete live-but-statically-orphan cases the analyzer must capture as dynamic edges:
   - The four `ari/publish/backends/*.py` modules have **no static importer** — they are lazily imported *by string name* in `_load_backend` (`publish/__init__.py:198`). A pure import graph flags all four as dead; they are the live `ari publish`/EAR path.
   - The 11 prompt `.md` templates under `ari/prompts/` are referenced by **no import at all** — reached only by string `.load(key)`.
   - The 23 reviewer rubrics + paperbench rubrics + 3 profiles are selected by *identifier* via `--rubric`/`ARI_RUBRIC`/`--profile`; no import references them.
   - Every MCP tool handler is reachable only by its **string tool name over stdio**; ari-core never imports skill modules for dispatch.
   - `services/api.ts` fetch/WS calls reach `viz` handlers over HTTP/WS — a cross-language edge no Python-only *or* TS-only graph sees.
3. **The flat MCP namespace hides collisions.** `MCPClient._tool_registry` (`client.py:283`) maps `tool_name → skill.name` **globally**, so two skills exposing the same bare snake_case tool name silently clobber (last skill wins). If the analyzer de-duplicates `mcp.tool` nodes by name, it *hides* this hazard — it must key by `(skill, tool_name)` and surface a collision report.
4. **Guarded/lazy imports evade naive walkers.** `ari/cli/__init__.py:82-100` registers `memory`/`ear`/`registry` sub-typers behind broad `try/except Exception`; `_load_backend` and prompt-loader helpers import lazily in-function. Ruff already reports **135 `E402`** and **8 `F811`**; the AST walker must treat these as real edges, not skip them.
5. **Empty package shells mislead export-based tools.** `ari-core/ari/__init__.py` is empty and `ari-core/ari/public/__init__.py` is docstring-only (re-exports nothing at top level). A tool that equates "public API = `__init__.__all__`" would conclude the public surface is empty and mark it all dead — the opposite of the truth. The analyzer must treat the `ari.public.*` submodules as roots regardless of `__all__`.

## 7. Proposed Design / Policy

A single stdlib-`ast` + PyYAML analyzer. Deterministic, no LLM, no network (P2). Structure: (a) load roots, (b) build static graph, (c) inject dynamic overlay, (d) ingest ruff hints, (e) emit `reference_graph.json` + collision report.

### 7.1 CLI contract

```
scripts/analyze_references.py
  --roots <file>        # reference-roots manifest from subtask 053 (default: docs/refactoring/reports/reference_roots.json if present, else auto-seed §7.3)
  --config <file>       # default: scripts/quality/analyze_references.yaml (scan roots, ignore globs)
  --output <file>       # default: docs/refactoring/reports/reference_graph.json
  --include-skills      # scan ari-skill-*/src/** (default: on)
  --include-frontend    # scan viz/frontend/src/** for cross_lang.http edges (default: on)
  --ruff / --no-ruff    # ingest `ruff check ari-core --output-format=json` hints (default: on if ruff present, else skip with a note)
  --format json         # only json for the primary artifact (markdown summary optional, stderr)
  --check               # exit 1 if the emitted graph differs from the committed one (determinism/CI hook; used by 058)
```

Exit convention (matches `check_doc_sources.py`): `0` = graph written/unchanged; `1` = `--check` drift; `2` = usage/environment error (missing PyYAML, unreadable root manifest).

### 7.2 Node & edge model (from `013` §4)

- **Node kinds:** `py.module`, `py.symbol`, `ts.module`, `ts.symbol`, `data.file`, `route`, `mcp.tool`. Each node carries `id`, `kind`, `file`, `loc`, `reachable_from`, `edges_in`. (Category tags and the final `classification` are computed by **055**, not here; 054 MAY leave `classification` absent or `null`.)
- **Edge kinds:** `static.import`, `static.call`, `dynamic.string_key`, `dynamic.path`, `dynamic.mcp`, `cross_lang.http`. Every dynamic/cross-lang edge MUST carry an `evidence` string (`file:line` + matched key/path/route). **Dynamic edges without evidence are not permitted** (`013` §6.1) — this keeps the graph falsifiable.

### 7.3 Static layer

- Enumerate `ari-core/ari/**/*.py` and (when `--include-skills`) `ari-skill-*/src/**/*.py`; parse each with `ast.parse`.
- Walk `ast.Import`/`ast.ImportFrom` at **all** depths (top-level, in-function, in `try`). Resolve `ImportFrom.level > 0` as intra-package. Record `static.import` edges.
- Extract top-level `FunctionDef`/`AsyncFunctionDef`/`ClassDef`/assigned constants as `py.symbol` nodes; record `static.call` for resolved intra-repo name references (best-effort attribute/name resolution — no runtime import).
- Seed roots from the 053 manifest; if absent, auto-seed R1/R2/R7/R6 from `pyproject.toml` `[project.scripts]`, the `ari.cli` Typer tree, the `ari.public.*` submodule set, and `viz` route registrations.

### 7.4 Dynamic overlay (the six §5 seams)

Targeted, evidence-carrying scans — implement one detector per seam, each emitting edges with `evidence`:

1. **String-keyed factories** → `dynamic.string_key`: string literals in the `_load_backend` `if/elif` (`publish/__init__.py:198`) → the 4 backend modules; keys of `_COMPOSITES` (`llm_evaluator.py:165`) → the 4 `weighted_*` callables; `resolve_litellm_model` branches (`routing.py:37`); the `ARI_MEMORY_BACKEND`-gated memory backend (`ari/core.py:130` hardcodes `LettaMemoryClient`; env set at `config/__init__.py:316`) as a `dynamic_target` *risk* even where no dispatch consumes it.
2. **Prompt keys** → `dynamic.path`: every string literal passed to `FilesystemPromptLoader.load(...)`/`load_versioned(...)` (and skill-local loaders) → the `.md` file under `ari/prompts/<key>.md` (and skill `prompts/`).
3. **Config/rubric/schema paths** → `dynamic.path`: `configs/_loader.py` keys → `configs/*.yaml`; `--rubric`/`ARI_RUBRIC`/`--profile` identifiers → `ari-core/config/{paperbench_rubrics,reviewer_rubrics,profiles}/*`; `schemas.load(name)`/`schema_path(name)` → `*.schema.json`.
4. **MCP dispatch** → `dynamic.mcp`: every `@mcp.tool`/`Tool(name=…)` handler across the 14 servers becomes an `mcp.tool` node keyed by `(skill, tool_name)` with a `dynamic.mcp` inbound edge from R4/R5; emit the **collision report** for duplicate bare names.
5. **Cross-language HTTP/WS** → `cross_lang.http`: regex/AST-lite match of endpoint path strings between `services/api.ts` fetch/WS calls and `viz` route registrations (`routes.py` + 14 `api_*.py` + `websocket.py`).
6. **CLI env-var pairs**: pair `os.environ[...]`/`setdefault("ARI_*")` writers (verified sites in §5) with `getenv("ARI_*")` readers so env-mediated liveness is recorded (`dynamic.string_key` with an `env:` evidence prefix).

### 7.5 Ruff ingestion

Run `ruff check ari-core --output-format=json` (ruff `0.15.2` present). Fold `F401` (341), `F841` (39), `F811` (8) into node metadata as `ruff_hints: ["F401", …]` ("possibly-unused"); treat `E402` (135) as a "lazy/guarded import present — walk it" marker. Ruff is corroborating signal only; it never sets a liveness verdict (that is 055's job). If ruff is absent, skip with a recorded note (graph still valid).

### 7.6 Output & determinism

- Emit `reference_graph.json` per `013` §6.1: `{schema_version, generated_at, commit, roots[], nodes[], edges[], collisions[]}`.
- **P2 determinism:** sort `nodes`/`edges`/`collisions` by `id`; the only wall-clock value is the top-level `generated_at`; **no LLM calls, no network**. Two runs on the same commit must produce byte-identical `nodes`/`edges`/`collisions` arrays. `--check` re-emits and diffs to enforce this.
- `node_modules/` under `frontend/` is ignored entirely (committed-vendored-deps hygiene issue tracked elsewhere; never a graph input).

## 8. Concrete Work Items

1. Create `scripts/analyze_references.py` with the `scripts/docs/` header idiom, `REPO_ROOT = Path(__file__).resolve().parents[1]`, PyYAML guard → `SystemExit(2)`, and the `argparse` surface of §7.1.
2. Implement the static layer (§7.3): `collect_python_nodes_edges(paths)` walking `ast.Import`/`ast.ImportFrom` at all depths + top-level symbol extraction + best-effort `static.call`.
3. Implement root loading: parse the 053 manifest; implement the auto-seed fallback (pyproject scripts, Typer tree, `ari.public.*`, viz routes).
4. Implement the six dynamic detectors (§7.4), each emitting `evidence`-carrying edges; assert no dynamic edge is emitted without evidence.
5. Implement the MCP collision report keyed by `(skill, tool_name)` (§7.4 item 4).
6. Implement the cross-language endpoint-string matcher (§7.4 item 5) over `services/api.ts` ↔ `viz` routes (string/AST-lite, no TS compiler).
7. Implement ruff ingestion (§7.5) with graceful skip when ruff is unavailable.
8. Implement deterministic JSON emission + `--check` drift mode (§7.6); write to `docs/refactoring/reports/reference_graph.json`.
9. Create `scripts/quality/analyze_references.yaml` (scan roots, ignore globs incl. `node_modules/`, `__pycache__/`).
10. Create `scripts/tests/test_analyze_references.py`: (a) fixture tree with a string-keyed factory asserts a `dynamic.string_key` edge with evidence is emitted and the "orphan" target is NOT edge-less; (b) a two-skill fixture with a duplicate MCP tool name asserts a collision entry; (c) a repo smoke test asserts the 4 `publish/backends/*` modules and the 11 prompt `.md` templates each have ≥1 inbound dynamic edge (i.e. are NOT graph orphans); (d) determinism: two runs produce byte-identical `nodes`/`edges`.
11. Regenerate per-directory READMEs so `scripts/readme_sync.py --check` stays green: new `scripts/quality/README.md`, `scripts/tests/README.md`, and updated `scripts/README.md` `## Contents`.

## 9. Files Expected to Change

Created by this subtask (all net-new; none exists today):

- `scripts/analyze_references.py` — the reference-graph analyzer.
- `scripts/quality/analyze_references.yaml` — scan-root/ignore config (new `scripts/quality/` directory, shared with sibling checkers 025–031).
- `scripts/tests/test_analyze_references.py` — unit + smoke + determinism tests (new `scripts/tests/` directory).
- `scripts/quality/README.md`, `scripts/tests/README.md` — per-directory READMEs (`## Contents` convention) required by `readme_sync.py --check`.
- `scripts/README.md` — updated `## Contents` (regenerated by `readme_sync.py --write`).

Generated (report artifact, not hand-authored source):

- `docs/refactoring/reports/reference_graph.json` — produced by running the analyzer. Whether it is committed or `.gitignore`d is deferred to subtask **033 (`add_generated_files_gitignore_policy`)**; this subtask writes it under `docs/refactoring/reports/` (currently empty) and leaves the commit/ignore decision to 033. Do not hand-edit it.

Explicitly **not** changed: any `ari-core/ari/**`, any `ari-skill-*/src/**`, any prompt template, any runtime YAML under `ari-core/config/`, `ari-core/ari/config/`, or `ari-core/ari/configs/`, any `.github/workflows/*`, and any file under `ari-core/ari/viz/frontend/` (read-only scan only).

## 10. Files / APIs That Must Not Be Broken

This subtask adds a read-only analyzer and **cannot** break a runtime contract, but the design must *preserve them conceptually*:

- **CLI** `ari = ari.cli:app` and every subcommand/flag/`ARI_*` env side effect — read as roots, never modified.
- **`ari.public.*`** (8 submodules) — treated as R7 roots; not modified or narrowed.
- **MCP tool contracts** — bare snake_case tool names, `inputSchema`, the `{"result"|"error"}` envelope, and `mcp__<skill>__<tool>` naming: the analyzer *records* them (and their collisions) but never renames or removes a tool.
- **Dashboard API** — `ari/viz/routes.py` + the 14 `api_*.py` endpoints + `websocket.py` consumed by `services/api.ts`: modeled as R6 roots + `cross_lang.http` edges; never altered.
- **Checkpoint/output/config file formats** (`ari/checkpoint.py`; YAML under `config/`+`configs/`) — untouched.
- **`ari-skill-* → ari-core` stable interface** and the sanctioned `ari-core → ari_skill_memory` edge — recorded, never used to justify a rename/removal in this subtask.
- **Scripts invoked by workflows** (`scripts/readme_sync.py`, `scripts/docs/check_*`) — untouched; the new READMEs must keep `readme_sync.py --check` green.

## 11. Compatibility Constraints

- **Contract classification vocabulary:** the artifact is **KEEP** (net-new analyzer). It *feeds* later ADAPT/MOVE_TO_LEGACY/DELETE_CANDIDATE decisions (055/056/057) but encodes none itself.
- The word **"deprecated"** is reserved for external contracts (public API, CLI, MCP, dashboard API, documented import paths, `ari-skill` stable interfaces). It is **not** applied to internal graph orphans — those are (later) `SAFE_DELETE_CANDIDATE`/`QUARANTINE_CANDIDATE`, computed by 055.
- **Determinism (P2):** stdlib `ast`/`importlib` + PyYAML only; no LLM, no network; stable sort by `id`; byte-identical reruns. Mirrors the "no LLM calls" contract of `ari-skill-memory` and `scripts/readme_sync.py`.
- **Tooling constraints:** `radon` NOT installed (irrelevant — no complexity analysis); `ruff 0.15.2` available (ingested as hints, optional); `python`/`compileall`/`pytest` available; `node`/`npm` available, **no `pnpm`** (the TS layer is a string/AST-lite scan, no compiler). Add no new third-party runtime dependency.
- **No `sonfigs/`.** The analyzer must key on the real trio (`ari/config/` code, `ari/configs/` packaged data, top-level `config/` rubric data) and must never emit a `sonfigs/*` node.
- **Rollout:** advisory only. This subtask flips no gate to blocking and touches no CI (the 058 chain and subtask 032 own that).

## 12. Tests to Run

From the repo root:

- `python -m compileall scripts/analyze_references.py` — byte-compile the new script; also `python -m compileall .` for the tree.
- `pytest -q scripts/tests/test_analyze_references.py` — the new unit/smoke/determinism tests (§8 item 10). Also `pytest -q ari-core/tests/` to confirm no regression (this subtask touches no runtime code, so it must stay green).
- `ruff check .` — lint the new script (it must add zero ruff findings of its own).
- Manual acceptance runs:
  - `python scripts/analyze_references.py --output /tmp/rg.json` writes valid JSON matching the `013` §6.1 schema; every `dynamic.*`/`cross_lang.http` edge carries a non-empty `evidence`.
  - Run twice; `diff` the two outputs' `nodes`/`edges`/`collisions` arrays → byte-identical (P2). `python scripts/analyze_references.py --check` exits `0` on the committed graph, `1` on drift.
- `python scripts/readme_sync.py --check` — the new READMEs and `## Contents` entries must be in sync.

(No `npm test` / `npm run build`: the frontend is *scanned read-only* for endpoint strings; this subtask ships no frontend change.)

## 13. Acceptance Criteria

1. `scripts/analyze_references.py` exists, is byte-compilable, ruff-clean, and follows the `scripts/docs/` house style (shebang, docstring citing `013`/`007`, `argparse`, `REPO_ROOT = parents[1]`, `SystemExit(2)` on missing PyYAML).
2. Running the analyzer emits `docs/refactoring/reports/reference_graph.json` conforming to the `013` §6.1 schema (`schema_version`, `generated_at`, `commit`, `roots`, `nodes`, `edges`, `collisions`).
3. **Dynamic overlay proven:** the 4 `ari/publish/backends/*.py` modules, the 11 `ari/prompts/**.md` templates, and the 23 `reviewer_rubrics/*.yaml` files each have ≥1 inbound `dynamic.*` edge with a `file:line` evidence string, i.e. **none is a graph orphan** despite having no static importer.
4. **MCP layer:** every `@mcp.tool`/`Tool(name=…)` handler across the 14 servers appears as an `mcp.tool` node keyed by `(skill, tool_name)`; any duplicate bare tool name appears in `collisions[]`.
5. **Cross-language edges:** at least the obvious `services/api.ts` → `viz` route matches appear as `cross_lang.http` edges with the matched path string as evidence.
6. **Determinism:** two consecutive runs on the same commit produce byte-identical `nodes`/`edges`/`collisions`; `--check` distinguishes unchanged (`0`) from drift (`1`).
7. No `dynamic.*`/`cross_lang.http` edge lacks `evidence`. No `sonfigs/*` node exists in the output.
8. `pytest -q` (new tests + `ari-core/tests/`), `python -m compileall .`, `ruff check .`, and `readme_sync.py --check` all pass. No `.github/workflows/*`, no `ari-core/ari/**`, no `ari-skill-*/src/**`, no frontend, and no runtime config file is modified.

## 14. Rollback Plan

The change is purely additive and read-only, so rollback is trivial and risk-free:

- `git rm scripts/analyze_references.py scripts/quality/analyze_references.yaml scripts/tests/test_analyze_references.py` (and the two new READMEs), delete `docs/refactoring/reports/reference_graph.json` if it was committed, then `python scripts/readme_sync.py --write` to drop the `## Contents` entries and revert `scripts/README.md`.
- Because nothing imports the analyzer at runtime and it is not wired into any workflow, removal cannot affect `ari`, the dashboard, MCP skills, checkpoint/config formats, or any test outside `scripts/tests/`. No data migration or contract impact. The downstream classifier (055) simply has no input until re-added.

## 15. Dependencies

Per the provided **DEPENDENCY GRAPH** (`053 -> 054 -> 055 -> 056 -> 057 -> 058`) and `007_subtask_index.md` line 101:

- **Hard prerequisite: subtask 053 (`inventory_reference_roots`).** 054 consumes the reference-roots manifest 053 produces (roots R1–R12 of `013` §3, plus the recorded dynamic reference roots — `_load_backend` string keys, `_COMPOSITES`, `ari.schemas.load()` per index lines 164–169). If 053 delivered prose only, 054's §7.3 auto-seed fallback covers R1/R2/R6/R7; but 053's dynamic-root list is the authoritative input for §7.4 completeness. **054 must not start its dynamic overlay design before 053's root inventory is settled.**
- **Not gated by the other inventory subtasks.** The rule "inventory subtasks (001, 002, 020, 036, 045, **053**, 059, 060, 067) must precede any runtime code change" applies to 054 **only through 053** — 054 is itself **not a runtime code change** (Section 16), so 001/002/020/036/045/059/060/067 do not block it. `001`'s LOC/ruff baseline is *useful context* (fed into §7.5 ruff ingestion) but not a hard edge.
- **Downstream consumers (depend on this):** **055** (`check_dead_code.py`) consumes `reference_graph.json` to classify candidates; **056** builds the classification report from 055; **057** deletes only confirmed `SAFE_DELETE_CANDIDATE` nodes; **058** folds dead-code counts into the quality report. The parent methodology is `docs/refactoring/013_reference_graph_and_dead_code_plan.md`.

## 16. Risk Level

**Low.** **Runtime code change: No.** The subtask adds a standalone, read-only analyzer plus its YAML config and a test module under `scripts/`, and writes one JSON report under `docs/refactoring/reports/`. It imports nothing from `ari-core`/`ari-skill-*` at runtime, is not referenced by any of the 5 workflows, and cannot alter the `ari` CLI, the dashboard, MCP tools, checkpoint/config formats, or the frontend. The only failure mode is the analyzer being *wrong* (false orphans / missed dynamic edges), which is bounded by the §13 acceptance tests (publish backends, prompts, rubrics, MCP handlers must all be non-orphan) and the "no dynamic edge without evidence" invariant. Matches the index rating (Phase 1, Risk **Low**, Runtime **No**).

## 17. Notes for Implementer

- **Parse with AST, never grep, for imports.** Guarded (`try/except`) and in-function imports are the norm at the extensibility seams (`cli/__init__.py:82-100`, `_load_backend`). `ast.walk` catches every real import and ignores comments/strings automatically; a grep would miss them or trip on false positives.
- **Every dynamic edge needs evidence.** Refuse to emit a `dynamic.*`/`cross_lang.http` edge without a `file:line` + matched-string `evidence`. This is the falsifiability guarantee of `013` §6.1 and the single most important correctness property; the `test_analyze_references.py` suite must assert it.
- **Key MCP tools by `(skill, tool_name)`, not by name.** The flat global namespace (`MCPClient._tool_registry`, `client.py:283`) clobbers duplicate names silently. De-duplicating nodes by bare name would *hide* the very hazard 055/056 need to see — always emit the `collisions[]` list.
- **The two MCP server idioms differ.** 10 FastMCP skills use `@mcp.tool()` decorators (≈59); 4 low-level `Server` skills (coding, evaluator, hpc, orchestrator) use `Tool(name=…)` entries (≈27) returning `list[TextContent(...)]`. The detector must recognize both to enumerate all handlers.
- **Treat `ari.public.*` submodules as roots regardless of `__all__`.** `ari/__init__.py` is empty and `ari/public/__init__.py` is docstring-only; an export-based heuristic would mark the whole public surface dead. Seed R7 from the 8 submodule filenames.
- **Do not fabricate `sonfigs/`.** Key strictly on `ari-core/ari/config/` (code), `ari-core/ari/configs/` (packaged data), and top-level `ari-core/config/` (rubric data). Assert in a test that no output node path contains `sonfigs`.
- **Keep ruff optional.** ruff (`0.15.2`) is available now, but the analyzer must degrade gracefully (record a note, still emit a valid graph) if it is absent — ruff is corroborating signal, not the liveness authority.
- **Determinism is a hard gate.** Sort every array by `id`; keep the only timestamp at the top level (`generated_at`); no LLM, no network. Wire `--check` so 058/CI can assert the committed graph is current. Mirror the `readme_sync.py --check` / `check_*` gate pattern already used in `docs-sync.yml` / `readme-sync.yml`.
- **Stay in your lane vs. 055.** 054 emits nodes/edges/collisions and MAY leave `classification` null. Do **not** apply the §7 precedence rules of `013` (PUBLIC_CONTRACT / DYNAMIC_REFERENCE_RISK / … / SAFE_DELETE_CANDIDATE) — that is 055's contract, and duplicating it here would create two sources of truth.
- **Name files with the `analyze_references` prefix** under `scripts/quality/` so subtask 031's aggregator (`generate_quality_report.py`) and 058 can discover this analyzer's output unambiguously alongside the sibling `check_*` outputs.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **054** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
