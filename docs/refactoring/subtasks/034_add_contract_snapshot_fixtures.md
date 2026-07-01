# Subtask 034: Add Contract Snapshot Fixtures

> **Phase:** Phase 10 — Docs and Tests
> **Repo:** `/home/t-kotama/workplace/ARI` · branch `main` · `ari-core` version `0.9.0` · planning date `2026-07-01`
> **Primary output:** committed **golden snapshot fixtures** + a thin verification test under `ari-core/tests/` (and one deterministic generator under `scripts/`). All net-new; **do not exist** today.
> **Runtime code change:** No (adds test fixtures, a verification test module, and a read-only generator script; touches no runtime code, imports, prompts, runtime config, workflows, or frontend).
> **Classification of the artifact:** KEEP (net-new baseline data). It *records* the existing contracts so later refactor subtasks can prove they did not drift them; it never proposes changing a contract.

---

## 1. Goal

Create a set of **committed, machine-diffable "golden" snapshot fixtures** that freeze the four ARI stable contract surfaces as data, plus a thin, deterministic verification test that fails when the live surface drifts from the recorded snapshot. The four surfaces:

1. **Public Python API** — the exported symbol table of `ari.public.*` (8 submodules).
2. **CLI command/flag tree** — the `ari = ari.cli:app` Typer surface (top-level commands, sub-typers, options, and their env-var side effects).
3. **MCP tool catalog** — the tool-name set (and, where deterministically extractable, argument names / `inputSchema`) exposed by the 14 `ari-skill-*/src/server.py` servers, plus the `{"result"|"error"}` return-envelope and `mcp__<skill>__<tool>` naming invariants.
4. **Dashboard REST endpoint inventory** — the method+path set served by `ari/viz/routes.py` + `api_*.py`, plus the always-present response keys of the highest-traffic endpoints (extending the pattern already in `test_api_schema_contract.py`).

These fixtures are **baseline data for later phases**, not a new CI gate. They give the future runtime-refactor subtasks (which MUST NOT break these contracts) a single, reviewable diff surface: any PR that changes a contract must also change a golden file, making the change explicit and gate-able. The snapshot generator is deterministic (design principle P2 — no LLM, no network) and re-runnable.

## 2. Background

The repo already has **four partial, precedent-setting guards**, but **no committed golden snapshot fixtures** of the whole contract surface:

- `ari-core/tests/test_api_schema_contract.py` (~109 lines) pins the *always-present keys* of a handful of viz endpoints (`/api/checkpoints`, `/api/checkpoint/<id>/summary`, `/api/settings`) as an **additive/subset** contract against the frontend TypeScript types. It hard-codes the key lists inline; there is no external fixture and no endpoint-inventory snapshot.
- `ari-core/tests/test_public_api_boundary.py` (127 lines) and `ari-core/tests/test_skill_public_contract.py` (118 lines) enforce the *import boundary* (skills reach core only via `ari.public.*` / `ari.protocols.*`), but neither snapshots the **exported symbol table** of `ari.public.*` — a symbol could be removed/renamed from `ari.public.claim_gate` and both tests would stay green.
- `ari-core/tests/test_prompt_extraction.py` (108 lines) pins each externalised prompt by **sha256** in an inline `_EXPECTED_HASHES` list — the closest existing "snapshot" idiom (byte-identity, "update the list if intentional").
- `report/scripts/check_prompt_snapshots.py` (Gate 10) + `report/scripts/snapshot_prompts.py` implement the sibling pattern for the *report appendix*: a `% snapshot-from: <rel>@<sha256> @ commit <c>` header block plus a recorded SHA that must match the source bytes. This is the house convention for "snapshot fixture + regenerator + verifier" and 034 should mirror its shape (data file + generator + checker), scoped to code contracts instead of report prose.

The gap 034 fills: there is **no** committed golden of (a) the full `ari.public.*` symbol table, (b) the ~86 MCP tool names/schemas, (c) the `ari` CLI command/flag/env tree, or (d) the ~140 dashboard endpoints. The subtask index (`docs/refactoring/007_subtask_index.md` line 81) records 034 as Phase 10, Risk **Low**, Depends On **—**, Runtime Code Change **No**, Can Run Independently **Yes**; line 371 scopes it to "snapshots for `ari.public.*`, MCP tool schemas, dashboard endpoints"; line 581 lists 034 among the checkers/design/config subtasks that "can start immediately".

Contract inventory this fixture must reflect (from `docs/refactoring/010_contract_preservation_policy.md` and the packaging/viz area findings):

