# Subtask 007: Define Core Interfaces And Protocols

> Phase 3: Core Architecture · Risk: Low · Runtime behavior change: **No**
> Primary output: the authoritative interface catalog (Protocol/ABC contracts) plus optional behavior-neutral type-only stubs under `ari-core/ari/protocols/`.
> This subtask is the fan-out root for **008, 009, 010, 011, 012, 013, 014** — every Phase-3 extraction adopts contracts defined here.

---

## 1. Goal

Define the complete set of internal **interfaces** (Protocols and ABCs) that the
Phase-3 extraction subtasks (008–014) will adopt, so that each extraction can
inject a typed contract instead of a concrete class. Concretely, this subtask:

1. Produces the **authoritative interface catalog**: one entry per target
   abstraction, each with (a) a Protocol-vs-ABC decision, (b) method signatures
   copied **verbatim** from the current concrete implementation so existing
   classes satisfy the contract structurally, and (c) the adopting subtask.
2. Optionally lands **pure type-only stub definitions** under
   `ari-core/ari/protocols/`, extending the existing package whose docstring
   already promises them (`ari/protocols/__init__.py:14-16`). These stubs are
   **not** imported by any runtime path in this subtask; wiring is deferred to
   008–014.
3. Resolves two design hazards up front: the `BaseRegistry`
   ↔ `ari/registry/` **name collision** (the latter is an HTTP artifact
   registry, not a DI container), and the **Protocol-vs-ABC naming
   inconsistency** in the memory package (`ari/memory/__init__.py:3,16` calls an
   ABC a "protocol").

The deliverable must be complete enough that a fresh coding session opening
subtask 008 can implement `BaseModelBackend` without re-deriving the contract.

---

## 2. Background

ARI's core already has a **deliberate Protocol package**:
`ari-core/ari/protocols/` (2 py files + README). Its `__init__.py` (23 lines)
exposes three contracts today — `Evaluator`, `PromptLoader`, `ConfigLoader` —
and its module docstring explicitly names the roadmap:

> "More Protocols (LLMClient, MCPClient, MemoryClient, NodeStore, StageRunner)
> land in subsequent phases when their adopters are ready."
> — `ari/protocols/__init__.py:14-16`

The established repo convention (recorded in `006_target_architecture_plan.md`
§2.1) is **Protocol by default, ABC only for a genuine substitution axis with
shared base logic**:

- `Evaluator` (`protocols/evaluator.py:18`) is a `@runtime_checkable Protocol`,
  satisfied **structurally** by `LLMEvaluator` (`evaluator/llm_evaluator.py:240`)
  with no subclassing.
- `PromptLoader` (`prompts/_loader.py:21`) and `ConfigLoader`
  (`configs/_loader.py:21`) are Protocols with a default filesystem impl
  (`FilesystemPromptLoader`, `FilesystemConfigLoader`).
- By contrast, `MemoryClient` (`memory/client.py:8`) is an **ABC**
  (`@abstractmethod add/search/get_all`), and the skill defines a divergent,
  richer `MemoryBackend` **ABC** (`ari-skill-memory/src/ari_skill_memory/backends/base.py:8`).

`006_target_architecture_plan.md` §3 is the **authoritative catalog** of the
target abstractions; this subtask turns that catalog into copy-ready contracts
(and optionally stubs). No `Base*` interface for the model backend, cost
tracker, evaluator base, stores, node store, stage, or DI registry exists in
code today — they are all named only in prose. `LLMClient`, `CostTracker`, and
`LLMEvaluator` are all concrete with no ABC above them.

---

## 3. Scope

- **In scope:** authoring the interface catalog; deciding Protocol vs ABC per
  interface; copying exact method signatures from current concrete classes;
  mapping each interface to its adopting subtask (008–014); resolving the
  `BaseRegistry` name-collision and the memory Protocol-vs-ABC inconsistency at
  the **design** level; optionally landing behavior-neutral, unimported type-only
  stub modules under `ari-core/ari/protocols/` and extending the package's
  `__init__.py` re-exports + `README.md` Contents list.
