# Subtask 014: Refactor Registry And Factory Layer

> Phase 3: Core Architecture · Risk: High · Direct predecessor: 007
> Changes runtime code: **Yes** (see Section 16)

---

## 1. Goal

Unify the three ad-hoc, string-keyed dispatchers that live scattered across
`ari-core/ari/` into a single, small, deterministic factory layer that sits
**behind the existing `ari/protocols/` contracts**, without breaking any
external string-key contract and without colliding with the existing
`ari/registry/` HTTP artifact-registry module.

Concretely, the three dispatchers to bring under one roof are:

1. **Publish backends** — `ari/publish/__init__.py:198` `_load_backend(name)`
   (if/elif over `"ari-registry" | "local-tarball" | "zenodo" | "gh"` with lazy
   module import).
2. **Evaluator composites** — `ari/evaluator/llm_evaluator.py:165` `_COMPOSITES`
   (a `dict[str, callable]` — already the closest thing to a real registry-dict).
3. **LLM provider routing** — `ari/llm/routing.py:37` `resolve_litellm_model`
   (if/elif over `"anthropic" | "claude" | "ollama" | "cli-shim"`).

The deliverable is a `KEEP`-biased consolidation: a `BaseRegistry` /
factory helper that these three call-sites can adopt one at a time, with a
compatibility adapter for every public/string contract they currently expose.
The factory is **import-driven** (in-tree registration), *not*
`importlib.metadata` entry-points — no entry-point plugin system exists in this
repo (`ari-core/pyproject.toml` declares only `ari = "ari.cli:app"`).

## 2. Background