- **Public API** (`ari-core/ari/public/__init__.py`, 28 lines, docstring-only) re-exports 8 submodules: `claim_gate`, `config_schema`, `container`, `cost_tracker`, `llm`, `paths`, `run_env`, `verified_context`. Note `ari.public.__init__` re-exports *nothing at top level* — callers import the submodules — so the snapshot must key on `ari.public.<submodule>` symbol tables, not `dir(ari.public)`.
- **CLI** (`ari-core/ari/cli/__init__.py`, 175 lines): root `app = typer.Typer(name="ari")`, order pinned by `_reorder_commands_for_compat()` (lines 148–170, mutates `app.registered_commands`). 11 top-level commands + 4 `add_typer` groups (`memory`, `ear`, `registry`, `migrate`), several loaded behind broad `try/except Exception` import guards (a broken import silently drops a whole group — the snapshot makes such a regression visible).
- **MCP** (`ari-core/ari/mcp/client.py`, 484 lines): `list_tools()` (lines 209, 297) returns `[{name, description, inputSchema, skill_name}]`; `call_tool()` returns the `{"result": <text>}` or `{"error": ...}` envelope; `to_claude_mcp_config()` (line 437) emits `mcp__<skill>__<tool>` names. Servers use **two idioms**: FastMCP `@mcp.tool()` (10 skills, **59** decorators total — benchmark 3, idea 1, memory 15, paper 14, paper-re 4, plot 2, replicate 3, transform 5, vlm 3, web 9) and low-level `types.Tool(name=...)` (4 skills — coding, evaluator, hpc, orchestrator; **27 unique** per the area findings). Tool names are **bare snake_case in one flat namespace**, and `MCPClient._tool_registry` maps `tool_name → skill.name` globally, so **cross-skill name collisions silently clobber** — an invariant worth asserting from the snapshot.
- **Dashboard endpoints** (`ari/viz/routes.py`, 1197 lines): a single if/elif chain in `do_GET` (~86 branches) / `do_POST` (~51 branches) — there is **no route table** (the `api_wizard.py:30 WIZARD_ROUTES` dict is an abandoned partial attempt), so an exhaustive automatic parse is fragile; the snapshot is a curated inventory (seeded from the routed viz findings) plus a drift check for net-new path literals.

## 3. Scope

In scope (all net-new, non-runtime):

- Create a new fixtures directory `ari-core/tests/fixtures/contracts/` (no `ari-core/tests/fixtures/` exists today).
- Author four golden fixture files:
  - `public_api.json` — per-submodule exported-symbol table for `ari.public.*`.
  - `cli_tree.json` — the `ari` command tree (commands, sub-typers, option flags, and documented `ARI_*` env side effects).
  - `mcp_tools.json` — per-skill tool catalog (names; arg names / `inputSchema` where deterministically available) + the return-envelope/naming invariants.
  - `viz_endpoints.json` — method+path inventory + always-present response keys of the pinned high-traffic endpoints.
- Add one verification test module `ari-core/tests/test_contract_snapshots.py` that, in-process (safe for `ari-core`), regenerates the surfaces it can build without launching skill subprocesses (public API via import, CLI via Typer introspection, viz endpoint drift via AST scan of `routes.py`/`api_*.py`) and diffs them against the goldens with **surface-appropriate semantics** (exact-set for symbol/tool-name tables; additive/subset for response-key contracts, mirroring `test_api_schema_contract.py`).
- Add one deterministic generator/updater `scripts/snapshot_contracts.py` that regenerates the goldens; for MCP it must run **one skill per subprocess** (mirroring `scripts/run_all_tests.sh`) to avoid the cross-skill `src.server` import ambiguity documented in `pytest.ini`.
- Add `ari-core/tests/fixtures/contracts/README.md` and update the `## Contents` indexes (`ari-core/tests/README.md`, `scripts/README.md`) so `scripts/readme_sync.py --check` stays green.

Out of scope (see §4).

## 4. Non-Goals