- **Boundary:** the stubs, if landed, must be pure `typing.Protocol` / `abc.ABC`
  definitions that **no existing runtime module imports**. Adoption, injection,
  and any behavior change belong to 008–014.

---

## 4. Non-Goals

- **No adoption / wiring.** Do not modify `core.py::build_runtime` (`core.py:83`),
  `AgentLoop`, `BFTS`, `run_pipeline`, or any call site to consume a new
  interface. That is 008–014.
- **No refactor of concrete classes.** Do not rename, re-signature, or move
  `LLMClient`, `LLMEvaluator`, `CostTracker`, `LettaMemoryClient`, `BFTS`,
  `AgentLoop`, or the composite functions.
- **No collapsing of the two memory ABCs** (core `MemoryClient` vs skill
  `MemoryBackend`) — that MERGE is subtask 013; here we only record the decision.
- **No registry unification** (`_load_backend`, `resolve_litellm_model`,
  memory-client selection) — that is subtask 014.
- **No new dependencies, no `importlib.metadata` entry-points.** `pyproject.toml`
  declares only `ari = "ari.cli:app"`; a future registry must be import-driven.
- **No changes** to prompts, configs, workflows, frontend, or directory names.
- **No "sonfigs".** There is no `sonfigs/` directory anywhere in the repo; the
  confusable trio is `ari/config/` (code) vs `ari/configs/` (packaged defaults)
  vs top-level `config/` (rubric data). Nothing here touches that.

---

## 5. Current Files / Directories to Inspect

Existing Protocol/loader surfaces (the pattern to follow):

- `ari-core/ari/protocols/__init__.py` (23 lines) — exposes `Evaluator`,
  `PromptLoader`, `ConfigLoader`; docstring lists the roadmap.
- `ari-core/ari/protocols/evaluator.py` (40 lines) — `@runtime_checkable`
  `Evaluator` Protocol, single async `evaluate(...)`.
- `ari-core/ari/protocols/README.md` — Contents list to keep in sync.
- `ari-core/ari/prompts/_loader.py` — `PromptLoader` Protocol +
  `FilesystemPromptLoader` (`load`, `load_versioned`).
- `ari-core/ari/configs/_loader.py` — `ConfigLoader` Protocol +
  `FilesystemConfigLoader` (`load`).

Concrete classes that the new interfaces must fit **structurally**:

- `ari-core/ari/llm/client.py` — `LLMClient` (class at `:26`, **concrete, no
  ABC**); `LLMMessage`/`LLMResponse` dataclasses; also the public symbol via
  `ari/public/llm.py`. → `BaseModelBackend` (subtask 008).
- `ari-core/ari/llm/routing.py` — `resolve_litellm_model(model, backend)`
  (`:37`), the single provider-prefix source of truth. → registry (subtask 014).
- `ari-core/ari/evaluator/llm_evaluator.py` (part of the 1261-LOC evaluator
  pkg) — `LLMEvaluator` (`:240`); composite registry `_COMPOSITES`
  (`:165`, keys validated `:280`). → `BaseEvaluator` / `BaseCompositeEvaluator`
  (subtask 009).
- `ari-core/ari/config/__init__.py` — `EvaluatorConfig.composite` **Literal**
  (`:212`), a public field via `config_schema`.
- `ari-core/ari/cost_tracker.py` (448 LOC) — `CostTracker` (`:77`, **concrete,
  no ABC**); global singleton + free functions. → `BaseCostTracker` (design-only
  here; no dedicated fan-out subtask among 008–014).
- `ari-core/ari/memory/client.py` (23 lines) — `MemoryClient` **ABC**
  (`add/search/get_all`); impls `letta_client.py`, `file_client.py`,
  `local_client.py`. → `BaseMemoryClient` (subtask 013).
