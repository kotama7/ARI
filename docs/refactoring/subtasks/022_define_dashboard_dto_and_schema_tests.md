# Subtask 022: Define Dashboard DTO And Schema Tests

- **Subtask ID:** 022
- **Phase:** Phase 4 — Viz / Dashboard Backend
- **Classification:** `KEEP` / `ADAPT` (test + schema-artifact subtask; it *documents and pins* the existing dashboard wire contract, it does not restructure it)
- **Changes runtime code:** **No** (see Section 16)
- **Depends on (dependency graph):** **020** (`inventory_viz_dashboard_api_contracts`)
- **Planning date:** 2026-07-01
- **Repo root:** `/home/t-kotama/workplace/ARI` (git branch `main`, `ari-core` version `0.9.0`)

> **Planning-phase notice.** This document is a plan for a *future* coding session. Authoring it changes no runtime code, imports, prompts, configs, workflows, frontend, or directory names — the only file created by the planning phase is this `.md`. Everything under "Concrete Work Items" and "Files Expected to Change" describes what the **implementer of subtask 022** will do in a later, separate session, and even then only test files and packaged schema *data* are added (no request-handling code path is altered).

---

## 1. Goal

Give the ARI dashboard backend a **machine-readable, versioned definition of its response/request shapes (DTOs) plus an executable test harness** that pins those shapes against the frontend TypeScript source of truth, so the sibling viz refactors (015 service layer, 021 routes extraction, 023 file-I/O split, 024 tree adapter) can move code freely **without silently drifting the wire contract** consumed by `ari-core/ari/viz/frontend/src/services/api.ts` (863 lines).

Concretely this subtask produces two artifact classes and nothing else:

1. **DTO schema definitions** — JSON Schema (draft-07) files under the existing `ari-core/ari/schemas/` package, one per high-traffic dashboard payload (`/state`, `/api/settings`, `/api/checkpoints` item, `/api/checkpoint/<id>/summary`, and the shared `TreeNode`), mirroring the interfaces already declared in `ari-core/ari/viz/frontend/src/types/index.ts` (264 lines: `AppState` 87–129, `Settings` 38–75, `Checkpoint` 24–36, `CheckpointSummary` 237–264, `TreeNode` 3–22).
2. **Schema-conformance tests** — Python tests under `ari-core/tests/` that (a) build the real backend payloads via the existing handler functions and validate them against the new schemas, and (b) cross-check that the schemas stay in sync with the frontend TS types. These extend the already-present `ari-core/tests/test_api_schema_contract.py` (109 lines) rather than replacing it.

This subtask is the **contract-freezing layer** for the whole Phase-4 viz cluster and the **direct input to subtask 030** (`add_viz_api_schema_checker_script` → `scripts/check_viz_api_schema.py`), which will consume these schema files in CI. It is explicitly *not* the service/route refactor (that is 015/021/023/024) and it introduces **no schema-validation into the live request path** (see Section 4).

## 2. Background

**There is no schema or validation layer in the viz backend today.** Every handler parses POST bodies with a raw `json.loads(body)` inline and returns an ad-hoc `dict` serialized by `routes.py:_json(data, status)` (`routes.py:1190-1197`). Two response conventions coexist on the wire and are a real drift hazard:

- `{"ok": bool, ...}` (launch/stage endpoints) vs `{"error": str}` (file APIs); e.g. PaperBench returns `{"error": ...}` and `{"error": ..., "paper_id": ...}` and `{"deleted": bool, "paper_id": ...}` (`api_paperbench.py:275,283,384-385,450,455,478,489`).
- HTTP status codes are **smuggled** through the payload via `r.pop("_status", 200)` (`routes.py:1047-1057`, `1088-1089`) rather than declared.
- The frontend mirrors this split: `get/post` in `services/api.ts` **throw** on non-2xx (`api.ts:18-32`), but `pbGet/pbPost` **never throw** and hand back `{error}` bodies (`api.ts:787-799`). Any backend key rename would break one side silently.

Two safety nets already exist and this subtask **builds on them, it does not reinvent them**:

