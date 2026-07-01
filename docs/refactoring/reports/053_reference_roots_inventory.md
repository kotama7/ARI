# 053 — Reference Roots Inventory

> **Subtask:** `053_inventory_reference_roots` (Phase 1: Measurement and Inventory) ·
> **Risk:** Low · **Runtime code change:** No · **Depends on:** — (root inventory) ·
> **Enables:** `054 → 055 → 056 → 057 → 058`.
>
> **Status:** Read-only inventory artifact. This document changes **no** runtime code,
> imports, prompts, configs, workflows, frontend, or directory names. It is the frozen
> reference-root baseline that subtask **054** (`analyze_references.py`) seeds its root
> set from, **055** (`check_dead_code.py`) classifies against, and **057** uses as its
> "never delete" allow-list (§3, the deletion firewall).
>
> **Repo baseline:** `/home/t-kotama/workplace/ARI` · git branch `whole_refactoring` ·
> `ari-core` version `0.9.0` (`ari-core/pyproject.toml:7`) · HEAD `2a20bd9` ·
> verification date **2026-07-01**.
>
> **Provenance note:** The subtask plan `subtasks/053_inventory_reference_roots.md`
> cites planning HEAD `dcfeacd`; the working tree at generation time is at HEAD
> `2a20bd9` (branch `whole_refactoring`). Every anchor below was **re-verified live**
> against the current tree; where a count or path diverges from the planning docs it is
> recorded as observed and flagged in §10/§12.
>
> **Vocabulary.** Directory/module decisions use KEEP / ADAPT / MERGE / MOVE_TO_LEGACY /
> DELETE_CANDIDATE / REVIEW_REQUIRED. Symbol-level dead-code buckets follow
> `013 §7` (PUBLIC_CONTRACT / DYNAMIC_REFERENCE_RISK / TEST_ONLY / DOCS_ONLY /
> QUARANTINE_CANDIDATE / SAFE_DELETE_CANDIDATE / REVIEW_REQUIRED). The word
> "deprecated" is reserved for external contracts only.

---

## 1. Static Root Set (R1–R12)

All twelve roots verified present at HEAD `2a20bd9`. Each is a live, contract-bearing
root → **KEEP**. `LOC` = `wc -l` at verification.

| # | Root class | Concrete anchor (`file:line`) | Verified | Notes |
|---|------------|-------------------------------|----------|-------|
| **R1** | Console script | `ari-core/pyproject.toml:34` `[project.scripts]` `ari = "ari.cli:app"` (`:33` heading) | ✅ present | The **only** console script in the repo. |
| **R2** | CLI app + top-level command tree | `ari-core/ari/cli/__init__.py:78` `app = typer.Typer(name="ari")` (174 LOC); order pinned by `_reorder_commands_for_compat()` `:148-170` (invoked `:170`) | ✅ present | 11 top-level commands (below). |
| **R3** | Guarded CLI sub-typers | `cli/__init__.py:82-100` (`memory`/`ear`/`registry` under `try/except Exception`); `migrate` at `:107` (unguarded) | ✅ present | Modules: `ari/memory_cli.py`, `ari/cli_ear.py`, `ari/registry/cli.py`, `ari/cli/migrate.py` (all present). |
| **R4** | MCP skill servers | 14 × `ari-skill-*/src/server.py` | ✅ 14/14 | FastMCP: benchmark, idea, memory, paper, paper-re, plot, replicate, transform, vlm, web (10). Low-level `mcp.server.Server`: coding, evaluator, hpc, orchestrator (4). Tool handlers are roots (§6). |
| **R5** | MCP client bridge | `ari-core/ari/mcp/client.py` (483 LOC): `list_tools` `:209`/`:297`, `call_tool` `:227`/`:336`, `_tool_registry` `:283`, `to_claude_mcp_config` `:437` (emits `mcp__<skill>__<tool>`) | ✅ present | Sole public symbol per `ari/mcp/__init__.py`. |
| **R6** | Dashboard HTTP/WS routes | `ari/viz/routes.py` (1197) + 14 × `ari/viz/api_*.py` + `websocket.py` (36), `server.py` (201), `state.py` (79), `state_sync.py` (117) | ✅ present | 14 `api_*.py` modules enumerated in §9. |
| **R7** | Public Python API | `ari/public/{claim_gate,config_schema,container,cost_tracker,llm,paths,run_env,verified_context}.py` (8 submodules; 148 LOC incl. `__init__.py`) | ✅ 8/8 | Exact `__all__` per submodule in §3/§5; `__init__.py` is docstring-only (re-exports nothing at top level). |
| **R8** | Frontend entrypoint | `ari/viz/frontend/src/App.tsx`; API client `.../services/api.ts` (863 LOC) | ✅ present | Cross-language roots into R6 (§9). |
| **R9** | Test suites | `ari-core/tests/` (heaviest: `test_server.py` 1844, `test_gui_errors.py` 1650, `test_workflow_contract.py` 1606) + per-skill / frontend `__tests__/` | ✅ present | **TEST_ONLY** roots — do **not** justify production liveness (§5). |
| **R10** | Documented commands | `ari …` invocations in `README*.md` / `docs/`; validated by `scripts/docs/check_doc_sources.py` (present) | ✅ present | Observed in `README.md`: `ari run/clone/resume/paper/status/skills-list/viz/projects/show/delete/settings/memory/ear` (**DOCS_ONLY** liveness only). |
| **R11** | Scripts invoked by CI | 12 targets across `.github/workflows/*` (§ list below) | ✅ 12 | See enumeration; matches subtask 045's frozen set. |
| **R12** | Registry / EAR HTTP surface | `ari/registry/app.py:22` `build_app(data_dir=None)`; routes `:46 /healthz`, `:50 /version`, `:54 POST /artifact`, `:80 GET /artifact/{id}`, `:100 HEAD`, `:114 /manifest.lock`, `:121 /promote`, `:139 DELETE`; served via `ari registry serve` | ✅ present | Distinct from the DI-style "registry" name (`013 §5`). |