- `ari-skill-memory/src/ari_skill_memory/backends/base.py` — richer
  `MemoryBackend` **ABC** (`:8`); divergent from the core ABC.
- `ari-core/ari/orchestrator/node.py` — `Node` (`:87`), `NodeStatus`,
  `NodeLabel`; `ari-core/ari/orchestrator/node_report/` — node-report I/O. →
  `NodeStore` (subtask 011).
- `ari-core/ari/orchestrator/bfts.py` (845 LOC) — `BFTS` strategy, currently
  also does filesystem I/O (`:43-416`) and prompt assembly (`:604-760`). →
  `BaseStrategy` / `BasePromptBuilder` (subtask 011).
- `ari-core/ari/agent/loop.py` (1630 LOC) — `AgentLoop.run`; and
  `ari-core/ari/agent/react_driver.py` (442 LOC), a second generic ReAct loop. →
  `BaseAgentLoop` (subtask 008/011).
- `ari-core/ari/pipeline/orchestrator.py` (913 LOC) — `run_pipeline` (`:548`),
  the YAML-driven while-loop; `ari-core/ari/pipeline/stage_runner.py`;
  `ari-core/ari/pipeline/yaml_loader.py`. → `BasePipelineStage` / `StageRunner`
  (subtask 012).
- `ari-core/ari/checkpoint.py`, `ari-core/ari/paths.py`,
  `ari-core/ari/public/paths.py` — flat-file checkpoint I/O. →
  `BaseArtifactStore` / `BaseCheckpointStore` / `BaseTraceStore` (subtask 010).
- `ari-core/ari/mcp/client.py` — MCP stdio client. → `BaseSkillAdapter`
  (design-only here; adopted during the loop refactor).
- `ari-core/ari/publish/__init__.py` — `_load_backend(name)` if/elif dispatcher
  (`:198`); `ari-core/ari/schemas/publish.schema.json` backend-name **enum**
  (`:51`: `ari-registry, gh, zenodo, s3, local-tarball`). → registry (subtask 014).
- `ari-core/ari/registry/` (5 files, ~366 LOC) — **HTTP artifact registry**
  (FastAPI `build_app`, `app.py`), wired as `ari registry` typer group
  (`cli/__init__.py:97-98`). **Name-collision hazard** with any `BaseRegistry`.
- `ari-core/ari/public/` — stable surfaces (`config_schema.py`, `llm.py`,
  `cost_tracker.py`, `paths.py`, `container.py`, `run_env.py`,
  `verified_context.py`, `claim_gate.py`).
- `ari-core/ari/core.py` — `build_runtime` (`:83`) composition root wiring
  `LettaMemoryClient` (`:130`), `BFTS` (`:148`), `LLMEvaluator` (`:195`),
  `AgentLoop` (`:219`).

Design authority (read first):

- `docs/refactoring/006_target_architecture_plan.md` §2.1 (Protocol-vs-ABC rule),
  §2.2 (L1–L5 layering), §3 (the interface catalog — §3.1 `BaseModelBackend`
  through §3.7 `BaseMemoryClient`, and the store/registry blocks).
- `docs/refactoring/007_subtask_index.md` (rows 54–61; Phase-3 dependency edges
  `007 -> 008..014`).

---

## 6. Current Problems

1. **The roadmap is prose, not contracts.** `protocols/__init__.py:14-16` names
   `LLMClient, MCPClient, MemoryClient, NodeStore, StageRunner` but none exist as
   types; 008–014 would each have to re-derive the same contracts, risking
   divergent signatures.
2. **Key subsystems have no interface above the concrete class.** `LLMClient`
   (`llm/client.py:26`), `CostTracker` (`cost_tracker.py:77`), and `LLMEvaluator`
   (`evaluator/llm_evaluator.py:240`) are all concrete; there is no
   `BaseModelBackend`, `BaseCostTracker`, or `BaseEvaluator`.