- `ari-core/tests/test_api_schema_contract.py` (109 lines) already pins the *always-present subset* of keys for `/api/checkpoints` items, `/api/checkpoint/<id>/summary` (found + `{"error": "not found"}` not-found sentinel), and `/api/settings`, and documents the *additive* wire policy (extra keys allowed; error sentinels are exact-equality). It calls the handlers directly (`checkpoint_api._api_checkpoints`, `checkpoint_api._api_checkpoint_summary`, `api_settings._api_get_settings`) with `monkeypatch` fixtures — no HTTP round-trip needed.
- `ari-core/ari/schemas/` already ships JSON Schemas plus a loader: `__init__.py` exposes `load(name) -> dict` and `schema_path(name) -> Path` (draft-07 schemas `node_report.schema.json` 125 lines, `publish.schema.json` 56 lines, plus `README.md`). `ari-core/tests/test_node_report.py` demonstrates the intended **dependency-free** validation idiom: a tiny `_check_required()` / `_validate_minimal()` that reads the schema JSON and asserts required keys + a few enum/int constraints, with the explicit comment *"Avoids pulling jsonschema as a hard test dep"* (`test_node_report.py:27-61`). `jsonschema` is **not** listed in `requirements.txt` / `ari-core/pyproject.toml` (it happens to be importable in this environment, but tests must not depend on it).

So subtask 022 is a natural extension: define the *rest* of the dashboard DTOs as schema files in the same place and validate them with the same no-external-dep idiom, driven off the already-authoritative frontend types.

The "sonfigs" directory referenced in some planning prompts **does not exist**; profile YAML consumed by the `/state` builder is read from the top-level `ari-core/config/` rubric/profile data tree, distinct from `ari-core/ari/config/` (locator code) and `ari-core/ari/configs/` (packaged defaults). This subtask touches none of those.

## 3. Scope

In scope for the subtask implementation (executed **after** the 020 inventory gate):

1. **Author DTO schema files** under `ari-core/ari/schemas/` for the highest-traffic dashboard payloads, each a draft-07 JSON Schema mirroring the corresponding `types/index.ts` interface:
   - `viz_state.schema.json` ← `AppState` (`types/index.ts:87-129`), including the always-present tail keys (`exit_code`, `running`, `pid`, `llm_model`) and the conditional `_ckpt_valid` block keys (`phase_flags`, `best_nodes`, `all_metric_keys`, …) marked optional.
   - `viz_settings.schema.json` ← `Settings` (`types/index.ts:38-75`), covering the always-present keys asserted today in `test_api_schema_contract.py:89-98` (`llm_model`, `llm_provider`, `ollama_host`, `temperature`, `retrieval_backend`, `slurm_partition`, `slurm_walltime`, `container_mode`, `container_pull`, `vlm_review_enabled`, `vlm_review_model`, `letta_base_url`, `letta_embedding_config`, `ors` as an object with `judge_model`).
   - `viz_checkpoint.schema.json` ← `Checkpoint` (`types/index.ts:24-36`): required `id, path, status, node_count, review_score, mtime`; optional `best_metric` (documented always-null init), `best_scientific_score` (conditional).
   - `viz_checkpoint_summary.schema.json` ← `CheckpointSummary` (`types/index.ts:237-264`): `nodes_tree.nodes[]`, plus the `{"error": "not found"}` sentinel path.
   - `viz_tree_node.schema.json` ← `TreeNode` (`types/index.ts:3-22`), referenced (`$ref`) by the state + summary schemas.
   - The **additive-subset** policy must be encoded: schemas set `"additionalProperties": true` (extra keys allowed) and mark only genuinely-always-present keys as `required`, matching the `{**defaults, **saved}` merge behavior asserted by `test_settings_merges_saved_over_defaults` (`test_api_schema_contract.py:101-108`).
2. **Author schema-conformance tests** under `ari-core/tests/`:
   - Extend `test_api_schema_contract.py` (or add `test_viz_dto_schema.py`) so each existing subset assertion is *also* validated against its new schema file using the dependency-free `_check_required`/`_validate_minimal` idiom from `test_node_report.py:34-61`.
   - Add a **TS↔schema sync test** that parses `frontend/src/types/index.ts` (regex/line extraction of interface field names — no TS compiler needed) and asserts every schema `required` key exists as a field in the mirrored interface, so a future rename on either side fails a test.