**R2 top-level commands** (callback `file:line`; order frozen by
`_reorder_commands_for_compat()` canonical list `cli/__init__.py:150-162`):

| Command | Callback anchor | Callback name (reorder key) |
|---|---|---|
| `clone` | `cli/commands.py:53` | `cmd_clone` |
| `run` | `cli/run.py:168` | `run` |
| `resume` | `cli/run.py:446` | `resume` |
| `paper` | `cli/projects.py:61` | `paper` |
| `status` | `cli/projects.py:171` | `status` |
| `skills-list` | `cli/commands.py:143` | `skills_list` |
| `viz` | `cli/commands.py:169` | `viz` |
| `projects` | `cli/projects.py:222` | `list_projects` |
| `show` | `cli/projects.py:284` | `show_project` |
| `delete` | `cli/commands.py:105` | `delete_project` |
| `settings` | `cli/commands.py:196` | `settings_cmd` |

**R3 sub-typer groups:** `ari memory` (`memory_cli.py`), `ari ear` (`cli_ear.py`),
`ari registry` (`registry/cli.py`), `ari migrate` (`cli/migrate.py`).

**R7 public submodule exports** (from each module's `__all__`, verified):

| Submodule | Exported symbols | Backed by |
|---|---|---|
| `public/claim_gate.py` | `run_hard_gate, check_emission, classify_concept, scan_science_data, CONCEPT_INVARIANTS` | `ari.pipeline.claim_gate*` |
| `public/config_schema.py` | `ARIConfig, BFTSConfig, CheckpointConfig, EvaluatorConfig, LLMConfig, LoggingConfig, SkillConfig` | `ari.config` |
| `public/container.py` | `from ari.container import *` (dynamic `__all__`; `ari/container.py` declares no `__all__`) | `ari.container` |
| `public/cost_tracker.py` | `from ari.cost_tracker import *` (docstring names `bootstrap_skill`/`record`/`init_from_env`) | `ari.cost_tracker` |
| `public/llm.py` | `LLMClient` | `ari.llm.client` |
| `public/paths.py` | `PathManager` | `ari.paths` |
| `public/run_env.py` | `from ari.agent.run_env import *` (no `__all__` in impl → `dir()` fallback; incl. `capture_env` `:31`, `read_run_env` `:97`, `shell_capture_snippet` `:175`) | `ari.agent.run_env` |
| `public/verified_context.py` | `render_grounded_block, write_verified_context, build_verified_context` | `ari.pipeline.verified_context` |

**R11 — 12 CI-invoked scripts** (from `.github/workflows/*`):
`scripts/check_i18n.py`, `scripts/readme_sync.py`,
`scripts/docs/{assemble_site.sh, check_doc_links.py, check_doc_sources.py,
check_i18n_js.py, check_readme_parity.py, check_ref_coupling.py,
check_report_cochange.py, check_site_i18n.py, check_translation_freshness.py,
sync_report_pdf.sh}`.
Observation (§12): the `check_i18n.py` target lives at `scripts/check_i18n.py`, not
`report/scripts/check_i18n.py` as `010 §9`/`013 §3-R11` prose implies — recorded, not
resolved here. `scripts/git-hooks/pre-commit:19-24` also invokes
`scripts/readme_sync.py --write` (not a CI root, but a live tooling caller).

---

## 2. Dynamic Reference Sources (D1–D6)

Each seam carries `file:line` **evidence** (013 §6.1 falsifiability rule). Every D-row
is **DYNAMIC_REFERENCE_RISK** → never a deletion candidate.

| ID | Seam | Anchor (`file:line`) | Live targets (verified) |
|----|------|----------------------|--------------------------|
| **D1** | String-keyed publish backends | `ari/publish/__init__.py:198` `_load_backend(name)` `if/elif` (`:199-213`, keys `"ari-registry" \| "local-tarball" \| "zenodo" \| "gh"`) | `backends/{ari_registry.py(213), local_tarball.py(48), zenodo.py(139), gh.py(134)}` — **no static importer** (grep confirmed). Keys mirrored in `ari/schemas/publish.schema.json:51` enum (which also lists `"s3"` — see §10). |
| **D2** | Evaluator composites dict | `ari/evaluator/llm_evaluator.py:165-170` `_COMPOSITES` (consumed `:280,:286`) | 4 callables: `weighted_harmonic_mean` `:75`, `weighted_arithmetic_mean` `:102`, `weighted_min` `:122`, `weighted_geometric_mean` `:141`. Keys `harmonic_mean/arithmetic_mean/weighted_min/geometric_mean` mirror `EvaluatorConfig.composite` Literal (`config/__init__.py:212`). |
| **D3** | LLM backend routing | `ari/llm/routing.py:37` `resolve_litellm_model(model, backend=None)` | Provider-prefix branches `anthropic\|claude → anthropic/`, `ollama → ollama_chat/`, `cli-shim\|cli_shim → openai/`; `backend` defaults to `getenv("ARI_BACKEND")` (env-coupled, see D6). |
| **D4** | Prompt / config / rubric / schema path lookups | Prompt loader `ari/prompts/_loader.py:24 load` / `:28 load_versioned`; `ari/configs/_loader.py`; `ari/config/finder.py`; `ari/schemas/__init__.py:11 load`/`:18 schema_path`; CLI `--rubric`/`--profile` | 11 prompt `.md` (§3), packaged `configs/{defaults,model_prices}.yaml`, 23 reviewer rubrics, 4 paperbench rubrics, 3 profiles, 3 fewshot JSON, 2 schema JSON, `config/workflow.yaml`. All by string key / filesystem path — no `import`. |
| **D5** | MCP tool dispatch (stdio) | `ari/mcp/client.py:227/:336 call_tool`; 14 × `ari-skill-*/src/server.py` | 87 tool handlers keyed by `(skill, tool_name)` (§6), reached only by string name over stdio; PUBLIC_CONTRACT. |
| **D6** | Cross-language HTTP/WS + `ARI_*` env pairs | `viz/frontend/src/services/api.ts` ↔ `viz/routes.py`+`api_*.py`; WS `{"type":"update"}` (`websocket.py:27`, `state_sync.py:45`); `getenv("ARI_*")` readers vs CLI writers | 55 distinct endpoint literals in `api.ts` matched against route registrations (§9); 80 distinct `ARI_*` readers vs CLI writers (§8). |

**Prompt `.load(...)` call sites** (8 explicit + 3 config-indirected, covering all 11
templates):

| Template key | Call site |
|---|---|
| `orchestrator/root_idea_selector` | `orchestrator/root_idea_selector.py:63` |
| `orchestrator/lineage_decision` | `orchestrator/lineage_decision.py:293` |
| `orchestrator/bfts_expand` | `orchestrator/bfts.py:744` |
| `orchestrator/bfts_select` | `orchestrator/bfts.py:477` (key via `config.select_prompt` default) |
| `orchestrator/bfts_expand_select` | `orchestrator/bfts.py:557` |
| `pipeline/keyword_librarian` | `pipeline/context_builder.py:117` |
| `viz/wizard_chat_goal` | `viz/api_tools.py:55` |
| `viz/wizard_generate_config` | `viz/api_tools.py:127` |
| `evaluator/extract_metrics` | `evaluator/llm_evaluator.py:255` |
| `evaluator/peer_review` | `evaluator/llm_evaluator.py:413` |
| `agent/system` | `agent/loop.py:46` `_SYSTEM_PROMPT_KEY = "agent/system"` |

---

## 3. Live-by-String Allow-List (the 057 deletion firewall)

Files/symbols with **no static importer** that MUST be treated as live. Per `013 §9`:
if a 057 deletion candidate appears here, it is reclassified out of
SAFE_DELETE_CANDIDATE and the workflow stops. All paths verified present.

| # | Item | Path / anchor | Count | Rationale |
|---|------|---------------|-------|-----------|
| 1 | Publish backends | `ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py` | 4 | Reached only via `_load_backend` string `if/elif` (`publish/__init__.py:199-213`). Canonical hazard. |
| 2 | Evaluator composite callables | `evaluator/llm_evaluator.py:75,102,122,141` | 4 | Reached only via `_COMPOSITES[composite]` (`:286`). |
| 3 | Prompt templates | `ari/prompts/**/*.md` (non-README) | 11 | `agent/system`; `evaluator/{extract_metrics,peer_review}`; `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}`; `pipeline/keyword_librarian`; `viz/{wizard_chat_goal,wizard_generate_config}`. Reached by string key via `FilesystemPromptLoader.load()`. |
| 4 | Reviewer rubrics | `config/reviewer_rubrics/*.yaml` | 23 | Selected by `ari paper --rubric` / `ARI_RUBRIC`. No import. |
| 5 | PaperBench rubrics | `config/paperbench_rubrics/{generic,nature,neurips,sc}.yaml` | 4 | Selected by identifier. |
| 6 | Profiles | `config/profiles/{cloud,hpc,laptop}.yaml` | 3 | Selected by `--profile`. |
| 7 | Fewshot JSON | `config/reviewer_rubrics/fewshot_examples/neurips/*.json` | 3 | `attention.json`, `132_automated_relational.json`, `2_carpe_diem.json`. Selected by fewshot mode. |
| 8 | JSON schemas (data) | `ari/schemas/{node_report,publish}.schema.json` | 2 | Live **data** (test reads + mirrored enums); the loader **functions** are TEST_ONLY (§5). |
| 9 | Workflow graph | `config/workflow.yaml` (23,661 bytes) | 1 | Loaded by `cli/run.py:91,245,400`; copied into each checkpoint. |

**Allow-list total: 51 items** (4+4+11+23+4+3+3+2+1). Skill-local prompt trees
(`ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`) are the same
class within their packages (record for 054's per-skill overlay).

---

## 4. Data Reference Roots (config triple)

Three real, distinct directories — record all three exact paths; fabricate no fourth:

| Path | Role | Key contents |
|---|---|---|
| `ari-core/ari/config/` | Python **locator code** | `finder.py` (workflow/profile discovery; `package_config_root()` → `ari-core/config/`), `__init__.py` (Pydantic models + `auto_config()`) |
| `ari-core/ari/configs/` | packaged **default data** + loader | `_loader.py`, `defaults.yaml`, `model_prices.yaml` |
| `ari-core/config/` | shipped **rubric/profile/workflow data** | `default.yaml`, `workflow.yaml`, `profiles/`, `paperbench_rubrics/`, `reviewer_rubrics/` (23) |

**`sonfigs/` does not exist.** `find -iname '*sonfig*'` matches only a planning-doc
filename (`docs/refactoring/subtasks/003_consolidate_config_configs_sonfigs.md`); there
is **no `sonfigs/` directory** (`ls sonfigs` → "No such file or directory"). There is
also **no top-level `pyproject.toml`** (`ari-core/pyproject.toml` is the core manifest).

---

## 5. TEST_ONLY / DOCS_ONLY Carve-Outs

Roots that justify **only** test/docs liveness, never production liveness — keep
separate so 056 does not over-count production reachability.

- **TEST_ONLY.** `ari/schemas/__init__.py` `load()` (`:11`) / `schema_path()` (`:18`)
  have **no production importer** (repo-wide grep: only `ari/schemas/README.md:4`
  documents it; `tests/test_node_report.py:30` reads the `.json` by direct filesystem
  path, bypassing the loader). Classify the **loader functions** as TEST_ONLY; the
  **`.json` data files** are live (§3 item 8). Record separately.
- **DOCS_ONLY.** R10 documented `ari …` commands validated by
  `scripts/docs/check_doc_sources.py` justify only DOCS_ONLY liveness.
- **R9 tests** (heaviest listed in §1) are TEST_ONLY roots.

---

## 6. MCP Tool Set + Collision Report

Tool names keyed by `(skill, tool_name)`, extracted deterministically (AST: `@mcp.tool`
FastMCP decorators + low-level `Tool(name=...)`; no LLM, P2). **87 tools across 14
servers** (59 FastMCP + 28 low-level).

| Skill | Idiom | Count | Tool names |
|---|---|---|---|
| benchmark | FastMCP | 3 | analyze_results, plot, statistical_test |
| coding | Server | 5 | emit_results, read_file, run_bash, run_code, write_code |
| evaluator | Server | 3 | claim_evidence_hard_gate, evidence_grounded_semantic_review, make_metric_spec |
| hpc | Server | 9 | job_cancel, job_status, probe_platform_capabilities, singularity_build, singularity_build_fakeroot, singularity_pull, singularity_run, singularity_run_gpu, slurm_submit |
| idea | FastMCP | 1 | _load_virsci_snapshot_papers |
| memory | FastMCP | 15 | _set_current_node, add_experiment_result, add_failure_case, add_memory, add_procedure_memory, add_reflection, add_reproducibility_event, audit_memory, clear_node_memory, consolidate_node_memory, get_experiment_context, get_node_memory, get_verified_context, search_memory, search_research_memory |
| orchestrator | Server | 11 | get_ear, get_paper, get_status, get_workflow, list_children, list_files, list_runs, list_skills, read_file, run_experiment, stop_experiment |
| paper | FastMCP | 14 | check_format, compile_paper, generate_section, get_template, inject_code_availability, link_paper_claims, list_rubrics, list_venues, merge_reviews, paper_refine, review_compiled_paper, review_section, revise_section, write_paper_iterative |
| paper-re | FastMCP | 4 | build_reproduce_sh, fetch_code_bundle, grade_with_simplejudge, run_reproduce |
| plot | FastMCP | 2 | generate_figures, generate_figures_llm |
| replicate | FastMCP | 3 | audit_rubric, generate_rubric, suggest_target_leaf_count |
| transform | FastMCP | 5 | curate_ear, generate_ear, nodes_to_science_data, promote_ear, publish_ear |
| vlm | FastMCP | 3 | review_figure, review_figures_all, review_table |
| web | FastMCP | 9 | collect_references_iterative, fetch_url, list_uploaded_files, read_uploaded_file, search_arxiv, search_papers, search_semantic_scholar, set_retrieval_backend, web_search |

**Collision report** (bare tool name in >1 skill — the flat-namespace clobber hazard,
`MCPClient._tool_registry` last-skill-wins, `client.py:283`):

- **`read_file`** → `coding` **and** `orchestrator` (COLLISION; last-registered skill
  wins in the global registry). → **REVIEW_REQUIRED** (§10); do not de-duplicate away.

Observations (record only): `idea` exposes exactly one `@mcp.tool` decorator
(`_load_virsci_snapshot_papers`, `ari-skill-idea/src/server.py:393-394`);
`generate_ideas` (`:553`) is an internal async function, **not** a FastMCP tool. Tool
name `_set_current_node` (memory) and `_load_virsci_snapshot_papers` (idea) carry a
leading underscore but are genuine registered tools.

---

## 7. Negatives ("not roots" — do not over-seed)

- `ari/core.py:83` `build_runtime` and `:235` `generate_paper_section` are **internal**
  (CLI-only; reachable *from* R2), **not** independent public roots. `013 §3` also names
  these as explicit negatives.
- `ari-skill-replicate/pyproject.toml:27` (`ari-skill-replicate = "server:main"`) and
  `ari-skill-paper-re/pyproject.toml:29` (`ari-skill-paper-re = "server:main"`) are
  **entrypoint noise** — skills launch by filesystem path (`python <skill>/src/server.py`),
  so these console scripts are unused. Mark **REVIEW_REQUIRED**, not R1-class roots.

---

## 8. `ARI_*` Env Writer → Reader Pairs (D6 detail)

Env-mediated coupling invisible to imports. **80 distinct `ARI_*` readers** in
`ari-core/ari` (`getenv`/`environ.get`/`environ[...]`). Representative writer→reader
pairs (CLI writer → downstream reader liveness):

| Writer (CLI) | Env var(s) | Reader coupling |
|---|---|---|
| `cli/run.py:202-210` | `ARI_IDEA_VIRSCI_{REAL,K,TEAM_SIZE,N_AUTHORS,N_PAPERS}` | idea stage / virsci path |
| `cli/run.py:264-265` | `ARI_CONTAINER_{IMAGE,MODE}` | container runtime |
| `cli/projects.py:81-90` | `ARI_RUBRIC`, `ARI_FEWSHOT_MODE`, `ARI_NUM_REVIEWS_ENSEMBLE`, `ARI_NUM_REFLECTIONS` | evaluator / paper stage |
| `config/__init__.py:316` | `ARI_MEMORY_BACKEND` (`setdefault`) | **no core consumer** — core hardcodes `LettaMemoryClient` (`core.py:130`); `ARI_BACKEND` (D3) is the routed one. → DYNAMIC_REFERENCE_RISK, not orphan. |

054 should enumerate the full 80-reader set and pair each with its writer; this table is
the representative sample the subtask calls for.

---

## 9. Cross-Language HTTP/WS Edges (D6 detail)

Method for 054 (not resolved exhaustively here): extract endpoint path literals from
`services/api.ts` and match against route registrations in `viz/routes.py` + the 14
`api_*.py`. **55 distinct endpoint literals** in `api.ts`; representative confirmed
matches (string present in both the TS client and the Python route dispatch):

`/state`, `/api/settings`, `/api/checkpoints`, `/api/active-checkpoint`,
`/api/launch`, `/api/run-stage`, `/api/env-keys`, `/api/models`,
`/api/delete-checkpoint`, `/api/config/generate`, `/api/chat-goal`,
`/api/checkpoint/compile`, `/api/checkpoint/file/{save,delete}`,
`/api/paperbench/{papers,run,cost-estimate}`, `/api/scheduler/detect`,
`/api/gpu-monitor`, `/api/memory/restart`, `/api/publish/settings`.

**14 `ari/viz/api_*.py` modules** (R6): `api_experiment, api_fewshot, api_memory,
api_ollama, api_orchestrator, api_paperbench, api_paperbench_worker, api_process,
api_publish, api_settings, api_state, api_tools, api_wizard, api_workflow`.

**WebSocket (Contract D):** single message `type` `"update"` pushed from
`websocket.py:27` and `state_sync.py:45`; that shape is the contract.

---

## 10. REVIEW_REQUIRED / Open Items (record only — do not resolve here)

1. **Subtask-numbering discrepancy (013 §10 vs 007).** `013 §8.1` (line 396) and the
   `013 §10` mapping table (line 498) assign `analyze_references.py` to subtask **053**,
   but `007_subtask_index.md:100-101` defines **053 = inventory_reference_roots**
   (Runtime code change: No) and **054 = add_reference_graph_analyzer** →
   `analyze_references.py`. This artifact follows `007` (053 = inventory). →
   **REVIEW_REQUIRED** documentation discrepancy; do not edit `013` from 053.
2. **Flat MCP namespace collision.** `read_file` is registered by both `coding` and
   `orchestrator` (§6); the global `_tool_registry` (`client.py:283`) silently keeps the
   last-registered skill. → **REVIEW_REQUIRED**; resolution belongs to the MCP/skill
   stream, not 053.
3. **`publish.schema.json` enum lists an unimplemented backend.** `publish.schema.json:51`
   enum = `["ari-registry", "gh", "zenodo", "s3", "local-tarball"]` (5), but
   `_load_backend` (`publish/__init__.py:199-213`) handles only 4; there is **no `s3`
   branch and no `backends/s3.py`** (calling backend `"s3"` raises `unknown backend`). →
   `"s3"` is **not** a live-by-string target; record as enum-vs-impl drift, REVIEW_REQUIRED.
4. **Two coexisting checkpoint dirs** (root-level `checkpoints/` vs
   `workspace/checkpoints/`) — adjacent to reference roots; storage-path policy is the
   004/005 stream. Note only.
5. **`ARI_MEMORY_BACKEND` set without a core consumer** (§8) — DYNAMIC_REFERENCE_RISK,
   not an orphan; ownership is the registry/DI stream.

---

## 11. Regeneration / Verification Recipe (deterministic, no LLM)

Run from repo root; each figure below is reproducible (P2):

```sh
# R1 console script (expect: ari = "ari.cli:app")
grep -n 'ari = "ari.cli:app"' ari-core/pyproject.toml
# R4 MCP servers (expect: 14)
ls -1 ari-skill-*/src/server.py | wc -l
# R7 public submodules (expect: 8 + __init__.py)
ls ari-core/ari/public/*.py | grep -v __init__ | wc -l
# D1 publish backends (expect: 4 files; zero static importers)
ls ari-core/ari/publish/backends/*.py | grep -vE '__init__' | wc -l
# §3 allow-list data counts
find ari-core/ari/prompts -name '*.md' ! -name 'README.md' | wc -l   # 11
find ari-core/config/reviewer_rubrics -maxdepth 1 -name '*.yaml' | wc -l  # 23
find ari-core/config/paperbench_rubrics -name '*.yaml' | wc -l       # 4
find ari-core/config/profiles -name '*.yaml' | wc -l                 # 3
# D5 MCP tools (expect: 59 FastMCP + 28 low-level = 87); collision on read_file
#   (AST extractor: see the JSON companion 053_reference_roots.json)
# sonfigs does not exist
ls sonfigs 2>&1   # No such file or directory
```

A machine-readable companion — `053_reference_roots.json` — accompanies this file for
direct ingestion by subtask 054 (roots R1–R12, seams D1–D6, allow-list, tool set +
collisions, negatives).

---

## 12. Cross-Check Against 013 / 007

- **Static roots R1–R12:** all present; counts match `013 §3` (14 skills, 14 `api_*.py`,
  8 public submodules, 12 CI scripts). One prose divergence: `check_i18n.py` is at
  `scripts/` not `report/scripts/` (§1 R11).
- **Dynamic seams D1–D6:** all anchors match `013 §5` at current HEAD. Line drift from
  the planning citations is nil for the load-bearing anchors (`_load_backend:198`,
  `_COMPOSITES:165`, `resolve_litellm_model:37`).
- **Allow-list:** matches `013 §7.3` / `007:633` expectation (publish backends, prompts,
  rubrics, profiles, schemas, workflow.yaml); one addition — the `s3` enum-without-impl
  drift (§10 #3), which strengthens (does not weaken) the firewall.
- **Numbering discrepancy** (§10 #1) recorded, not resolved (per `053 §8.9`).
- **No planning doc edited.** Discrepancies are recorded here only.

---

## 13. Retirement Condition

This artifact is a read-only inventory produced by subtask 053. It is retired only when
subtask **053** is marked DONE in `docs/refactoring/007_subtask_index.md` and its
implementing PR is merged, per the canonical Document Retirement Policy in
`007_subtask_index.md`. Before any `git rm`, re-verify each §13 acceptance criterion of
`subtasks/053_inventory_reference_roots.md` against primary sources.