3. **Protocol-vs-ABC convention is not unified.** `Evaluator`/`PromptLoader`/
   `ConfigLoader` are Protocols; `MemoryClient` is an ABC; yet
   `memory/__init__.py:3,16` mislabels the ABC as a "protocol." A fresh session
   needs one written rule (006 §2.1) applied per interface.
4. **Two divergent memory ABCs.** Core `MemoryClient` (`memory/client.py:8`,
   `add/search/get_all`) and skill `MemoryBackend`
   (`backends/base.py:8`, `add_memory/search_memory/get_node_memory/... + react_*
   + bulk_import`) share no types. Any `BaseMemoryClient` contract must be chosen
   knowing both (decision recorded here, MERGE executed in 013).
5. **Name-collision hazard.** `ari/registry/` is an **HTTP FastAPI artifact
   registry** wired into the CLI as `ari registry`, not a DI/factory container. A
   naively named `BaseRegistry` would shadow it and confuse readers and imports.
6. **No plugin/entry-point extensibility exists.** `pyproject.toml` declares only
   `ari = "ari.cli:app"`; all extensibility is in-tree string keys
   (`_load_backend`, `_COMPOSITES`, `resolve_litellm_model`). The registry
   interface must be import-driven, not `importlib.metadata`-based.
7. **Composite keys and enums are public-adjacent.** `_COMPOSITES` keys must stay
   in sync with the public `EvaluatorConfig.composite` Literal
   (`config/__init__.py:212`), and `_load_backend` names duplicate the
   `publish.schema.json:51` enum. The interface design must forbid renaming these
   strings.

---

## 7. Proposed Design / Policy

### 7.1 Method

For every abstraction in `006_target_architecture_plan.md` §3, produce a catalog
entry with this fixed shape:

- **Role name** (the `Base*` name from the master vocabulary).
- **Protocol or ABC** — decided by the 006 §2.1 rule: *Protocol by default; ABC
  only when a genuine multi-impl substitution axis coincides with shared,
  non-trivial base logic.*
- **Exact signature(s)** copied verbatim from the current concrete class so it is
  satisfied **structurally** with zero source change to that class.
- **Adopting subtask** (008–014) and classification (KEEP / ADAPT / MERGE /
  MOVE_TO_LEGACY / REVIEW_REQUIRED).

### 7.2 Interface catalog (decisions)

| Interface (role) | Kind | Grounding concrete | Adopting subtask | Class |
|---|---|---|---|---|
| `Evaluator` (exists) | Protocol | `LLMEvaluator` (`llm_evaluator.py:240`) | 009 | KEEP |
| `BaseCompositeEvaluator` | Protocol | `_COMPOSITES` fns (`llm_evaluator.py:165`) | 009 | ADAPT |
| `BaseModelBackend` | Protocol | `LLMClient` (`llm/client.py:26`) | 008 | ADAPT |
| `BasePromptBuilder` | Protocol | inline in `bfts.py`/`loop.py` (no class) | 008/011 | ADAPT |
| `BaseAgentLoop` | ABC | `AgentLoop` + `react_driver` (MERGE) | 008/011 | MERGE |
| `BaseStrategy` | ABC | `BFTS` (`orchestrator/bfts.py`) | 011 | ADAPT |
| `NodeStore` | Protocol | `node_report/` + `bfts.py:43-416` | 011 | ADAPT |
| `BaseArtifactStore` / `BaseCheckpointStore` / `BaseTraceStore` | Protocol | `checkpoint.py` flat-file I/O | 010 | ADAPT |
| `BasePipelineStage` / `StageRunner` | ABC | `run_pipeline` (`orchestrator.py:548`) | 012 | ADAPT |
| `BaseMemoryClient` | ABC (keep) | `MemoryClient` (`memory/client.py:8`) | 013 | MERGE |
| `BaseSkillAdapter` (MCP) | Protocol | `mcp/client.py` | 008/011 | ADAPT |
| `BaseCostTracker` | Protocol | `CostTracker` (`cost_tracker.py:77`) | design-only | REVIEW_REQUIRED |
| `BaseRegistry` | ABC/generic | `_load_backend`, `_COMPOSITES`, memory sel. | 014 | ADAPT |