- **Not the checker scripts.** 034 provides the *fixture data / baseline*, not a `scripts/quality/` gate. `check_public_api_contracts.py` (subtask **029**), `check_viz_api_schema.py` (subtask **030**, depends on 020), and `check_import_boundaries.py` (subtask **026**) are separate; they MAY consume 034's goldens as their baseline, but 034 does not implement them or wire any gate.
- **Not prompt snapshots.** The `ari/prompts/**` byte-identity snapshot is already covered by `test_prompt_extraction.py` + report Gate 10 and is extended by subtask **042 (add_prompt_snapshot_tests)**. 034 does not touch prompt fixtures.
- **Not CI wiring.** No `.github/workflows/*` file is changed; advisory/blocking CI integration is subtask **032 (add_quality_script_ci_plan)** and **046**. The 5 existing workflows (`docs-change-coupling.yml`, `docs-sync.yml`, `pages.yml`, `readme-sync.yml`, `refactor-guards.yml`) are not rewritten.
- **No runtime change.** Do NOT modify any `ari-core/ari/**`, any `ari-skill-*/src/**`, any prompt template, any YAML under `ari-core/config*/` / `ari-core/ari/config*/`, or any file under `ari-core/ari/viz/frontend/`. The snapshot **records** the contracts; it must never propose renaming/removing a symbol, tool, command, or endpoint.
- **No live-server load in the in-process suite.** The `ari-core/tests` run must not launch the 14 MCP servers (per `pytest.ini`, importing two skills' `src.server` in one process is ambiguous). MCP catalog capture happens only in the per-skill generator (§7.4) or via static AST.
- **No LLM, no network, no non-determinism** (P2). Snapshots must be byte-stable across runs (sorted keys, `ensure_ascii=False`, trailing newline) so diffs are meaningful.
- **No `sonfigs/` handling** — that directory does **not exist** in the repo (the "sonfigs" token in some planning prompts is a hypothesized typo); nothing here references it.

## 5. Current Files / Directories to Inspect

Contract surfaces the fixtures snapshot (all verified present 2026-07-01):

- `ari-core/ari/public/__init__.py` (28 lines, docstring-only) and the 8 submodules `ari-core/ari/public/{claim_gate,config_schema,container,cost_tracker,llm,paths,run_env,verified_context}.py` — the public-API surface. Known exports to seed `public_api.json`:
  - `claim_gate`: `run_hard_gate`, `check_emission`, `classify_concept`, `scan_science_data`, `CONCEPT_INVARIANTS`.
  - `config_schema`: `ARIConfig`, `BFTSConfig`, `CheckpointConfig`, `EvaluatorConfig`, `LLMConfig`, `LoggingConfig`, `SkillConfig`.
  - `container`: `from ari.container import *` (dynamic `__all__` — snapshot the resolved names).
  - `cost_tracker`: `from ari.cost_tracker import *` (docstring names `bootstrap_skill`/`record`/`init_from_env`).
  - `llm`: `LLMClient`; `paths`: `PathManager`.
  - `run_env`: `from ari.agent.run_env import *` (`capture_env`, `shell_capture_snippet`).
  - `verified_context`: `render_grounded_block`, `write_verified_context`, `build_verified_context`.
- `ari-core/ari/cli/__init__.py` (175 lines; `_reorder_commands_for_compat()` at 148–170, `app.registered_commands` at 164–167) plus `ari-core/ari/cli/{commands,run,projects}.py`, `ari-core/ari/memory_cli.py`, `ari-core/ari/cli_ear.py`, `ari-core/ari/registry/cli.py`, `ari-core/ari/cli/migrate.py` — the CLI tree to seed `cli_tree.json` (11 top-level commands: `clone`, `run`, `resume`, `paper`, `status`, `skills-list`, `viz`, `projects`, `show`, `delete`, `settings`; 4 sub-typers: `memory`, `ear`, `registry`, `migrate`).
- `ari-core/ari/mcp/client.py` (484 lines) — `list_tools()` (209/297), `inputSchema` at 219, `call_tool()` `{"result"|"error"}` envelope, `to_claude_mcp_config()` (437, `mcp__<skill>__<tool>`), `_tool_registry` clobber (283/325). The 14 servers to enumerate: `ari-skill-{benchmark,coding,evaluator,hpc,idea,memory,orchestrator,paper,paper-re,plot,replicate,transform,vlm,web}/src/server.py`.
- `ari-core/ari/viz/routes.py` (1197 lines) + `ari-core/ari/viz/api_*.py` (e.g. `api_experiment.py` 929, `api_paperbench.py` 813, `checkpoint_api.py`, `api_settings.py`) — the endpoint inventory to seed `viz_endpoints.json`; the frontend client it must match is `ari-core/ari/viz/frontend/src/services/api.ts` (863 lines).

Existing precedent to read before writing (match their idiom):

- `ari-core/tests/test_api_schema_contract.py` (~109 lines) — additive/subset response-key assertions, `monkeypatch` isolation of `ari.viz.state` globals; the `viz_endpoints.json` response-key checks should extend, not duplicate, these.
- `ari-core/tests/test_prompt_extraction.py` (108 lines) — the "pinned value + update-if-intentional" snapshot idiom.
- `report/scripts/check_prompt_snapshots.py` + `report/scripts/snapshot_prompts.py` — the snapshot header/SHA generator+verifier house style.
- `ari-core/tests/test_public_api_boundary.py` (127) / `test_skill_public_contract.py` (118) — AST-based repo scanning idiom (`Path(__file__).resolve().parents[2]` repo root, `ast.parse`, grandfathered allowlist) reusable by the viz-endpoint drift scan.
- `scripts/readme_sync.py` and `scripts/README.md` `## Contents` block — the per-directory README sync gate the new files must satisfy.

Directories that **do not exist yet** and are created here: `ari-core/tests/fixtures/` and `ari-core/tests/fixtures/contracts/`.

## 6. Current Problems

1. **No frozen baseline for `ari.public.*` symbols.** The import-boundary tests prove skills *use* `ari.public.*`, but nothing pins *what `ari.public.*` exports*. A refactor could silently drop `ari.public.claim_gate.CONCEPT_INVARIANTS` or rename `verified_context.build_verified_context` and every test would stay green until a skill breaks at runtime.
2. **No MCP tool catalog snapshot.** ~86 tools (59 FastMCP + 27 low-level) live in a flat snake_case namespace across two divergent server idioms. There is no artifact recording the canonical name set, so a rename, a dropped tool, or a **new cross-skill name collision** (which `MCPClient._tool_registry` resolves last-skill-wins, silently) is invisible to review.
3. **CLI groups can vanish silently.** `ari/cli/__init__.py` loads `add_typer` groups under broad `try/except Exception` guards (lines 82–100). A broken import in `cli_ear.py`/`registry/cli.py` drops the whole `ear`/`registry` group with no error. No snapshot records the expected command/flag tree, so such a regression ships unnoticed.
4. **Endpoint contract is only partially and inline-pinned.** `test_api_schema_contract.py` covers ~3 endpoints' keys; the other ~140 method+path pairs (subprocess launch, file write, checkpoint delete, SSE streams) have no inventory snapshot. Because `routes.py` dispatches via a giant if/elif chain with hand-rolled string matching, a removed/renamed path is easy to miss and hard to diff.
5. **No single reviewable "contract diff" surface.** The later runtime-refactor subtasks are *required* not to break these contracts (§10), but reviewers have no golden file whose diff would flag a breakage. 034 creates exactly that surface.

## 7. Proposed Design / Policy

A stdlib-only (`ast`, `json`, `importlib`, `subprocess`) design. Deterministic, no LLM, no network (P2). Each surface is snapshot with the *weakest semantics that still catches a real breakage*: exact-set for name tables, additive/subset for response payloads.

### 7.1 Fixture format & determinism

- All goldens are JSON with `sort_keys=True`, `ensure_ascii=False`, 2-space indent, trailing newline, so regeneration is byte-stable and diffs are minimal. Each file carries a top `"_meta"` block: `{"generated_by": "scripts/snapshot_contracts.py", "surface": "<name>", "ari_core_version": "0.9.0", "note": "regenerate with scripts/snapshot_contracts.py --surface <name> --update"}`. (Do NOT record a timestamp or commit SHA in the payload — that would break byte-stability; the report-appendix SHA header pattern is for prose files, not these regenerated data files.)
- Every fixture stores a `"schema_version": 1` so the reader/test can evolve the shape without ambiguity.

### 7.2 Public API surface (`public_api.json`) — in-process, exact-set

- The generator imports each `ari.public.<submodule>` (safe — pure `ari-core`) and records the sorted list of **public names** (`__all__` if defined, else names not starting with `_`, excluding re-imported modules). For the `import *` submodules (`container`, `cost_tracker`, `run_env`) it records the *resolved* names so a change in the underlying `ari.container`/`ari.cost_tracker`/`ari.agent.run_env` `__all__` is captured.
- Shape: `{"ari.public.claim_gate": ["CONCEPT_INVARIANTS", "check_emission", ...], ...}` for all 8 submodules.
- Test semantics: **exact set** per submodule. A removed/renamed symbol fails; an added symbol also fails (forcing an explicit golden update — additive API changes are still contract events worth reviewing). Failure message tells the implementer to run `--update` if intentional.

### 7.3 CLI surface (`cli_tree.json`) — in-process, structural

- The generator imports `ari.cli:app` and walks `app.registered_commands` + `app.registered_groups` (Typer/Click introspection) to record, per command: the command name, its option flags (long/short), and — for the commands with documented `ARI_*` env side effects (`run` → `ARI_IDEA_VIRSCI_*`; `paper` → `ARI_RUBRIC`/`ARI_FEWSHOT_MODE`/…) — a curated `env_side_effects` list seeded from the packaging findings §3.
- Records sub-typers (`memory`, `ear`, `registry` + nested `token`, `migrate`) and their subcommands so a silently-dropped group (§6 item 3) fails the snapshot.
- Test semantics: exact set of command names and sub-typer names; option flags compared as a set. The `env_side_effects` list is a curated, hand-maintained field (not machine-derivable) validated for presence only.

### 7.4 MCP surface (`mcp_tools.json`) — static primary + per-skill runtime enrichment

Because in-process import of two skills' `src.server` is ambiguous (`pytest.ini`), the **primary, P2-clean** capture is static AST:

- For FastMCP skills: AST-scan `ari-skill-*/src/server.py` for functions decorated with `@mcp.tool(...)`; record the function name (the tool name) and its parameter names. (10 skills, 59 tools.)
- For low-level skills (coding, evaluator, hpc, orchestrator): AST-scan for `types.Tool(name=...)` / `Tool(name=...)` literals; record the `name=` string and, if present as a literal, the `inputSchema` dict keys. (4 skills, 27 tools.)
- Shape: `{"benchmark": [{"name": "make_metric_spec", "args": ["..."], "idiom": "fastmcp"}, ...], ...}` plus a top-level `"invariants": {"return_envelope": ["result", "error"], "fq_name_pattern": "mcp__<skill>__<tool>", "namespace": "flat_snake_case"}`.
- **Optional runtime enrichment:** `scripts/snapshot_contracts.py --surface mcp --with-schema` launches each skill **one-per-subprocess** (reusing the isolation pattern of `scripts/run_all_tests.sh`) and calls the skill's tool-listing to capture the full runtime `inputSchema`. This path is opt-in (it imports skill deps) and stored in a sibling `mcp_tools.schema.json` if run; the primary `mcp_tools.json` stays static so the in-process test needs no subprocess.
- Test semantics (in-process): load `mcp_tools.json`, assert the tool-name set matches a fresh AST scan (exact set), and assert **no duplicate tool name across skills** (guards the `_tool_registry` clobber, §6 item 2). The invariants block is asserted for presence/value.

### 7.5 Dashboard endpoint surface (`viz_endpoints.json`) — curated inventory + drift scan

- Seed the inventory (method+path list) from the routed viz-area findings (the endpoint groups under `routes.py` inline, `checkpoint_api`, `api_experiment`, `api_settings`/`api_workflow`, `api_paperbench`, `api_tools`, `api_orchestrator`, `api_memory`, `ear`, `api_publish`, `api_fewshot`, `api_process`, `api_ollama`). Store as `{"endpoints": [{"method": "GET", "path": "/api/checkpoints", "owner": "checkpoint_api"}, ...]}`.
- **Response-key contract:** for the already-pinned high-traffic endpoints, reuse the exact key lists from `test_api_schema_contract.py` (do not fork them — import/reference the same source of truth, or explicitly note the intentional mirror) with **additive/subset** semantics.
- Drift check: a light AST/string scan of `routes.py`/`api_*.py` for path literals (`self.path == "..."`, `startswith`/`endswith`/`re.match` string args) flags **net-new** paths absent from the golden (so a new endpoint forces a golden update) and **missing** golden paths (removed endpoint). Because `routes.py` has no route table, this scan is best-effort and documented as such; it must not hard-fail on a path it cannot statically resolve — it only reports net-new/missing literals it *can* see.
- Test semantics: subset — every literal the scan resolves must be in the golden; the golden may legitimately contain endpoints the scan cannot resolve (dynamic paths). This keeps the check non-brittle while still catching obvious additions/removals.

### 7.6 Generator / update workflow

- `scripts/snapshot_contracts.py` follows the `scripts/docs/` house style (`#!/usr/bin/env python3`, module docstring citing this subtask + `010_contract_preservation_policy.md`, `argparse`, `REPO_ROOT = Path(__file__).resolve().parents[1]`, `SystemExit(2)` on environment error). Surface selector: `--surface {public,cli,mcp,viz,all}`; mode: `--check` (default, compare, exit 1 on drift) / `--update` (rewrite goldens). This mirrors `readme_sync.py`'s `--check`/`--write` convention.
- The pytest module `test_contract_snapshots.py` calls the same comparison functions the generator uses (single source of truth), parametrized per surface, so `pytest -q` and `python scripts/snapshot_contracts.py --check` agree.

## 8. Concrete Work Items

1. Create `ari-core/tests/fixtures/contracts/` and the four goldens (`public_api.json`, `cli_tree.json`, `mcp_tools.json`, `viz_endpoints.json`) with the `_meta`/`schema_version` envelope (§7.1).
2. Implement `scripts/snapshot_contracts.py` with the `--surface`/`--check`/`--update` CLI (§7.6): a `build_public()` (import-based, §7.2), `build_cli()` (Typer introspection, §7.3), `build_mcp_static()` (AST, §7.4) with optional `build_mcp_runtime()` behind `--with-schema`, and `build_viz()` (curated + AST drift, §7.5). Deterministic JSON emit (sorted keys, trailing newline).
3. Seed `public_api.json` by running `--surface public --update` and hand-verifying against the §5 known-export list.
4. Seed `cli_tree.json` by running `--surface cli --update`; hand-fill the curated `env_side_effects` for `run`/`paper` from packaging findings §3.
5. Seed `mcp_tools.json` by running `--surface mcp --update` (static AST, all 14 skills = 59 + 27 tools) and add the `invariants` block; assert the fresh scan yields no cross-skill duplicate name (fix the fixture, not the code, if the scan reveals one — a real collision is a finding for a later runtime subtask, recorded here as a `known_collisions` note, not "fixed").
6. Seed `viz_endpoints.json` from the routed viz-area endpoint inventory; wire the response-key checks to reuse `test_api_schema_contract.py`'s key lists.
7. Create `ari-core/tests/test_contract_snapshots.py`: parametrized per surface, exact-set for public/CLI/MCP names, additive/subset for viz keys, plus the "no duplicate MCP tool name" assertion. Failure messages must say "run `python scripts/snapshot_contracts.py --surface <x> --update` if the change is intentional."
8. Create `ari-core/tests/fixtures/contracts/README.md` (explains each golden + regeneration command) and update `## Contents` in `ari-core/tests/README.md` and `scripts/README.md` (regenerate via `scripts/readme_sync.py --write`).

## 9. Files Expected to Change

Created by this subtask (all net-new; none exists today):

- `ari-core/tests/fixtures/contracts/public_api.json` — `ari.public.*` symbol table.
- `ari-core/tests/fixtures/contracts/cli_tree.json` — `ari` command/flag/env tree.
- `ari-core/tests/fixtures/contracts/mcp_tools.json` — MCP tool catalog + invariants.
- `ari-core/tests/fixtures/contracts/viz_endpoints.json` — dashboard endpoint inventory + response-key contract.
- `ari-core/tests/fixtures/contracts/README.md` — per-directory README (`## Contents` convention).
- `ari-core/tests/test_contract_snapshots.py` — the verification test.
- `scripts/snapshot_contracts.py` — the deterministic generator/updater.

Modified (index/README sync only, no runtime code):

- `ari-core/tests/README.md` — new `## Contents` entries for the test + fixtures dir.
- `scripts/README.md` — new `## Contents` entry for `snapshot_contracts.py` (regenerated by `readme_sync.py --write`).

Explicitly **not** changed: any `ari-core/ari/**`, any `ari-skill-*/src/**`, any prompt template under `ari-core/ari/prompts/**`, any YAML under `ari-core/config*/` / `ari-core/ari/config*/`, any `.github/workflows/*`, and any file under `ari-core/ari/viz/frontend/`.

## 10. Files / APIs That Must Not Be Broken

This subtask only *records* contracts; it cannot and must not alter them. The design preserves (never proposes breaking) every surface below:

- **CLI** `ari = ari.cli:app` — all 11 top-level commands, 4 sub-typers, option flags, and their `ARI_*` env side effects. The snapshot reads them; it does not reorder or rename.
- **Public Python API** — every `ari.public.*` symbol in §5. The fixture records them; widening/narrowing is a later runtime subtask, never done here.
- **MCP tool contracts** — the ~86 tool names, `inputSchema`, the `{"result"|"error"}` return envelope, and `mcp__<skill>__<tool>` fully-qualified naming. Snapshot only.
- **Dashboard API** — `ari/viz/routes.py` + `api_*.py` method+path set and response shapes consumed by `services/api.ts` + `websocket.py`. Snapshot only; the additive/subset semantics match the wire policy (`{**defaults, **saved}` merges, extra keys allowed).
- **Checkpoint/output/config file formats** and **`ari-skill-* → ari-core` stable interface** — untouched; the fixtures live entirely under `tests/` and `scripts/`.
- **Scripts already invoked by workflows** (`scripts/readme_sync.py`, `scripts/docs/check_*`) — untouched; the new files must keep `readme_sync.py --check` green.
- The word **"deprecated"** is reserved for external contracts; nothing here marks internal code deprecated.

## 11. Compatibility Constraints

- **Classification:** the artifact is **KEEP** (net-new baseline data). It does not perform any **ADAPT/MERGE/MOVE_TO_LEGACY/DELETE_CANDIDATE** action on runtime code. If the MCP static scan surfaces a genuine cross-skill name collision, record it as a `known_collisions` note in `mcp_tools.json` and flag it **REVIEW_REQUIRED** for a later runtime subtask — do not fix it here.
- **Additive-contract semantics** for viz response keys (subset assertions) mirror `test_api_schema_contract.py` so the snapshot does not falsely fail when a new optional field is added; name-table surfaces (public/CLI/MCP) use exact-set so any change is an explicit, reviewed golden update.
- **Determinism (P2):** stdlib only (`ast`, `json`, `importlib`, `subprocess`); sorted-key JSON; no timestamps/commit SHAs in payloads; no LLM, no network. The in-process test must never launch a skill server (`pytest.ini` isolation).
- **Tooling constraints:** `radon`/`vulture` NOT installed (irrelevant); `ruff` IS available (lint the new script/test); `python -m compileall`/`pytest` available; `node`/`npm` available but **no `pnpm`** and **not needed** (034 is not a frontend subtask). Add no new third-party dependency.
- **No CI flip:** 034 adds fixtures + a test that runs in the existing `pytest -q` set; it does not add a new workflow or blocking gate (that is 032/046).

## 12. Tests to Run

From the repo root:

- `python -m compileall .` — byte-compile the tree, including `scripts/snapshot_contracts.py` and `ari-core/tests/test_contract_snapshots.py`.
- `pytest -q` — the full in-process `ari-core/tests` set including the new `test_contract_snapshots.py`; must stay green (034 touches no runtime code). Also run `pytest -q ari-core/tests/test_contract_snapshots.py` in isolation.
- `ruff check .` — lint the new script + test (keep clean).
- `python scripts/snapshot_contracts.py --surface all --check` — must exit `0` against the freshly-seeded goldens (self-consistency of generator vs fixtures).
- Optional (per-skill isolation, mirrors the full suite): `bash scripts/run_all_tests.sh` and, if capturing runtime schemas, `python scripts/snapshot_contracts.py --surface mcp --with-schema --update` run once per skill process.
- `python scripts/readme_sync.py --check` — the new README + `## Contents` entries must be in sync.

(No `npm test` / `npm run build`: 034 does not modify `ari-core/ari/viz/frontend/`. The `viz_endpoints.json` fixture *references* the frontend `services/api.ts` types conceptually but changes no frontend file.)

## 13. Acceptance Criteria

1. `ari-core/tests/fixtures/contracts/{public_api,cli_tree,mcp_tools,viz_endpoints}.json` exist, are byte-stable (re-running `--update` produces no diff), and each carries the `_meta`/`schema_version` envelope.
2. `public_api.json` records all 8 `ari.public.*` submodule symbol tables including the §5 known exports; `test_contract_snapshots.py` fails if any symbol is removed/renamed/added without a golden update.
3. `cli_tree.json` records the 11 top-level commands + 4 sub-typers (incl. nested `registry token`); the snapshot fails if a group is silently dropped by the `try/except` import guard.
4. `mcp_tools.json` records all 14 skills' tool names (59 FastMCP + 27 low-level = 86) with the `invariants` block; the test asserts **no duplicate tool name across skills** and a fresh AST scan matches the golden name set.
5. `viz_endpoints.json` records the endpoint inventory; the response-key checks reuse `test_api_schema_contract.py`'s key lists with additive/subset semantics; the drift scan flags net-new/missing resolvable path literals without hard-failing on dynamic paths.
6. `scripts/snapshot_contracts.py --surface all --check` exits `0`; `--update` regenerates deterministically; both share the comparison code with the pytest module.
7. `pytest -q`, `python -m compileall .`, `ruff check .`, and `readme_sync.py --check` all pass. No `.github/workflows/*`, no `ari-core/ari/**`, no `ari-skill-*/src/**`, no frontend, and no runtime config file is modified.

## 14. Rollback Plan

Purely additive and read-only; rollback is trivial and risk-free:

- `git rm -r ari-core/tests/fixtures/contracts/ ari-core/tests/test_contract_snapshots.py scripts/snapshot_contracts.py`, then `python scripts/readme_sync.py --write` to drop the `## Contents` entries and revert `ari-core/tests/README.md` / `scripts/README.md`.
- Because nothing imports the fixtures or the generator at runtime and nothing is wired into a workflow, removal cannot affect the `ari` CLI, the dashboard, MCP skills, checkpoint/config formats, or any test outside `test_contract_snapshots.py`. No data migration, no contract impact.

## 15. Dependencies

Per the provided **DEPENDENCY GRAPH**, there is **no `X -> 034` edge** — 034 has no predecessor and is one of the "independent … config that can start immediately" (`007_subtask_index.md` lines 581–582; index line 81: Depends On **—**, Can Run Independently **Yes**).

- **Hard prerequisites:** none. The inventory subtasks that MUST precede any *runtime* code change (001, 002, 020, 036, 045, 053, 059, 060, 067) do **not** gate 034, because 034 is **not** a runtime code change (§16).
- **Informational input (not a blocker):** `docs/refactoring/010_contract_preservation_policy.md` (the contract catalog), `docs/refactoring/020_inventory_viz_dashboard_api_contracts.md` and subtask **020** (a richer viz endpoint inventory 034's `viz_endpoints.json` can cross-reference) — useful but not required; 034 seeds the viz inventory from the routed findings so it can start before 020 lands.
- **Downstream consumers (depend on this):** subtask **029** (`check_public_api_contracts.py`) can adopt `public_api.json` as its baseline; subtask **030** (`check_viz_api_schema.py`, itself gated by 020) can adopt `viz_endpoints.json`; subtask **042** (prompt snapshots) is a sibling using the same "snapshot + regenerate" idiom; and the later runtime-refactor subtasks that must not break these contracts (§10) use these goldens as their review diff surface.

## 16. Risk Level

**Low. Runtime code change: No.** The subtask adds committed fixture data, one pytest module under `ari-core/tests/`, and one read-only generator under `scripts/`. It imports nothing new into `ari-core`/`ari-skill-*` at runtime, launches no MCP server in the in-process suite, is not referenced by any of the 5 workflows, and cannot alter the `ari` CLI, the dashboard, MCP tools, checkpoint/config formats, or the frontend. The only failure mode is the snapshot being wrong (a false-positive drift or a missed surface), contained by the self-consistency acceptance run (`--check` == `pytest`) and the additive/subset semantics for the volatile viz surface. Matches the index rating (Phase 10, Risk **Low**, Runtime Code Change **No**).

## 17. Notes for Implementer

- **Snapshot the weakest semantics that still catches a breakage.** Name tables (public/CLI/MCP) = exact set (any change is a reviewed golden update); payload keys (viz) = additive/subset (extra optional fields must not fail). Copy the subset idiom verbatim from `test_api_schema_contract.py` rather than inventing a new one.
- **Never launch skill servers in `ari-core/tests`.** `pytest.ini` documents that importing two skills' `src.server` in one process is ambiguous (`sys.modules` caches the first). Capture MCP tools by **AST** for the in-process test; only the opt-in `--with-schema` generator path launches one-skill-per-subprocess (reuse `scripts/run_all_tests.sh`'s isolation).
- **`ari.public.__init__` re-exports nothing at top level** — key the public snapshot on `ari.public.<submodule>`, not `dir(ari.public)`. For the three `import *` submodules, snapshot the *resolved* names so a change in the underlying module's `__all__` is caught.
- **Watch the two MCP idioms.** FastMCP tool name = the decorated function name (`@mcp.tool()`); low-level tool name = the `types.Tool(name="...")` literal. The static scanner must handle both; verify the counts (59 + 27 = 86) after seeding, and treat any cross-skill duplicate name as a `REVIEW_REQUIRED` finding recorded in the fixture, not a code fix.
- **Keep JSON byte-stable.** `json.dumps(..., sort_keys=True, ensure_ascii=False, indent=2) + "\n"`. Do NOT embed timestamps or commit SHAs in the payload (unlike the report-appendix `% snapshot-from` header, which is for prose files) — a volatile field would make every regeneration a spurious diff.
- **Single source of truth for the comparison.** Have `test_contract_snapshots.py` import and call the generator's build/compare functions so `pytest` and `snapshot_contracts.py --check` can never disagree. The failure message must name the exact `--update` command.
- **Do not fork the viz key lists.** Reference (or clearly mirror with a comment) `test_api_schema_contract.py`'s key lists so the two do not drift apart; that test remains the canonical response-shape guard, and `viz_endpoints.json` adds the *inventory* dimension on top.
- **Cite the design docs in the module docstring** (`docs/refactoring/010_contract_preservation_policy.md`, this subtask 034) to match the `scripts/docs/` convention of a docstring pointing at its spec.
- **`sonfigs/` does not exist** — ignore any planning-prompt reference to it; the config surfaces here are `ari-core/ari/config/` (code), `ari-core/ari/configs/` (packaged defaults), and top-level `ari-core/config/` (rubric data), none of which this subtask touches.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **034** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