3. **Update documentation of the schema package**: `ari-core/ari/schemas/README.md` "Contents" list (readme-parity gate) to enumerate the new `viz_*.schema.json` files.
4. **Record the DTO/response-convention map** (which endpoints use `{"ok"}` vs `{"error"}` vs `_status` smuggling) as prose in the test module docstring / schema `description` fields, so subtask 030's checker has a documented baseline.

Out of scope: everything in Section 4.

## 4. Non-Goals

- **NOT** wiring any schema into the live request path. No handler in `routes.py` or `api_*.py` gains a `validate()` call, no POST body is rejected that is accepted today. Introducing request validation would change observable behavior (currently-accepted payloads could start 4xx-ing) and is therefore forbidden here. Schemas are consumed **only** by tests (and later by 030's static checker).
- **NOT** unifying the `{"ok"}` vs `{"error"}` conventions or removing the `_status` smuggling — that is 015's response-wrapper work. 022 *documents* both conventions; it does not change them.
- **NOT** adding a `jsonschema` dependency. Validation uses the existing dependency-free idiom (`test_node_report.py:34-61`). Do not edit `requirements.txt`, `requirements.lock`, or `ari-core/pyproject.toml`.
- **NOT** extracting/refactoring the `/state` builder (`routes.py:219-666`, 021), the file-I/O handlers (023), the BFTS tree adapter (024), or the PaperBench `_JOBS` store (`api_paperbench.py:496-497`). See the discrepancy note in Section 17 regarding the `_JOBS` redesign.
- **NOT** changing any endpoint path, HTTP method, JSON key, status code, header, or the WebSocket `{"type":"update","data":...,"timestamp":...}` message.
- **NOT** touching `frontend/` TypeScript (the TS types are read as *input* only), `docs/`, `.github/workflows/`, configs, or directory names.
- **NOT** authoring `scripts/check_viz_api_schema.py` — that net-new checker is subtask **030**; 022 only produces the schema *files* it will consume.
- **NOT** assigning `KEEP/ADAPT/DELETE_CANDIDATE` verdicts to viz modules (that is 015/020).

## 5. Current Files / Directories to Inspect

All paths relative to `/home/t-kotama/workplace/ARI`. **Read-only inputs** to this subtask.

Existing schema package (the home for the new DTO files):

| File | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/schemas/__init__.py` | 21 | `load(name)` + `schema_path(name)` loader (generic; **needs no change**). |
| `ari-core/ari/schemas/node_report.schema.json` | 125 | Draft-07 schema; the *style* template for the new DTO schemas. |
| `ari-core/ari/schemas/publish.schema.json` | 56 | Draft-07 schema; second style template. |
| `ari-core/ari/schemas/README.md` | 17 | Contents list — **must be updated** for new files (readme-parity gate). |

Frontend contract source of truth (read-only input, mirror target):

| File | LOC | Relevant interfaces |
| --- | --- | --- |
| `ari-core/ari/viz/frontend/src/types/index.ts` | 264 | `TreeNode` (3-22), `Checkpoint` (24-36), `Settings` (38-75), `CostSummary` (79-85), `AppState` (87-129), `CheckpointSummary` (237-264), `ReviewReport` (204-229), `ResourceMetrics` (174-183), `WorkflowData`/`WorkflowStage` (138-172). |
| `ari-core/ari/viz/frontend/src/services/api.ts` | 863 | Two error regimes: `get/post` throw (18-32); `pbGet/pbPost` never throw (787-799). Authoritative list of paths/methods. |

Backend handlers whose return values the schemas describe (read-only; called by the tests):

| File | LOC | Payload |
| --- | --- | --- |
| `ari-core/ari/viz/checkpoint_api.py` | 327 | `_api_checkpoints()` (item ← `Checkpoint`), `_api_checkpoint_summary(id)` (← `CheckpointSummary`, `{"error":"not found"}` sentinel). |
| `ari-core/ari/viz/api_settings.py` | 553 | `_api_get_settings()` (← `Settings`, `{**defaults, **saved}` merge at `:119`). |
| `ari-core/ari/viz/routes.py` | 1197 | inline `/state` builder (`219-666`, ← `AppState`); `_json` serializer (`1190-1197`); `_status` smuggling (`1047-1057`, `1088-1089`). |
| `ari-core/ari/viz/api_paperbench.py` | 813 | `{"error"}`/`{"deleted"}` PaperBench shapes (`275,283,384-385,450-489`). |
| `ari-core/ari/viz/state.py` | 79 | mutable globals monkeypatched by the tests (`_checkpoint_dir`, `_last_proc`, `_running_procs`, `_settings_path`). |

Existing tests to extend / reuse the idioms from:

| File | LOC | Reuse |
| --- | --- | --- |
| `ari-core/tests/test_api_schema_contract.py` | 109 | The subset-assertion tests to augment with schema validation; the `isolated_state` monkeypatch fixture (`:25-31`). |
| `ari-core/tests/test_node_report.py` | — | `_load_schema`/`_check_required`/`_validate_minimal` dependency-free validator (`:29-61`) — copy this pattern. |
| `ari-core/tests/test_viz_node_report_api.py` | — | Handler-direct-call test style (no HTTP). |

Upstream planning references: `docs/refactoring/subtasks/020_*` (inventory — **not yet authored**, see Section 15), `docs/refactoring/subtasks/015_refactor_dashboard_viz_api_services.md`, `docs/refactoring/008_viz_dashboard_refactoring_plan.md`, `docs/refactoring/010_contract_preservation_policy.md`, `docs/reference/rest_api.md` (10.8 KB), `docs/reference/file_formats.md` (13.7 KB).

## 6. Current Problems

Grounded in the verified viz findings and re-checked line references:

1. **No formal DTO contract exists.** The dashboard's request/response shapes live only implicitly in scattered handler `dict` literals and in the frontend TS types. There is no single machine-readable definition, so a refactor that renames a JSON key (015/021/023's risk) cannot be caught statically.
2. **Two response conventions + status smuggling are undocumented.** `{"ok"}` vs `{"error"}` and `r.pop("_status", 200)` (`routes.py:1047-1057`) are load-bearing wire behavior with no captured spec. The frontend's asymmetric error handling (`get/post` throw vs `pbGet/pbPost` swallow, `api.ts:18-32` vs `787-799`) means a silent key drift breaks one path only.
3. **Contract-test coverage is partial.** `test_api_schema_contract.py` pins only three payloads (`checkpoints`, `checkpoint summary`, `settings`) and only as *key-subset* assertions. The highest-value and largest payload — `/state` (`AppState`, built by the ~450-line `routes.py:219-666`) — has **no** dedicated schema-contract test, and `TreeNode` (embedded in both `/state` and summaries) is unpinned.
4. **Schema/TS drift is unguarded.** `ari-core/ari/viz/frontend/src/types/index.ts` is hand-maintained and already carries "corrected from prior type" annotations (e.g. `cost` at `:106-109`, `AppState` tail keys at `:115-128`), showing the shapes *do* drift over time. Nothing tests that the backend and the TS types agree.
5. **The 030 checker has no schema to consume.** `scripts/check_viz_api_schema.py` (subtask 030, net-new) is meant to statically verify `routes.py`+`api_*.py` against `services/api.ts`. Without committed schema files it would have to reinvent the DTO definitions inline. 022 supplies exactly those files.

## 7. Proposed Design / Policy

**Policy: define DTOs as draft-07 JSON Schema *data* in `ari-core/ari/schemas/`, validated by dependency-free tests, with zero wiring into the request path.** Classification: this is a `KEEP`/`ADAPT` documentation-and-test subtask — additive artifacts only, no external contract changed.

### 7.1 Schema file conventions

- One `viz_*.schema.json` per payload, draft-07, styled after `node_report.schema.json` (`$schema`, `$id`, `title`, `description`, `type`, `required`, `properties`).
- Encode the **additive wire policy** explicitly: `"additionalProperties": true` on object schemas so extra/optional keys never fail (matches `test_api_schema_contract.py`'s subset philosophy and the `{**defaults, **saved}` merge). Only mark a key `required` if the handler emits it *unconditionally*; conditional keys (e.g. `AppState.phase_flags`, `Checkpoint.best_scientific_score`) go in `properties` but not `required`.
- Represent nullable fields as `{"type": ["<t>", "null"]}` (as `node_report.schema.json` already does, e.g. `parent_id`). Reuse `viz_tree_node.schema.json` via `$ref` inside `viz_state.schema.json` and `viz_checkpoint_summary.schema.json` to avoid duplicating the `TreeNode` definition.
- Preserve exact error sentinels as documented constants in the schema `description` (e.g. checkpoint-summary not-found is exactly `{"error": "not found"}`, per `test_api_schema_contract.py:78`) — the sentinel is validated by the test, not by the additive schema.

### 7.2 Validation tests (dependency-free)

- Copy the `_load_schema`/`_check_required`/`_validate_minimal` idiom from `test_node_report.py:29-61`. Do **not** `import jsonschema`; if a fuller validator is ever wanted, gate it behind `pytest.importorskip("jsonschema")` so the suite passes without the package.
- Each test builds the **real** payload by calling the handler directly (as the current contract tests do — `checkpoint_api._api_checkpoints()`, `api_settings._api_get_settings()`, and for `/state` the builder invoked via the same monkeypatched `state.py` fixture), then runs `_check_required(payload, schema)` plus the endpoint-specific enum/type asserts already present.
- Keep the existing `isolated_state` fixture (`test_api_schema_contract.py:25-31`) and its `monkeypatch.setattr(_st, "_checkpoint_dir", …)` calls — do not rename `state.py` globals (that is a hard constraint for 015 too).

### 7.3 TS↔schema sync test

- Add one test that reads `frontend/src/types/index.ts` as text, extracts the field-name set of each mirrored interface with a small regex (field lines match `^\s*([a-zA-Z_][\w]*)\??:`), and asserts every schema `required` key is present in the corresponding interface. This is a **name-level** guard (not a full type check) and needs no Node/TS toolchain, so it runs inside `pytest`.
- The test's failure message must name both the schema file and `types/index.ts` so a drift is actionable from either side.

### 7.4 Where the DTOs live (and why "No runtime change" holds)

- Schemas live under `ari-core/ari/schemas/` as **packaged JSON data**, loaded by the already-generic `ari.schemas.load()` (no `__init__.py` edit needed). Nothing in `routes.py`/`api_*.py`/`server.py` imports them, so no executing request path changes — this is why the subtask is classified **No runtime code change** (consistent with `007_subtask_index.md:37-40,69`, which counts "tests / CI config / data" as non-runtime).
- Do **not** introduce a new importable Python DTO module under `ari-core/ari/viz/` (e.g. a `dto.py`) in this subtask: even if inert, it enlarges the runtime package surface and invites accidental wiring. If a later subtask (015) wants typed request DTOs in the handler path, it owns that runtime change. 022 keeps DTOs as declarative data + tests.

## 8. Concrete Work Items

Execute only after the 020 inventory exists (Section 15). Suggested order:

1. **Ingest the 020 inventory** of endpoints (method, path, params, response keys, status codes, headers, `{"ok"}`/`{"error"}`/`_status` conventions). Use it as the authoritative list of shapes to schematize; reconcile it against `types/index.ts` and `services/api.ts`.
2. **Author `viz_tree_node.schema.json`** first (it is `$ref`-ed by others), mirroring `TreeNode` (`types/index.ts:3-22`).
3. **Author `viz_state.schema.json`, `viz_settings.schema.json`, `viz_checkpoint.schema.json`, `viz_checkpoint_summary.schema.json`**, each mirroring its interface and marking only unconditional keys `required` (cross-check against the keys already asserted in `test_api_schema_contract.py:53,89-98`).
4. **Add the validation tests**: extend `test_api_schema_contract.py` (or add `ari-core/tests/test_viz_dto_schema.py`) so every existing subset assertion also runs `_check_required(payload, load("viz_*"))`; add a dedicated `/state` schema test (the currently-untested largest payload), building the payload via the same `state.py` monkeypatch fixture.
5. **Add the TS↔schema sync test** (Section 7.3).
6. **Update `ari-core/ari/schemas/README.md`** "Contents" to list every new `viz_*.schema.json` (readme-parity gate).
7. **Run the full gate set** (Section 12) and confirm `pytest -q` passes with strictly more passing tests and no regression in the existing three contract tests.

## 9. Files Expected to Change

When this subtask is executed (post-020). **All additions are test files or packaged schema data — no request-handling code changes.**

New schema data (packaged, loaded only by tests):
- `ari-core/ari/schemas/viz_tree_node.schema.json` — **new**, mirrors `TreeNode`.
- `ari-core/ari/schemas/viz_state.schema.json` — **new**, mirrors `AppState`.
- `ari-core/ari/schemas/viz_settings.schema.json` — **new**, mirrors `Settings`.
- `ari-core/ari/schemas/viz_checkpoint.schema.json` — **new**, mirrors `Checkpoint`.
- `ari-core/ari/schemas/viz_checkpoint_summary.schema.json` — **new**, mirrors `CheckpointSummary`.

New / edited tests:
- `ari-core/tests/test_viz_dto_schema.py` — **new** (or, equivalently, edits appended to `ari-core/tests/test_api_schema_contract.py`): handler-driven schema-conformance tests + the TS↔schema sync test.

Docs (repo-hygiene, gated):
- `ari-core/ari/schemas/README.md` — **edit**: add the five `viz_*.schema.json` entries to the "Contents" list.

Explicitly **not** changed by this subtask (delegated / read-only): `ari-core/ari/schemas/__init__.py` (loader already generic), any `ari-core/ari/viz/*.py` handler, `routes.py`/`server.py`, all `frontend/` TS (read as input only), `docs/`, `.github/workflows/`, `requirements*.txt`, `ari-core/pyproject.toml`.

This planning document: `docs/refactoring/subtasks/022_define_dashboard_dto_and_schema_tests.md` (the only file created by the planning phase).

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WebSocket contract** — every path/method/JSON-key/status-code/header consumed by `ari-core/ari/viz/frontend/src/services/api.ts` (863) and described in `docs/reference/rest_api.md`. 022 must **describe** these shapes, never alter them. The WS `{"type":"update","data":<tree>,"timestamp":...}` message is out of scope but its `data` tree reuses `TreeNode`, so the `viz_tree_node.schema.json` must not contradict it.
- **Existing schema loader** `ari.schemas.load` / `schema_path` — behavior unchanged; new files must load cleanly (`json.loads` valid, draft-07).
- **Existing contract tests** `ari-core/tests/test_api_schema_contract.py`, `test_node_report.py` — must keep passing; the new asserts are additive.
- **`state.py` global attribute names** (`_checkpoint_dir`, `_last_proc`, `_running_procs`, `_settings_path`) — the fixtures monkeypatch these; do not rename.
- **`ari.public.*`**, **CLI `ari`**, **the 14 `ari-skill-*` MCP contracts**, **checkpoint/output/config file formats** — untouched (this subtask reads none of them at runtime).
- **Scripts invoked by `.github/workflows/`** — unaffected; the new schema files become an *input* to the future `scripts/check_viz_api_schema.py` (030), which this subtask does not author.

## 11. Compatibility Constraints

- **Additive-subset schemas only.** Set `"additionalProperties": true` and mark only unconditionally-emitted keys `required`, matching the `{**defaults, **saved}` merge (`api_settings._api_get_settings`, `test_api_schema_contract.py:101-108`). A schema that is too strict would make the tests reject *currently-valid* payloads — a false contract break.
- **Exact error sentinels preserved.** `{"error": "not found"}` (checkpoint summary) is exact-equality per `test_api_schema_contract.py:78`; encode it as a test constant, not as an additive schema property.
- **No new runtime dependency.** Validation stays dependency-free (`test_node_report.py:34-61`); any optional `jsonschema` use is guarded by `pytest.importorskip`.
- **No term "deprecated".** The `{"ok"}`/`{"error"}`/`_status` conventions are *documented as current behavior*, not deprecated — "deprecated" is reserved for external contracts, and these conventions remain the live contract.
- **Schemas mirror, never lead.** Where a schema and `types/index.ts` disagree, the fix is to correct the schema to match the *current backend output*, not to "improve" the shape. Changing the shape is a 015/021/023 runtime decision, not 022's.

## 12. Tests to Run

From repo root `/home/t-kotama/workplace/ARI` (editable installs already set up by `setup.sh`: `ari-skill-memory` then `ari-core`):

```bash
python -m compileall .                 # syntax gate (fast; schemas are data, tests compile)
ruff check .                           # lint (ruff IS available; radon is NOT)
pytest -q                              # full suite
```

Targeted loop (run first):

```bash
pytest -q ari-core/tests/test_api_schema_contract.py \
          ari-core/tests/test_viz_dto_schema.py \
          ari-core/tests/test_node_report.py \
          ari-core/tests/test_viz_node_report_api.py
```

Schema-data sanity (every new file must be valid JSON and loadable):

```bash
python -c "from ari import schemas; \
  [schemas.load(n) for n in ('viz_tree_node','viz_state','viz_settings','viz_checkpoint','viz_checkpoint_summary')]; \
  print('viz schemas load OK')"
```

Docs gate (schema README parity — the schemas dir is a per-directory README):

```bash
python scripts/docs/check_readme_parity.py   # and scripts/readme_sync.py if present
```

No frontend build is required: `frontend/src/types/index.ts` is read as text input, not modified, so `npm test` / `npm run build` are **not** part of the 022 gate. CI guard `.github/workflows/refactor-guards.yml` must stay green (no new `~/.ari/` references).

## 13. Acceptance Criteria

1. `python -m compileall .` and `ruff check .` pass with no new violations.
2. `pytest -q` passes with strictly more passing tests than before; the three existing contract tests in `test_api_schema_contract.py` still pass unchanged.
3. Five new `ari-core/ari/schemas/viz_*.schema.json` files exist, are valid draft-07 JSON, load via `ari.schemas.load`, and mirror `TreeNode`/`AppState`/`Settings`/`Checkpoint`/`CheckpointSummary` from `types/index.ts`.
4. Each mirrored payload has a schema-conformance test that builds the real handler output and validates it (dependency-free); the `/state` payload — previously untested for schema — now has coverage.
5. A TS↔schema sync test fails if a `required` schema key is renamed/removed on either the schema side or in `types/index.ts`.
6. No handler, `routes.py`, `server.py`, `__init__.py`, frontend TS, workflow, config, or dependency manifest is modified (verified by `git diff --stat` touching only `ari-core/ari/schemas/viz_*.schema.json`, `ari-core/ari/schemas/README.md`, `ari-core/tests/test_viz_dto_schema.py` and/or `test_api_schema_contract.py`).
7. `ari-core/ari/schemas/README.md` lists all new schema files (readme-parity gate green).
8. No `jsonschema` (or any other) dependency added to `requirements*.txt` / `ari-core/pyproject.toml`.

## 14. Rollback Plan

- The subtask adds only test files and packaged schema JSON; rollback is a `git revert` of the subtask's commit(s) with **zero** runtime impact — no executing code path imports the new schemas, so reverting cannot regress dashboard behavior.
- If a new schema is discovered to be too strict and fails against a legitimate payload variant, the minimal fix is to relax that schema (drop the over-strict `required` entry / keep `additionalProperties: true`) rather than revert the whole subtask; each schema is independent.
- No data/format migration is involved (schemas are read-only descriptions), so there is nothing to migrate back.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (`020 -> 021, 022, 023, 024, 030`; so **022 depends on 020**).

- **Hard predecessor (gate): 020** `inventory_viz_dashboard_api_contracts` (`007_subtask_index.md:69`, "Depends On = 020"). 020 enumerates the ~130 endpoints, their method/path/params, the always-present vs conditional response keys, and the `{"ok"}`/`{"error"}`/`_status` conventions. 022 needs that authoritative inventory to know *which* shapes to schematize and which keys are truly unconditional. **020 is not yet authored** (`docs/refactoring/subtasks/020_*` does not exist as of 2026-07-01); do not start 022 until it is (see Section 17).
- **Cross-cutting inventory gate.** The program rule "inventory subtasks MUST precede any runtime code change" lists **001, 002, 020, 036, 045, 053, 059, 060, 067**. 022 relies directly on **020**; it is otherwise a non-runtime (test/schema) subtask so it is not itself blocked by the others.
- **Consumer — 030** `add_viz_api_schema_checker_script` (`scripts/check_viz_api_schema.py`, also gated by 020): 030 **consumes** the schema files 022 produces. Author 022 before or alongside 030 so the checker has committed schemas to validate against (`007_subtask_index.md:252-253`).
- **Coordinates with (siblings, all gated by 020): 015** (service layer / response wrapper — the party most likely to change response bytes; 022's schemas are the guardrail that keeps 015 honest), **021** (`/state` extraction — `viz_state.schema.json` pins its output), **023** (file-I/O split), **024** (tree-viz adapter — shares `viz_tree_node.schema.json`). These form "Wave 6 — Dashboard backend + viz" (`007_subtask_index.md:535`). 022 has **no runtime dependency** on them and should ideally land *first* among the cluster so the others inherit a frozen contract to test against.
- Upstream policy inputs: **010** (contract preservation), **008** (viz dashboard refactoring plan), **006** (target architecture).

## 16. Risk Level

- **Does this subtask change runtime code? NO.** It adds (a) packaged JSON Schema *data* under `ari-core/ari/schemas/` loaded only by tests, (b) test modules under `ari-core/tests/`, and (c) a README edit. No request-handling code path, import graph, or dependency manifest changes. (The planning document itself changes no runtime code either.) This matches the `007_subtask_index.md:69` classification (`022 … Runtime Code Change? = No`).
- **Risk: LOW** (consistent with `007_subtask_index.md:69`). Rationale: additive, revert-clean, no wiring into live paths, dependency-free validation. The only realistic failure modes are (a) an over-strict schema that rejects a valid payload — caught immediately by `pytest` and fixed by relaxing that one schema; and (b) a mis-mirrored key vs `types/index.ts` — caught by the TS↔schema sync test. Neither can affect the running dashboard.

## 17. Notes for Implementer

- **Do not start before 020 exists.** 022 must schematize the *inventoried* shapes, not shapes reverse-engineered ad hoc from `routes.py`. If `docs/refactoring/subtasks/020_*` is absent, stop and escalate.
- **Reuse, don't reinvent, the validator.** Copy `_load_schema`/`_check_required`/`_validate_minimal` from `test_node_report.py:29-61`. Do **not** `import jsonschema` unconditionally — it is not in `requirements.txt`; guard any optional use with `pytest.importorskip("jsonschema")`.
- **Schemas mirror the backend's *current* output.** Build the real payload via the handler + the `state.py` monkeypatch fixture (`test_api_schema_contract.py:25-31`) and mark `required` only what is actually always emitted. When in doubt, prefer optional (`additionalProperties: true` + not-`required`) — a false-negative schema is safe; a false-positive one breaks the suite.
- **Preserve `state.py` attribute names.** The fixtures `monkeypatch.setattr(_st, "_checkpoint_dir"/"_last_proc"/"_running_procs"/"_settings_path", …)`. Do not touch `state.py`.
- **`_JOBS` discrepancy — REVIEW_REQUIRED.** Subtask 015's planning doc (`015_refactor_dashboard_viz_api_services.md`, Sections 3/8/9/17) hands the PaperBench `_JOBS` store redesign (`api_paperbench.py:496-497`) to "022". That is inconsistent with this subtask's index classification (`007_subtask_index.md:69`: 022 = **No** runtime change, **Low** risk) — redesigning an in-memory job store is a runtime change. Resolution for this plan: **022 does NOT redesign `_JOBS`.** 022 only *documents* the PaperBench `{"error"}`/`{"deleted"}` response shapes as schema/test artifacts; the actual `_JOBS` persistence redesign is a runtime change that belongs to a viz-runtime subtask (021, or a dedicated follow-up), and this cross-reference should be reconciled when 015/021 are finalized. Flag it, do not implement it here.
- **The "sonfigs" directory does not exist.** Profile YAML read by the `/state` builder comes from top-level `ari-core/config/`, not a `sonfigs/` path. Do not create or reference one.
- **radon is not installed; ruff is.** Use `ruff check .`; do not add radon. `node`/`npm` exist (no `pnpm`) but the frontend is untouched — no npm step in the 022 gate.
- **Keep the schema package README accurate.** A readme-parity gate (`scripts/docs/check_readme_parity.py`) and doc-source checks run in CI; every new `viz_*.schema.json` must be listed in `ari-core/ari/schemas/README.md`.
- **These schemas are 030's input, not 022's output-to-CI.** Do not wire the schemas into any workflow YAML — that coupling is subtask 030's job.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **022** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