Kind rationale (per 006 §2.1): `BaseModelBackend`, `NodeStore`,
`BasePromptBuilder`, the stores, `BaseSkillAdapter`, and `BaseCostTracker` have
essentially one production impl + test doubles → **Protocol**. `BaseAgentLoop`,
`BaseStrategy`, `BasePipelineStage`, and `BaseMemoryClient` have real shared base
machinery and/or an existing ABC to preserve → **ABC**.

### 7.3 Optional stub modules (behavior-neutral)

If the team wants the "+ stubs" deliverable (per index row 54), land pure
type-only modules under `ari-core/ari/protocols/` — one per interface family —
each importing only `typing`/`abc` and (under `TYPE_CHECKING` only) any value
types, so there is **no import cycle and no runtime effect**. Suggested modules:
`model_backend.py`, `memory.py`, `stores.py`, `node_store.py`, `stage.py`,
`skill_adapter.py`, `cost_tracker.py`, `registry.py`. Then extend
`protocols/__init__.py` re-exports and `__all__`, and update
`protocols/README.md` Contents. No existing runtime module may import these in
this subtask (a grep gate proves zero adoption — see §13).

### 7.4 Name-collision and naming policy

- **`BaseRegistry` must not live in, import, or shadow `ari/registry/`.** Place
  the DI/factory contract at `ari/protocols/registry.py` and give it a
  non-colliding public name (e.g. `Registry` / `FactoryRegistry`), explicitly
  documenting that `ari.registry` is the unrelated HTTP artifact server. The
  actual factory unification is subtask 014.
- **Fix the Protocol-vs-ABC label** for memory at the design level: record that
  `MemoryClient` is an **ABC** (not a "protocol"); the docstring correction in
  `memory/__init__.py` is executed in 013, not here.
- **String keys are frozen.** The design must state that composite keys
  (`harmonic_mean|arithmetic_mean|weighted_min|geometric_mean`) and publish
  backend names (`ari-registry|gh|zenodo|s3|local-tarball`) are contract strings;
  interfaces reference them, never rename them.

### 7.5 Layering the interfaces feed (context for 008–014)

The catalog is organized by the 006 §2.2 layers (L1 Foundation → L5
Presentation) so that adopters respect the strictly-downward dependency rule and
help remove the two known inversions: the core→viz edge
(`cli/lineage.py:151`) and the core→skill edge (`agent/loop.py:1047` imports
`ari_skill_memory.backends`).

---

## 8. Concrete Work Items

1. Read `006_target_architecture_plan.md` §2.1, §2.2, §3 in full; treat §3 as the
   source of truth for method lists.
2. For each interface in the §7.2 table, extract the **exact current signature**
   from the cited concrete class and record it in the catalog (copy, do not
   paraphrase). Confirm the existing concrete class satisfies it unchanged.
3. Record the Protocol-vs-ABC decision and classification per interface, applying
   the 006 §2.1 rule; justify any ABC with the shared-base-logic test.
4. Write the **name-collision resolution** for `BaseRegistry` vs `ari/registry/`
   and the **memory ABC-vs-Protocol** label decision (design only).
5. Enumerate the frozen contract strings (composite keys, publish enum) the
   interfaces must not rename, with file:line citations.