ARI has no central component/DI registry. Extensibility is expressed as in-tree
string keys resolved by hand-written `if/elif` chains or a single dict. Subtask
007 (`define_core_interfaces_and_protocols`) grounds the Protocol package this
subtask builds on; `ari/protocols/__init__.py:19-23` already exposes
`Evaluator`, `PromptLoader`, and `ConfigLoader`, and its docstring names the
roadmap (`LLMClient, MCPClient, MemoryClient, NodeStore, StageRunner` "land in
subsequent phases"). Subtask 053 (`inventory_reference_roots`) explicitly records
the dynamic reference roots this subtask touches (see 007_subtask_index.md:164-169).

**Critical naming trap (verified):** `ari-core/ari/registry/` is **NOT** a
component/DI registry. It is an **HTTP artifact registry** — a FastAPI server
for curated EAR bundles: `app.py:22` `build_app(data_dir)` returns a `FastAPI`
app titled `"ari-registry"` with endpoints `/artifact`, `/artifact/{id}`,
`/artifact/{id}/promote`, `/artifact/{id}/manifest.lock`, `/healthz`, `/version`
(`app.py:46-140`); `storage.py:28` `FilesystemStorage` (content-addressed
sha256[:16] ids); `auth.py:33` `TokenStore` (sqlite bearer tokens);
`cli.py:13` `registry_app` typer group with `serve`/`token`/`gc`. It is wired
into the main CLI at `ari/cli/__init__.py:97-98`
(`app.add_typer(_registry_app, name="registry")`), so `ari registry` is a
**live CLI contract**. Any new factory abstraction **must not** be named
`ari.registry` or reuse the `registry` name in a way that shadows this module.

## 3. Scope

In scope (design + refactor plan for the future implementation session):

- The three string→impl dispatchers listed in Section 1.
- A single `BaseRegistry` / factory helper (target module name TBD in
  Section 7, but explicitly **not** `ari.registry`).
- Adapter shims that keep every current string key and public symbol working.
- Reconciliation of the `MemoryClient` Protocol-vs-ABC inconsistency **only as a
  documented follow-up handoff to Subtask 013** (this subtask does not own the
  memory boundary; see Non-Goals).

Out of scope (owned by other subtasks — do not touch here):

- `ari/registry/` HTTP artifact-registry behaviour or its CLI (owned by no
  refactor in this batch; it is `KEEP` verbatim).
- Memory backend selection / the core→skill memory edge — Subtask 013.
- Evaluator interface extraction — Subtask 009.
- Model backend interface extraction — Subtask 008.
- Config consolidation — Subtask 003.

## 4. Non-Goals

- **Not** introducing an `importlib.metadata` entry-point plugin system. All
  extensibility stays in-tree string keys (verified: `pyproject.toml` declares
  only the `ari = "ari.cli:app"` console script; no `[project.entry-points]`
  plugin groups exist).
- **Not** renaming, moving, or altering `ari/registry/` (the HTTP artifact
  registry). It is a name-collision hazard only, not a refactor target.
- **Not** changing the `publish.schema.json` backend-name enum, the
  `EvaluatorConfig.composite` `Literal`, or the `resolve_litellm_model` return
  contract. These are frozen; the factory adapts to them, not vice-versa.
- **Not** wiring memory-client selection to `ARI_MEMORY_BACKEND` (see Section 6
  finding); that is a design note handed to Subtask 013, not an action here.
- **Not** adding `s3` publish support (see Section 6 discrepancy).
- **Not** modifying prompts, workflows, frontend, or directory names.

## 5. Current Files / Directories to Inspect

Registry-name collision (KEEP verbatim — inspect for disambiguation only):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/registry/__init__.py` | 49 | `resolve_data_dir`, package doc |
| `ari-core/ari/registry/app.py` | 150 | FastAPI `build_app` (HTTP artifact registry) |
| `ari-core/ari/registry/storage.py` | 145 | `FilesystemStorage` (sha256 content-addressed) |
| `ari-core/ari/registry/auth.py` | 93 | `TokenStore` (sqlite bearer tokens) |
| `ari-core/ari/registry/cli.py` | 74 | `registry_app` typer group (`ari registry`) |
| `ari-core/ari/cli/__init__.py:97-98` | — | wires `ari registry` subcommand |

Dispatcher #1 — publish backends (the primary `if/elif → registry` target):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/publish/__init__.py` | 219 | `_load_backend(name)` at `:198`; `publish()`/`promote()` |
| `ari-core/ari/publish/backends/__init__.py` | ~5 | package doc (each module exposes `publish`/`promote`) |
| `ari-core/ari/publish/backends/ari_registry.py` | ~213 | FastAPI-client backend |
| `ari-core/ari/publish/backends/local_tarball.py` | ~48 | zero-dep backend |
| `ari-core/ari/publish/backends/zenodo.py` | ~139 | zenodo backend |
| `ari-core/ari/publish/backends/gh.py` | ~134 | GitHub Releases backend |
| `ari-core/ari/schemas/publish.schema.json:51` | — | backend-name enum (external contract) |
| `ari-core/ari/cli_ear.py:138,159` | — | caller of `publish`/`promote` |
| `ari-core/ari/viz/api_publish.py:138,166` | — | dashboard caller of `publish`/`promote` |

Dispatcher #2 — evaluator composites (the existing registry-dict pattern):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/evaluator/llm_evaluator.py:165` | (file 30,914 bytes) | `_COMPOSITES` dict; validated at `:280-286` |
| `ari-core/ari/config/__init__.py:212-217` | — | `EvaluatorConfig.composite` `Literal` (keys must stay in sync) |

Dispatcher #3 — LLM provider routing:

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/llm/routing.py` | 62 | `resolve_litellm_model` (`:37`) + `_KNOWN_PREFIXES` |
| `ari-core/ari/llm/__init__.py:17,19` | — | re-exports `resolve_litellm_model` |
| `ari-core/ari/cost_tracker.py:270-276` | — | caller |
| `ari-core/ari/llm/client.py:68-69` | — | caller |

Contracts / Protocol seams to build behind:

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/protocols/__init__.py` | 23 | exposes `Evaluator`, `PromptLoader`, `ConfigLoader`; roadmap docstring |
| `ari-core/ari/protocols/evaluator.py` | 40 | `@runtime_checkable Evaluator` Protocol |
| `ari-core/ari/configs/_loader.py` | 59 | `ConfigLoader` Protocol + `FilesystemConfigLoader` (swap-impl model) |
| `ari-core/ari/schemas/__init__.py` | 20 | `load(name)` / `schema_path(name)` — no production importer (unused surface) |
| `ari-core/ari/memory/client.py:8` | 23 | `MemoryClient` **ABC** (doc calls it a "Protocol" — inconsistency) |
| `ari-core/ari/core.py:130` | — | hardcodes `LettaMemoryClient(...)` (no factory dispatch) |

## 6. Current Problems

1. **Three divergent dispatch styles for the same "string → impl" concept.**
   `_load_backend` is an `if/elif` with lazy imports (`publish/__init__.py:198-215`);
   `_COMPOSITES` is a plain module-level dict (`llm_evaluator.py:165-170`);
   `resolve_litellm_model` is an `if/elif` over prefixes (`routing.py:50-62`).
   Each re-implements "unknown key → raise", key validation, and the valid-keys
   list independently.

2. **Duplicated source-of-truth for valid keys.** Publish backend names live in
   both `_load_backend` (4 branches) and `publish.schema.json:51` (an enum of
   **5**). The composite keys live in both `_COMPOSITES` (4 keys) and
   `EvaluatorConfig.composite` `Literal` (4 keys, `config/__init__.py:212-217`).
   There is no mechanism keeping these in sync.

3. **Schema/loader drift (verified discrepancy).** `publish.schema.json:51`
   enumerates `["ari-registry", "gh", "zenodo", "s3", "local-tarball"]` — **five**
   names — but `_load_backend` only handles **four**; there is **no `s3` backend
   module** (`ls ari/publish/backends/` confirms none). Passing `backend="s3"`
   validates against the schema yet raises `PublishError("unknown backend: s3")`
   at runtime. A factory with a single key list would surface this gap explicitly
   instead of hiding it.

4. **Dead-code hazard for static analysis.** The four publish backend modules are
   referenced **only by string** through the lazy imports in `_load_backend`; they
   will not appear as statically imported and must be treated as **live**
   (recorded by Subtask 053, 007_subtask_index.md:167-168). Likewise
   `ari.schemas.load()` has **no production importer** — a repo-wide grep finds
   only `tests/` reading the schema files by direct filesystem path — so the
   loader API is effectively unused surface.

5. **Protocol-vs-ABC convention is not unified.** `MemoryClient` is an **ABC**
   (`memory/client.py:8`, `@abstractmethod add/search/get_all`) while
   `memory/__init__.py` documents it as a "Protocol"; meanwhile `Evaluator`
   (`protocols/evaluator.py:19`) and `ConfigLoader` (`configs/_loader.py:21`) are
   `Protocol`s. Any factory that produces `MemoryClient`s inherits this
   inconsistency (handoff to Subtask 013).

6. **Memory is not factory-dispatched at all.** `core.py:130` hardcodes
   `LettaMemoryClient(...)`; `ARI_MEMORY_BACKEND` is *set*
   (`config/__init__.py:316`) but no core dispatch *consumes* it. This is a
   latent factory site with no current dispatcher — note it, do not wire it here.

7. **Name collision with `ari/registry/`.** A naive `ari.registry.BaseRegistry`
   would shadow the HTTP artifact-registry package and its `ari registry` CLI.

## 7. Proposed Design / Policy

**Classification:** `ADAPT` (unify dispatch behind Protocol contracts with
compatibility adapters). The individual dispatchers are `KEEP` at the contract
level; only their internals converge.

### 7.1 A small `BaseRegistry` helper (import-driven)

Introduce one minimal helper — a typed, string-keyed registry class — placed to
**avoid the `ari.registry` name**. Recommended location:
`ari-core/ari/factory/` (new package) exposing `BaseRegistry`, or a single
module `ari-core/ari/_factory.py`. Final name is `REVIEW_REQUIRED` but MUST NOT
be `ari.registry`, `ari.registries`, or anything that shadows the HTTP module.

Shape (illustrative, not prescriptive):

- `BaseRegistry[T]` holds a `dict[str, Callable[..., T] | ModuleType]`.
- `register(key)` decorator / `register(key, factory)` method for in-tree
  registration.
- `resolve(key) -> T` (or the raw factory) with a single, uniform
  "unknown key → `KeyError`/domain error listing valid keys" path.
- `keys()` returning the canonical valid-key list — the **single source of
  truth** that schema/`Literal` sync checks can read.
- Support **lazy** resolution (for publish backends, which must stay lazily
  imported so optional deps like `zenodo` do not import at module load).

### 7.2 Adoption order (lowest-risk first)

1. **`_COMPOSITES` (Dispatcher #2)** — already a dict; convert to a
   `BaseRegistry` instance registering the same four callables under the same
   four keys. Keep `_COMPOSITES` as a module-level alias so
   `llm_evaluator.py:280-286` and any test referencing it keep working. Add a
   test/assert that `registry.keys() == set(EvaluatorConfig.composite.__args__)`
   so the `Literal` and the registry can never silently drift.
2. **`_load_backend` (Dispatcher #1)** — replace the `if/elif` body with a
   registry of **lazy** loaders (each entry imports its backend module on
   `resolve`, preserving the `try/except ImportError → PublishError` behaviour
   for `zenodo`/`gh`). Keep the module-level function `_load_backend(name)` as a
   thin wrapper delegating to `registry.resolve(name)` so `publish()`/`promote()`
   and both callers (`cli_ear.py`, `viz/api_publish.py`) are untouched. Add a
   sync check `registry.keys() ⊆ publish.schema.json enum`; explicitly document
   the `s3` gap (schema-only, no backend) rather than silently papering over it.
3. **`resolve_litellm_model` (Dispatcher #3)** — this one is the loosest fit: it
   is prefix *transformation*, not object *construction*, and it is public-adjacent
   (`llm/__init__.py:19`). Prefer **KEEP as-is** and only optionally back its
   `backend → prefix` mapping with a registry-style dict *internally* if it reduces
   duplication. The public function signature and return values are frozen.

### 7.3 What stays put

- `ari/registry/` HTTP server: `KEEP` verbatim; documented as off-limits.
- `ari.schemas.load()`: leave the loader API alone here; whether to keep or
  `DELETE_CANDIDATE` the unused loader is a Subtask 053/057 decision, not this
  one. Note it in the handoff.
- Memory dispatch: `KEEP` the hardcoded `LettaMemoryClient` in `core.py`; record
  the `ARI_MEMORY_BACKEND`-unconsumed finding as a design note for Subtask 013.

## 8. Concrete Work Items

1. Decide and record the factory module name (Section 7.1), confirming it does
   not shadow `ari.registry`. Document the rejected `ari.registry.*` names.
2. Implement `BaseRegistry[T]` with: `register`, `resolve` (eager + lazy),
   `keys`, and a uniform unknown-key error that lists valid keys.
3. Adopt `BaseRegistry` for `_COMPOSITES`
   (`ari/evaluator/llm_evaluator.py`), keeping the `_COMPOSITES` name as an alias
   and preserving `LLMEvaluator.__init__`'s validation semantics (`:280-286`).
4. Adopt `BaseRegistry` for publish backends (`ari/publish/__init__.py`),
   preserving lazy import, the `ImportError → PublishError` fallbacks, and the
   `_load_backend(name)` wrapper signature.
5. Add a sync assertion/test tying `BaseRegistry.keys()` to
   `EvaluatorConfig.composite.__args__` and to the `publish.schema.json` enum;
   explicitly document (comment + test xfail/skip note) the `s3` schema-only gap.
6. Evaluate `resolve_litellm_model` (Section 7.2 step 3). If left unchanged,
   record the rationale (public-adjacent, transformation not construction).
7. Write the Subtask 013 handoff note (MemoryClient ABC-vs-Protocol; unconsumed
   `ARI_MEMORY_BACKEND`) and the Subtask 053/057 handoff note (`s3` enum gap,
   unused `ari.schemas.load()`).
8. Update per-directory `README.md` only where a factory module is added (e.g.
   a new `ari/factory/README.md`), keeping the existing `ari/registry/README.md`
   accurate about the name distinction.

## 9. Files Expected to Change

Runtime code (future implementation session — this doc changes none of them):

- `ari-core/ari/evaluator/llm_evaluator.py` — `_COMPOSITES` → `BaseRegistry`
  adoption; keep alias + validation.
- `ari-core/ari/publish/__init__.py` — `_load_backend` internals → registry;
  keep `_load_backend(name)` wrapper.
- **New** `ari-core/ari/factory/__init__.py` (or `ari-core/ari/_factory.py`) —
  `BaseRegistry` implementation. Name pending Section 7.1.
- **New** `ari-core/ari/factory/README.md` — per-directory README (if a package
  is chosen), stating the distinction from `ari/registry/`.
- `ari-core/ari/llm/routing.py` — *optional*, internals only if adopted; public
  signature frozen.
- `ari-core/tests/` — new sync/parity tests (Section 12).

Files that are inspected but **not** changed: `ari/registry/*`,
`ari/schemas/*`, `ari/config/__init__.py`, `ari/core.py`, `ari/memory/client.py`,
`ari/cli_ear.py`, `ari/viz/api_publish.py`, `ari/cost_tracker.py`,
`ari/llm/client.py`, `ari/schemas/publish.schema.json`.

## 10. Files / APIs That Must Not Be Broken

- **CLI:** `ari registry` subcommand (`ari/cli/__init__.py:97-98` →
  `ari/registry/cli.py:registry_app`) and its `serve`/`token`/`gc` commands.
- **Public Python API:** `ari.public.*` — in particular
  `ari.public.config_schema` re-exports `EvaluatorConfig` (composite `Literal`);
  `ari.public.llm`. Also `ari.llm.resolve_litellm_model` (exported at
  `llm/__init__.py:17-19`).
- **Config-file / external contracts:** `publish.schema.json:51` backend-name
  enum; `EvaluatorConfig.composite` `Literal` values.
- **Dispatcher entry points relied on by callers:** `ari.publish.publish` /
  `ari.publish.promote` (used by `cli_ear.py` and `viz/api_publish.py`);
  `_load_backend(name)` wrapper if any test references it.
- **String keys as live roots:** the four publish backend module paths under
  `ari/publish/backends/` (string-referenced; must remain resolvable and must
  not be flagged dead by 053/057).
- **HTTP artifact registry:** `ari/registry/build_app` endpoints, `TokenStore`,
  `FilesystemStorage` — untouched.
- **MCP / dashboard:** no MCP tool contract or dashboard endpoint is in scope;
  keep it that way (the publish dispatcher is reached only via
  `viz/api_publish.py`, whose function signatures stay fixed).

## 11. Compatibility Constraints

- Keep every current string key verbatim: `"ari-registry"`, `"local-tarball"`,
  `"zenodo"`, `"gh"` (publish) and `"harmonic_mean"`, `"arithmetic_mean"`,
  `"weighted_min"`, `"geometric_mean"` (composites), plus the `resolve_litellm_model`
  backend tokens `"anthropic"/"claude"/"ollama"/"cli-shim"/"cli_shim"`.
- The factory MUST support **lazy** resolution so optional-dependency backends
  (`zenodo`, `gh`) still import only on demand and still degrade to
  `PublishError("... not implemented")` on `ImportError`.
- Do **not** introduce `importlib.metadata` entry-points; registration stays
  in-tree and import-driven.
- Provide a compatibility **adapter** (module-level alias `_COMPOSITES`, wrapper
  `_load_backend`) for any name a test or caller currently imports, so no
  import path or call signature changes.
- Do not "fix" the `s3` enum by adding a backend; only document the gap. Removing
  `s3` from the schema enum would itself be an external-contract change and is
  out of scope here.
- The word "deprecated" is reserved for external contracts; none are being
  deprecated by this subtask.

## 12. Tests to Run

- `python -m compileall .` — byte-compile sanity across the repo.
- `pytest -q` — full suite. Targeted files of interest:
  `ari-core/tests/test_llm_routing.py` (exercises `resolve_litellm_model`
  prefix rules), any publish/evaluator tests, and the new sync/parity tests
  added in Section 8.5.
- `ruff check .` — lint (ruff **is** available; `radon` is **not** installed, so
  do not rely on complexity tooling here).
- Frontend (`npm test` / `npm run build`): **not applicable** — this subtask
  touches no `ari/viz/frontend/` code.
- New parity tests to add:
  - `set(BaseRegistry_composites.keys()) == set(EvaluatorConfig.composite.__args__)`.
  - Every `_load_backend` registry key ∈ `publish.schema.json` enum, with the
    `s3` schema-only gap asserted/documented explicitly.

## 13. Acceptance Criteria

- A single `BaseRegistry` helper exists at a name that does **not** shadow
  `ari.registry`, and is adopted by at least `_COMPOSITES` and `_load_backend`.
- All four publish backends and all four composite formulas resolve through the
  registry with byte-for-byte identical behaviour (same keys, same errors, same
  lazy-import fallbacks).
- `pytest -q`, `python -m compileall .`, and `ruff check .` all pass.
- New parity tests guard composite-keys↔`Literal` and backend-keys↔schema-enum,
  with the `s3` gap documented.
- `ari registry` CLI and `ari.publish.publish`/`promote` behave exactly as
  before (no signature/import-path change).
- Handoff notes for Subtask 013 (memory ABC/Protocol + unconsumed
  `ARI_MEMORY_BACKEND`) and Subtask 053/057 (`s3` gap, unused `schemas.load()`)
  are written into this doc's implementation output / the relevant subtask docs.

## 14. Rollback Plan

- The change is additive-plus-adapter: the new factory module can be deleted and
  the adapters (`_COMPOSITES` alias, `_load_backend` wrapper) reverted to their
  original `if/elif`/dict bodies in a single revert commit, because no public
  import path, CLI name, or string key changes.
- Because the four publish backend modules are string-referenced, verify after
  any rollback that `_load_backend("zenodo")` / `("gh")` still resolve (they are
  the modules most likely to be missed by a partial revert).
- Keep the commit split by dispatcher (composites, then publish, then optional
  routing) so a single dispatcher can be rolled back independently.
- No data/format migration is involved, so rollback has no on-disk state cost.

## 15. Dependencies

Per the dependency graph (`007 -> 014`):

- **Hard predecessor: 007** (`define_core_interfaces_and_protocols`). The
  factory must sit behind the Protocols that 007 finalizes
  (`ari/protocols/`), so 007 must land first.
- **Inventory gate (must precede any runtime-code change):** the master plan
  requires inventory subtasks **001, 002, 020, 036, 045, 053, 059, 060, 067**
  to precede runtime changes. Of these, **053** (`inventory_reference_roots`) is
  directly load-bearing here — it records the string-dispatched dynamic roots
  (`_load_backend`, `_COMPOSITES`, `schemas.load`) this subtask edits — and
  **001**/**002** (architecture + legacy/duplicate inventory) must be complete.
  Do not start the runtime refactor until 007 plus the inventory gate are done.
- **Downstream / adjacent (not blocking, but coordinate handoffs):** 013
  (memory boundary — receives the ABC/Protocol + `ARI_MEMORY_BACKEND` note), 057
  (`delete_safe_dead_code_candidates` — must honour the string-referenced backend
  roots), and 008/009 (model/evaluator interface extraction — share the Protocol
  layer).

## 16. Risk Level

**High.** **Changes runtime code: Yes.**

Rationale: the refactor edits live dispatch paths (`publish/__init__.py`,
`evaluator/llm_evaluator.py`) that feed external contracts (`publish.schema.json`
enum, `EvaluatorConfig.composite` `Literal`, the `ari registry` name), and it
touches string-only dynamic reference roots that static analysis cannot see. The
mitigations are the adapter shims (Section 11), the parity tests (Section 12),
and the per-dispatcher commit split (Section 14).

## 17. Notes for Implementer

- **Do not name anything `ari.registry` / `ari.registries`.** `ari/registry/` is
  the HTTP artifact registry (FastAPI, `build_app`, `ari registry` CLI). Use
  `ari/factory/` or `ari/_factory.py`. Re-read `ari/registry/README.md` before
  starting so the name distinction is preserved.
- **The publish backend modules are live-by-string.** Never let a "remove unused
  import" pass delete `ari/publish/backends/{ari_registry,local_tarball,zenodo,gh}.py`;
  they are reachable only through `_load_backend`.
- **Preserve lazy import.** `zenodo`/`gh` import inside `try/except ImportError`
  and must keep degrading to `PublishError`; do not eagerly import backends at
  registry construction time.
- **Keep the two key lists synced by test, not by hand.** The whole point of the
  unification is that `BaseRegistry.keys()` becomes the single source of truth;
  add the parity tests so the `Literal` and the JSON enum can never silently
  drift again.
- **The `s3` gap is real, not a typo to fix.** `publish.schema.json:51` lists
  `s3` but no backend module exists. Document it; do not add `s3` support and do
  not edit the schema enum (both are external-contract changes, out of scope).
- **`resolve_litellm_model` is the weakest fit** — it transforms a model id
  rather than constructing an object, and it is public-adjacent. Defaulting to
  KEEP-as-is is an acceptable outcome; forcing it into the registry for symmetry
  is discouraged.
- **`ari.schemas.load()` has no production importer** (only tests read schema
  files by path). Do not delete it here; flag it to Subtask 053/057.
- **Note on the confusable config trio:** unrelated to this subtask but easy to
  trip on — `ari/config/` (code), `ari/configs/` (packaged data + `_loader.py`),
  and top-level `ari-core/config/` (rubric data). There is **no `sonfigs/`**
  directory anywhere in the repo. The composite `Literal` lives in
  `ari/config/__init__.py`; the packaged-data `ConfigLoader` lives in
  `ari/configs/_loader.py`.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **014** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