6. **(Optional, per index row 54)** Land behavior-neutral stub modules under
   `ari-core/ari/protocols/`:
   - Create one stub `.py` per interface family (§7.3), pure `typing`/`abc`, no
     top-level import of concrete impls (use `TYPE_CHECKING`).
   - Extend `protocols/__init__.py` re-exports + `__all__` and update the
     roadmap docstring to reflect what is now stubbed vs pending.
   - Update `protocols/README.md` Contents list.
   - Prove **zero adoption**: `grep -rn` from the new stub names finds only the
     definitions/re-exports, no consuming import.
7. Cross-check each catalog entry's "adopting subtask" against the dependency
   graph edges `007 -> 008..014` so no interface is orphaned.

---

## 9. Files Expected to Change

Design-only variant (no code): only this document
(`docs/refactoring/subtasks/007_define_core_interfaces_and_protocols.md`) plus
the catalog it contains.

"+ stubs" variant (behavior-neutral, per index row 54):

- `ari-core/ari/protocols/__init__.py` — extend re-exports, `__all__`, roadmap
  docstring (currently 23 lines; `Evaluator`/`PromptLoader`/`ConfigLoader`
  preserved).
- `ari-core/ari/protocols/README.md` — Contents list refresh.
- **New**: `ari-core/ari/protocols/model_backend.py`,
  `ari-core/ari/protocols/memory.py`, `ari-core/ari/protocols/stores.py`,
  `ari-core/ari/protocols/node_store.py`, `ari-core/ari/protocols/stage.py`,
  `ari-core/ari/protocols/skill_adapter.py`,
  `ari-core/ari/protocols/cost_tracker.py`,
  `ari-core/ari/protocols/registry.py` — each a pure type-only stub, not
  imported by any existing runtime module.

No other runtime file is touched. Do **not** edit `core.py`, `llm/client.py`,
`evaluator/`, `memory/client.py`, `orchestrator/`, `agent/`, `pipeline/`,
`checkpoint.py`, `mcp/client.py`, or any `public/` module in this subtask.

---

## 10. Files / APIs That Must Not Be Broken

- **`ari.protocols` existing exports** — `Evaluator`, `PromptLoader`,
  `ConfigLoader` must remain importable with unchanged names/signatures
  (`protocols/__init__.py`, `evaluator.py`, `prompts/_loader.py`,
  `configs/_loader.py`).
- **`ari.public.*` stable API** — `config_schema`, `llm` (incl. the
  `LLMClient` symbol and its `LLMClient(config: LLMConfig)` constructor),
  `cost_tracker`, `paths`, `container`, `run_env`, `verified_context`,
  `claim_gate`. Introducing interfaces must not shadow or re-signature these.
- **`EvaluatorConfig.composite` Literal** (`config/__init__.py:212`) and the
  `_COMPOSITES` key strings — no renames.
- **`MemoryClient` ABC methods** `add/search/get_all` (`memory/client.py:8`) —
  unchanged; the merge is 013.
- **`publish.schema.json` backend-name enum** (`:51`) — unchanged.
- **`ari/registry/` HTTP server and `ari registry` CLI group** — must not be
  renamed, shadowed, or imported by any new `Base/Registry` interface.
- **MCP tool contracts** (14 `ari-skill-*` `src/server.py`), **dashboard API**
  (`viz/routes.py` + `api_*.py`, `services/api.ts`), **checkpoint/config file
  formats**, **CLI `ari`**, and **README/docs usage** — untouched by this
  subtask.
- Existing concrete class names/constructors: `LLMClient`, `LLMEvaluator`,
  `CostTracker`, `BFTS`, `AgentLoop`, `LettaMemoryClient` — unchanged.

---

## 11. Compatibility Constraints

- New interfaces must be satisfied **structurally** by the current concrete
  classes with **zero source change** to those classes (Protocol default per 006
  §2.1). Copy signatures verbatim to guarantee this.
- Stub modules must be **import-safe and behavior-neutral**: only `typing`/`abc`
  at module top level; any value-type references go under `TYPE_CHECKING` to
  avoid import cycles (e.g. `LLMMessage`, `Node`, `LLMConfig`).
- `BaseRegistry`/factory contract must be **import-driven**, never
  `importlib.metadata` entry-points (`pyproject.toml` declares only
  `ari = "ari.cli:app"`).
- Preserve the `_COMPOSITES` dict as-is; interfaces describe it, they do not
  replace it in this subtask.
- Any ABC decision must keep the existing `MemoryClient` ABC method set intact so
  its three impls (`LettaMemoryClient`, `FileMemoryClient`, `LocalMemoryClient`)
  remain valid without edits.
- Do not use the term "deprecated" for internal modules; it is reserved for
  external contracts.

---

## 12. Tests to Run

From `ari-core/` (and repo root where noted):

- `python -m compileall .` — must pass; any landed stubs must byte-compile.
- `ruff check .` — must pass (ruff is available; `radon` is **not** installed, so
  do not rely on it).
- `pytest -q` — full suite must remain green with **no test changes**; the large
  suites (`tests/test_server.py` 1844, `tests/test_gui_errors.py` 1650,
  `tests/test_workflow_contract.py` 1606, `tests/test_wizard.py` 1133) must be
  unaffected because nothing consumes the new stubs.
- Import smoke: `python -c "import ari.protocols; print(ari.protocols.__all__)"`
  — must still expose `Evaluator`, `PromptLoader`, `ConfigLoader` (plus any newly
  stubbed names).
- Optional structural check (only if stubs landed): a `runtime_checkable`
  `isinstance` smoke asserting `LLMClient`/`LLMEvaluator`/`LettaMemoryClient`
  satisfy their respective new Protocols — but keep this in a scratch script, not
  a committed test, since committing tests is out of scope for a design subtask.

No frontend build applies (this subtask touches no `ari/viz/frontend/`); `npm
test`/`npm run build` are **not** required.

---

## 13. Acceptance Criteria

1. The catalog covers **every** abstraction in `006_target_architecture_plan.md`
   §3, each with: Protocol-vs-ABC decision, verbatim current signature(s),
   classification (KEEP/ADAPT/MERGE/MOVE_TO_LEGACY/REVIEW_REQUIRED), and the
   adopting subtask (008–014). No abstraction is orphaned relative to the
   `007 -> 008..014` edges.
2. Every existing concrete class named in the catalog satisfies its assigned
   interface **without any source change** (verified by inspection or an optional
   `isinstance` smoke).
3. The `BaseRegistry` ↔ `ari/registry/` name-collision resolution is documented,
   and no stub imports/shadows `ari.registry`.
4. The memory Protocol-vs-ABC inconsistency is recorded with a decision (ABC
   kept; docstring fix deferred to 013).
5. Frozen contract strings (composite keys, publish enum) are listed with
   file:line and marked non-renameable.
6. If stubs landed: `python -m compileall .`, `ruff check .`, and `pytest -q` all
   pass with no test edits; `import ari.protocols` still exposes the original
   three contracts; and `grep -rn` proves **zero** existing runtime module
   imports the new stub names (adoption is deferred).

---

## 14. Rollback Plan

- **Design-only variant:** nothing to roll back — no runtime file changed.
- **"+ stubs" variant:** the change is purely additive and unused. Roll back by
  deleting the new `ari-core/ari/protocols/*.py` stub modules and reverting the
  two edited files (`protocols/__init__.py`, `protocols/README.md`) to their
  prior 23-line / current state. Because no runtime path imports the stubs, there
  is zero behavior impact and no downstream subtask breaks (008–014 have not yet
  adopted them). `git checkout -- ari-core/ari/protocols/` suffices if no other
  work is staged there.

---

## 15. Dependencies

- **Incoming: none.** In the dependency graph, `007` is a **root** (no `X -> 007`
  edge); the subtask index marks it "Can Run Independently? = Yes." It does not
  depend on the path/config subtasks (`004 -> 005, 006`; `003`).
- **Outgoing (this subtask enables):** `007 -> 008, 009, 010, 011, 012, 013,
  014`. Every Phase-3 extraction consumes the contracts defined here, so 007 must
  **precede** all of them.
- **Advisory (not blocking):** the Phase-1 inventory subtasks `001`
  (complexity/dependency baseline) and `002` (legacy/duplicate inventory) give
  useful context on which concrete classes are live (e.g. the string-only
  `publish/backends/*` modules), but 007 has no formal edge to them.
- Per the master rule, inventory subtasks `001, 002, 020, 036, 045, 053, 059,
  060, 067` must precede any **runtime** code change; since 007 introduces no
  runtime behavior change (at most behavior-neutral stubs), it is free to run in
  the design wave without waiting on them.

---

## 16. Risk Level

**Low.**

**Does this subtask change runtime code? No** (runtime *behavior*: No). The
design-only deliverable touches no code. The optional "+ stubs" deliverable adds
**pure type-only Protocol/ABC definitions** under `ari-core/ari/protocols/` that
**no existing runtime path imports**, so there is no change to any execution
path, wiring, or output. The subtask index (row 54) classifies 007 as "Runtime
Code Change? = No, Can Run Independently? = Yes." The only real risks are (a)
signature drift — mitigated by copying signatures verbatim from the concrete
classes; and (b) the `BaseRegistry` name-collision — mitigated by the §7.4 policy
of keeping the DI contract out of `ari/registry/`.

---

## 17. Notes for Implementer

- **`006_target_architecture_plan.md` §3 is authoritative** for method lists;
  this subtask is the "make it copy-ready + optionally stub" step, not a redesign.
  If §3 and a concrete class disagree, the **concrete class wins** (structural
  satisfaction is the whole point) and you flag the doc drift.
- **Follow 006 §2.1 strictly:** Protocol by default; ABC only where a real
  substitution axis coincides with shared base logic. Recorded decisions:
  Protocol for `BaseModelBackend`, `NodeStore`, `BasePromptBuilder`, the three
  stores, `BaseSkillAdapter`, `BaseCostTracker`; ABC for `BaseAgentLoop`,
  `BaseStrategy`, `BasePipelineStage`, and (keep) `BaseMemoryClient`.
- **Never import concrete impls at stub module top level.** Use
  `from __future__ import annotations` + `TYPE_CHECKING` for value types
  (`LLMMessage`, `Node`, `LLMConfig`, etc.) to keep the stubs cycle-free and
  behavior-neutral.
- **`ari/registry/` is an HTTP artifact registry, not a DI container** — it is
  wired as `ari registry` at `cli/__init__.py:97-98`. Do not put `BaseRegistry`
  there or import it; name the DI contract distinctly (e.g.
  `ari.protocols.registry.Registry`).
- **The two memory ABCs diverge on purpose-of-scope** (core `add/search/get_all`
  vs skill `add_memory/search_memory/get_node_memory/react_*/bulk_import`).
  Record the union/decision but do **not** merge here — that is 013.
- **Frozen strings:** composite keys (`config/__init__.py:212`) and publish enum
  (`publish.schema.json:51`) are public-adjacent contracts; interfaces reference
  them, never rename them.
- **Tooling reality:** `ruff` is available, `radon` is **not**; `python -m
  compileall`/`pytest` are available; `node`/`npm` exist but no frontend work is
  in scope here (no `pnpm`).
- **"sonfigs" does not exist** — do not act on the hypothesized typo; the real
  trio is `ari/config/` (code) vs `ari/configs/` (packaged defaults) vs top-level
  `config/` (rubric data).
- Keep the deliverable **self-contained**: a fresh session opening subtask 008
  should be able to implement `BaseModelBackend` from this catalog alone, with
  `llm/client.py:26` open beside it.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **007** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
