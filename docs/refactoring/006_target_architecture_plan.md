---
title: ARI Target Architecture Plan
doc: 006
phase: planning
status: draft
canonical_language: en
last_verified: 2026-07-01
sources:
  - path: ari-core/ari
    role: implementation
  - path: ari-core/config
    role: config
  - path: scripts/docs
    role: test
---

# 006 — Target Architecture Plan (class-based)

> **Planning only.** This document designs a target class hierarchy for ARI. It
> changes **no** runtime code, imports, prompts, configs, workflows, frontend,
> or directory names. The only artefact it produces is this `.md` file.
>
> Every path and line count below was verified by reading the repository at
> `/home/t-kotama/workplace/ARI` on 2026-07-01 (`ari-core` version `0.9.0`,
> git branch `main`). Where an abstraction has **no** current implementation,
> that is stated as *"does not exist"* rather than assumed.

---

## 1. Scope and intent

ARI today is a working system whose core (`ari-core/ari/`, package `ari`) is
overwhelmingly **procedural**: composition happens in one function
(`ari/core.py::build_runtime`, L83–222), the two hottest execution paths are
single mega-methods (`ari/agent/loop.py::AgentLoop.run`, ~1170 lines inside a
1630-line file; `ari/pipeline/orchestrator.py::run_pipeline`, the 913-line
loop), and most "pluggable" seams are string-keyed `if/elif` dispatchers rather
than typed interfaces. A deliberate `ari/protocols/` package already exists and
names its own roadmap (`protocols/__init__.py:14–16`: *"More Protocols
(LLMClient, MCPClient, MemoryClient, NodeStore, StageRunner) land in subsequent
phases"*), so the target below is an **extension of an intent the codebase
already declares**, not a rewrite.

The goal of this document is to fix, for the whole refactor, **24 named
abstractions**, map each to the concrete code that will back it, and hand each
to a downstream subtask document (007–014). It is the architectural contract
that subtasks 007–014 implement against.

### 1.1 Non-negotiable external contracts

The following must survive the refactor unchanged (or behind an explicit
compatibility adapter). Each abstraction block below carries a
**Compatibility concerns** entry that references the relevant contract:

- **CLI**: the single console script `ari = ari.cli:app` and every subcommand
  name / option flag / env-var side effect (`ari/cli/__init__.py`, 175 lines;
  order pinned by `_reorder_commands_for_compat()`, L148–170).
- **`ari.public.*` API**: `claim_gate, config_schema, container, cost_tracker,
  llm, paths, run_env, verified_context` (`ari-core/ari/public/`, 9 files).
- **MCP tool contracts**: 14 `ari-skill-*/src/server.py` servers, bare
  snake_case tool names, `inputSchema`, and the `{"result"|"error"}` return
  envelope consumed via `ari/mcp/client.py` (`MCPClient`, L256).
- **Dashboard API**: `ari/viz/routes.py` (1197) + `api_*.py` endpoints and
  `websocket.py`, consumed by `frontend/src/services/api.ts` (863 lines).
- **On-disk formats**: checkpoint layout (`ari/checkpoint.py`, 198 lines;
  `PathManager.META_FILES`, `paths.py:51–76`) and config/rubric YAML under
  `ari-core/config/` and `ari-core/ari/configs/`.
- **`ari-skill-* → ari-core` stable interfaces**, README/docs usage, and any
  script invoked by `.github/workflows/` (5 workflows).

The word **"deprecated"** is reserved in this document for those external
contracts. Internal code is classified with the vocabulary in §2.3.

### 1.2 A note on the "config / configs / sonfigs" trio

There is **no `sonfigs/` directory anywhere** in the repository (`find -iname
'*sonfig*'` returns nothing); "sonfigs" is a hypothesised typo and is called
out as non-existent wherever the config surface is discussed. The real,
confusable trio is:

| Path | Nature | Backs which abstraction |
|---|---|---|
| `ari-core/ari/config/` | Python **code** — Pydantic models + `finder.py` discovery | `RuntimePathResolver` (discovery), schema (`ConfigLoader`) |
| `ari-core/ari/configs/` | packaged **data** — `defaults.yaml`, `model_prices.yaml` + `_loader.py` | `ConfigLoader` impl, `BaseCostTracker` pricing |
| `ari-core/config/` | shipped **rubric/profile/workflow data** — `workflow.yaml`, `profiles/`, `*_rubrics/` | `BaseWorkflowDriver`, `BaseCompositeEvaluator` axes |

---

## 2. Design tenets

### 2.1 Composition over inheritance — the governing principle

**Inheritance is used only for a genuine "is-a" substitution axis; everything
else is composition (dependency injection through constructors).** Concretely:

- A `Base*` class exists **only** where we expect *multiple interchangeable
  implementations selected at runtime or in tests* (e.g. `BaseModelBackend`:
  litellm vs cli-shim vs a test stub; `BaseMemoryClient`: letta vs file vs
  local; `BasePipelineStage`: subprocess-MCP vs ReAct). These are the true
  substitution axes.
- Where there is realistically **one** implementation plus test doubles, the
  contract is a **`typing.Protocol`**, not an ABC, following the pattern the
  repo already chose for `Evaluator` (`protocols/evaluator.py:18`,
  `@runtime_checkable`, satisfied *structurally* by `LLMEvaluator` with no
  subclassing), `PromptLoader` (`prompts/_loader.py:21`), and `ConfigLoader`
  (`configs/_loader.py`). This keeps existing concrete classes source-compatible
  — they already satisfy the Protocol without a class-hierarchy change.
- **Behaviour is injected, not inherited.** `AgentLoop` should *hold* a
  `BasePromptBuilder`, a `BaseModelBackend`, a `BaseEvaluator`, and stores — it
  should not subclass any of them. `BFTS` should *hold* a `BasePromptBuilder`
  and a node-report store rather than reading the filesystem itself
  (today it does both: `bfts.py` L43–416 file I/O + L604–760 prompt assembly).
- **`Base` prefix vs `Protocol`**: this document uses the `Base*` names from the
  master vocabulary as *role names*. For each one, the block states whether the
  concrete realisation should be an **ABC** (shared implementation + enforced
  override) or a **Protocol** (pure structural contract). The default is
  Protocol; ABC is chosen only when shared non-trivial base logic exists.

### 2.2 Layering (dependency direction)

Target dependency flow is strictly downward; the current core→viz edge
(`cli/lineage.py:151` imports `viz.api_orchestrator`) and the core→skill edge
(`agent/loop.py` L1047 imports `ari_skill_memory.backends`) are the two
inversions the layering is designed to remove or route through an adapter.

```
  L5  Presentation   cli/*,  viz/* (routes + api_*),  frontend
        |  (DashboardViewService / DashboardDTO, CLI Typer app)
  L4  Orchestration  BaseWorkflowDriver, BaseAgentLoop, BaseStrategy
        |  (ExecutionContext + ExecutionServices as the composition root)
  L3  Domain services BaseEvaluator/BaseCompositeEvaluator, BasePromptBuilder,
        |               BasePipelineStage, PromptRegistry
  L2  Infrastructure  BaseModelBackend, BaseMemoryClient, BaseSkillAdapter,
        |               BaseCostTracker, BaseLogger, BaseRegistry
  L1  Foundation      RuntimePathResolver, BaseArtifactStore,
                      BaseCheckpointStore, BaseTraceStore, PromptLoader,
                      ConfigLoader (existing)
```

### 2.3 Classification vocabulary (per current-code disposition)

- **KEEP** — already close to target; wrap with the interface, minimal change.
- **ADAPT** — retain behaviour, extract an interface and inject it.
- **MERGE** — two implementations collapse into one behind the interface.
- **MOVE_TO_LEGACY** — retain only as a migration source; not on the hot path.
- **DELETE_CANDIDATE** — appears dead; must be confirmed live before removal.
- **REVIEW_REQUIRED** — disposition needs a decision by the subtask owner.

---

## 3. Target abstractions

Each block follows the fixed schema: **Purpose / Current implementation
candidates / Methods / State ownership / Expected concrete implementations /
Composition relationships / Compatibility concerns / Migration subtasks.**

---

### 3.1 `BaseModelBackend`  →  subtask 007

- **Purpose.** A typed provider abstraction for "send messages, get a
  completion + token usage + cost signal," decoupling call sites from litellm
  and from the cli-shim special cases.
- **Current implementation candidates.** `ari/llm/client.py::LLMClient` (L26,
  concrete, **no ABC** today) wrapping `litellm.completion` (`timeout=1800`
  hardcoded, L180); `ari/llm/routing.py::resolve_litellm_model` (L37, the single
  provider-prefix router, `_KNOWN_PREFIXES` L21); `ari/llm/cli_server.py` (919
  LOC OpenAI-compatible shim around `claude -p`/`codex exec`, `VIRTUAL_MODELS`
  L743). **Second, hidden call site:** `LLMEvaluator.evaluate` calls
  `litellm.acompletion` **directly** (`evaluator/llm_evaluator.py:585`),
  bypassing `LLMClient` — a backend leak the abstraction must close.
- **Methods.** `complete(messages, *, node_id, phase, skill, work_dir,
  tools=None) -> LLMResponse`; `resolve_model(model, backend) -> str`;
  `attach_mcp(mcp_client)` (replaces the post-construction `llm.mcp_client = mcp`
  mutation in `core.py:146`). Return type reuses existing dataclasses
  `LLMMessage`/`LLMResponse` (`client.py:14,20`).
- **State ownership.** Owns per-call context (`_node_id/_phase/_skill/_work_dir`,
  `client.py:29–33`) and the injected `MCPClient` handle. Does **not** own cost
  accounting — that belongs to `BaseCostTracker` (§3.15); today the two are
  entangled only via the global litellm monkeypatch.
- **Expected concrete implementations.** `LiteLLMBackend` (KEEP `LLMClient`
  behaviour, ADAPT to the interface), `CliShimBackend` (the port-8900 target,
  detected today by `_is_cli_shim_target`, `client.py:71`), and a test
  `StubBackend`. Retry/backoff (absent everywhere today — no `num_retries`,
  no tenacity) is added **once** here.
- **Composition relationships.** Injected into `BaseAgentLoop`, `BaseStrategy`
  (BFTS is itself an LLM caller: `bfts.py` L485/564/762), and `BaseEvaluator`.
  Constructed in `ExecutionServices` (§3.19), one instance per phase as
  `core.py::_phase_llm` (L119–125) already does.
- **Compatibility concerns.** `ari.public.llm.LLMClient` is a **stable public
  symbol** (`public/llm.py:10`). `LLMClient` must remain importable with its
  current name and constructor `LLMClient(config: LLMConfig)`; the ABC/Protocol
  is introduced *above* it, and `LiteLLMBackend` can simply *be* `LLMClient`
  renamed-by-alias. No public rename in this phase.
- **Migration subtasks.** (a) Define the Protocol in `ari/protocols/` (roadmap
  already lists `LLMClient`). (b) Route `LLMEvaluator` through the backend to
  kill the direct `acompletion` (llm_evaluator.py:585). (c) Fold the
  `gpt-5*` temperature drop (client.py:130) and qwen3 think-disable (L142)
  into backend-specific subclasses.

---

### 3.2 `BaseStrategy`  →  subtask 008

- **Purpose.** The search/selection policy: *which node to run or expand next*,
  independent of I/O, prompt text, and persistence.
- **Current implementation candidates.** `ari/orchestrator/bfts.py::BFTS` (845
  LOC). Its genuine strategy surface is `select_next_node` (L418),
  `select_best_to_expand` (L520), `should_prune` (L498), `expand` (L577), the
  deterministic fallbacks `_fallback_score`/`_select_fallback` (L322–369), and
  diversity accounting `record_run`/`diversity_bonus`/`expansion_count`
  (L267–319).
- **Methods.** `select_next_node(tree) -> Node | None`;
  `select_best_to_expand(tree) -> Node | None`; `should_prune(node) -> bool`;
  `expand(node, context) -> list[Node]`; `record_run(node)`. LLM-driven ranking
  moves behind the injected `BaseModelBackend` + `BasePromptBuilder`, leaving
  `BaseStrategy` as **pure ranking/selection** (the "BFTSStrategy purity"
  opportunity from the orchestration findings).
- **State ownership.** Owns only search bookkeeping (diversity counters, prune
  cutoffs). It must **stop** owning: filesystem reads of `node_report.json`
  (`_resolve_pm_and_run_id` L43, `_get_node_report` L372, `_load_sibling_node_reports`
  L406) → those move to `BaseTraceStore`/a node-report repository (§3.10); and
  prompt/context serialization (`expand` L604–760) → `BasePromptBuilder` (§3.4).
- **Expected concrete implementations.** `BFTSStrategy` (ADAPT of current `BFTS`),
  plus the already-present deterministic fallback path exposed as
  `GreedyFallbackStrategy` for tests. One substitution axis (search policy) →
  ABC is justified; `Base` is an ABC here.
- **Composition relationships.** Holds `BaseModelBackend`, `BasePromptBuilder`,
  a node-report store, and `BaseMemoryClient` (`select_next_node` calls
  `memory.search`, bfts.py:446). Driven by `BaseWorkflowDriver`/the BFTS loop
  (`cli/bfts_loop.py::_run_loop`, L85–837), constructed in `ExecutionServices`
  (today `core.py:148 BFTS(cfg.bfts, bfts_llm)`).
- **Compatibility concerns.** No external contract — `BFTS` is internal
  (only constructed by `build_runtime`, L102). The one caller boundary is
  `_run_loop`; keep method names stable so that loop needs no rewrite.
- **Migration subtasks.** (a) Extract `BFTSPromptBuilder` (§3.4). (b) Inject the
  node-report store, removing `BFTS ↔ ari.paths`/filesystem coupling. (c) Land
  the ABC and make `BFTS` its first subclass.

---

### 3.3 `BaseAgentLoop`  →  subtask 008

- **Purpose.** A generic ReAct executor for one node: Thought→Action→Observation
  over MCP tools until a terminal signal, *with no domain-specific knowledge*.
- **Current implementation candidates.** **Two** implementations exist and must
  be merged: `ari/agent/loop.py::AgentLoop.run` (L459–1630, one ~1170-line
  method, despite its "no domain-specific knowledge" docstring) and the cleaner,
  generic `ari/agent/react_driver.py` (16 KB, ~442 LOC) already used by pipeline
  ReAct stages (`pipeline/stage_runner.py:143`). Partial extractions already
  landed: `tool_manager.py`, `guidance.py`, `message_utils.py`,
  `metric_contract.py`.
- **Methods.** `run(node, goal) -> NodeResult`; internally delegates to
  `PromptAssembler` (loop.py L489–621), a `MessageWindow` (the existing
  `_build_safe_window` L725–805 + `repair_tool_message_order` L113–155), a
  `ToolResultRouter` (the giant `if r["name"] == ...` dispatch L950–1318), and a
  `NodeEvaluationPersister` (dedupes the 3 `evaluate_sync` blocks at L1454/1532/
  1600 and the 5 near-identical "RESULT SUMMARY" `add_memory` blocks at
  L921/960/1480/1549/1567/1615).
- **State ownership.** Owns the running message window and step counter only.
  It must **stop** owning: file writes (`idea.json` L1015, reads of
  `metric_contract.json`/`platform_capabilities.json` L228–290, `experiment.md`
  L1051) → stores; memory writes → `BaseMemoryClient`; trace appends
  (`node.trace_log.append` L899, `_notify_progress`→tree.json flush L439–457) →
  `BaseTraceStore`.
- **Expected concrete implementations.** One canonical `ReActAgentLoop`
  (MERGE of `AgentLoop` + `react_driver`). Because the merged result has real
  shared machinery, `Base` here is a thin **ABC** with the window/step scaffold
  and an abstract `dispatch_tool`.
- **Composition relationships.** Holds `BaseModelBackend`, `BaseMemoryClient`,
  `BaseSkillAdapter` (MCP), `BaseEvaluator`, `BasePromptBuilder`,
  `BaseTraceStore`. Constructed in `ExecutionServices` (`core.py:219`).
- **Compatibility concerns.** No public symbol, but the **cross-layer reaches**
  `ari_skill_memory.backends` (L1047) and `ari.pipeline._extract_plan_sections`
  (L1061, L1118) violate layering; route them through `BaseSkillAdapter`/domain
  services rather than importing sideways. Behaviour (terminal-JSON protocol,
  tool-call shape) must be byte-stable so live runs reproduce.
- **Migration subtasks.** (a) Decompose `run` into the four collaborators above.
  (b) Reconcile the two ReAct loops into one. (c) Remove the two sideways
  imports.

---

### 3.4 `BasePromptBuilder`  →  subtask 008

- **Purpose.** Assemble the *context/message payload* for a model call from
  structured inputs, separately from the `.md` **template** (which
  `PromptLoader` already externalises). Today templates are external but the
  heavy serialization that fills them is inline.
- **Current implementation candidates.** *Does not exist as a class.* The logic
  is inline: BFTS `expand` context serialization (`bfts.py` L604–760:
  sci_note/depth_note/budget_note + sibling/ancestor/existing-children/diversity
  blocks) and candidate descriptions (L451–470, L537–550); `AgentLoop` system
  prompt + user_content assembly (`loop.py` L489–621) and module-level
  `build_working_context_messages` (L164–355).
- **Methods.** `build(context) -> list[LLMMessage]` (or `-> str` for a single
  block), one concrete builder per prompt family. Consumes `PromptLoader.load`
  for the template and fills it.
- **State ownership.** Stateless; pure function of its input context object. No
  filesystem, no LLM.
- **Expected concrete implementations.** `BFTSPromptBuilder` (expand/select
  contexts), `AgentPromptBuilder` (system + working-context), and a
  `PipelinePromptBuilder` for stage prompts. This is where the "BFTS as pure
  ranking" separation is realised.
- **Composition relationships.** Injected into `BaseStrategy` and
  `BaseAgentLoop`; itself composes `PromptLoader` (§3.23) resolved via
  `PromptRegistry` (§3.22).
- **Compatibility concerns.** Prompt text is **reproducibility-load-bearing**;
  extraction must be behaviour-preserving (`PromptLoader.load_versioned` already
  hashes for pinning, `_loader.py:45`). No external contract.
- **Migration subtasks.** (a) Lift the two BFTS serialization regions into
  `BFTSPromptBuilder`. (b) Lift `build_working_context_messages` into
  `AgentPromptBuilder`. (c) Add golden-text tests before moving a line.

---

### 3.5 `BaseEvaluator`  →  subtask 009

- **Purpose.** Turn a finished node's artifacts into `{score, reason,
  has_real_data, metrics, ...}` behind a swappable strategy.
- **Current implementation candidates.** The **Protocol already exists**:
  `ari/protocols/evaluator.py::Evaluator` (L18, `@runtime_checkable`, single
  async `evaluate(...)`). The sole concrete impl is
  `ari/evaluator/llm_evaluator.py::LLMEvaluator` (L240), which satisfies it
  structurally. Dynamic axes live in `evaluator/dynamic_axes.py`
  (`build_axes_for_run` L449; `GENERIC_AXES` now 6 axes incl.
  `claim_implementation_alignment`, L124).
- **Methods.** `async evaluate(goal, artifacts, summary, node_id=None,
  node_label=None) -> dict` — keep the existing signature verbatim.
- **State ownership.** Owns axis configuration (mode legacy/dynamic/custom,
  `config/__init__.py:227`) and the composite selection; does **not** own the
  model backend (today it wrongly owns a direct litellm path).
- **Expected concrete implementations.** `LLMEvaluator` (KEEP, satisfy Protocol
  formally), a regex/table `DeterministicEvaluator` for tests (the Protocol
  docstring explicitly anticipates this, evaluator.py:22–27). `Base` here stays
  a **Protocol** (structural), per the existing choice.
- **Composition relationships.** Injected into `BaseAgentLoop` and
  `BaseStrategy`; holds a `BaseModelBackend` (once the direct call is removed)
  and a `BaseCompositeEvaluator` (§3.6).
- **Compatibility concerns.** No `ari.public` surface, but `EvaluatorConfig`
  (`ari.public.config_schema`) *is* public — axis-mode/composite fields must
  keep their meaning. The `metrics["_scientific_score"]` key
  (llm_evaluator.py:662, returned L709) is consumed downstream; keep it.
- **Migration subtasks.** (a) Make `LLMEvaluator` explicitly Protocol-typed at
  call sites. (b) Inject `BaseModelBackend`, deleting the direct
  `litellm.acompletion` (L585). (c) Add retry/timeout via the backend (the
  hardcoded `future.result(timeout=120)` at L535 moves into backend config).

---

### 3.6 `BaseCompositeEvaluator`  →  subtask 009

- **Purpose.** Combine per-axis scores in `[0,1]` into a single composite score
  under a named formula.
- **Current implementation candidates.** *No class hierarchy* — composites are
  plain **functions** in a dict registry `_COMPOSITES`
  (`llm_evaluator.py:165`): `weighted_harmonic_mean` (L75, default),
  `weighted_arithmetic_mean` (L102), `weighted_min` (L122),
  `weighted_geometric_mean` (L141). Selected by ctor arg validated against the
  registry (L280–286).
- **Methods.** `compose(axis_scores: dict[str,float], weights: dict[str,float])
  -> float`; `name -> str`.
- **State ownership.** Stateless; pure math.
- **Expected concrete implementations.** Four thin classes wrapping the existing
  functions (`HarmonicMeanComposite`, `ArithmeticMeanComposite`,
  `MinComposite`, `GeometricMeanComposite`), registered in a `BaseRegistry`
  (§3.14) rather than a bare dict. This is the *closest existing thing to a real
  registry pattern* and the natural first `BaseRegistry` adopter.
- **Composition relationships.** Held by `BaseEvaluator`; keys registered
  through `BaseRegistry`.
- **Compatibility concerns.** Composite key strings
  (`harmonic_mean|arithmetic_mean|weighted_min|geometric_mean`) must stay in
  sync with `EvaluatorConfig.composite` **Literal** (`config/__init__.py:212`),
  which is public via `config_schema`. Renaming a key is a public break — do not.
- **Migration subtasks.** (a) Wrap each function as a class implementing the
  interface. (b) Register under `BaseRegistry` keyed by the existing strings.
  (c) Keep the `_COMPOSITES` dict as a thin compatibility alias until callers
  move.

---

### 3.7 `BaseMemoryClient`  →  subtask 012

- **Purpose.** Add / search / retrieve agent memory behind one interface.
- **Current implementation candidates.** **Already exists twice, divergently
  (MERGE target).** Core `ari/memory/client.py::MemoryClient` **ABC** (L8:
  `add/search/get_all`) with impls `LettaMemoryClient` (`letta_client.py:22`,
  which is the **first core→skill import**, delegating to
  `ari_skill_memory.backends.get_backend`, L27), `FileMemoryClient`
  (`file_client.py:16`), `LocalMemoryClient` (`local_client.py:8`). Separately,
  the skill defines a **richer** `MemoryBackend` ABC
  (`ari-skill-memory/src/ari_skill_memory/backends/base.py:8`:
  `add_memory/search_memory/get_node_memory/... + react_* + bulk_import`). The
  two ABCs share no types.
- **Methods.** Core-facing: `add(content, metadata=None)`,
  `search(query, limit=10) -> list[dict]`, `get_all() -> list[dict]` (keep the
  three-method core contract; the richer skill surface stays behind the MCP
  boundary).
- **State ownership.** Owns the memory connection/backing store handle only.
- **Expected concrete implementations.** `LettaMemoryClient` (KEEP as the
  primary), `FileMemoryClient`/`LocalMemoryClient` (MOVE_TO_LEGACY — the file
  client is retained mainly as a v0.5→v0.6 migration source per
  `core.py:98–100`). One substitution axis → ABC is justified; **keep the ABC**
  but resolve the "protocol vs ABC" naming inconsistency (`memory/__init__.py:3`
  calls the ABC a "protocol").
- **Composition relationships.** Injected into `BaseAgentLoop` and
  `BaseStrategy`; constructed in `ExecutionServices` (today hardcoded
  `LettaMemoryClient(...)` at `core.py:130`). Selection should move behind
  `BaseRegistry` keyed by `ARI_MEMORY_BACKEND` (set at `config/__init__.py:316`
  but currently consumed by **no** dispatcher).
- **Compatibility concerns.** The **core→skill import** (`letta_client.py:27`)
  and the direct reach from `agent/loop.py:1047` are the layering hazards; both
  route through `BaseSkillAdapter` (§3.13) or a stable
  `ari_skill_memory.backends` facade. Canonical store path
  `{ARI_CHECKPOINT_DIR}/memory_store.jsonl` and its JSONL format are a contract.
  Note the observed `FileMemoryClient._load` reads the whole file as a single
  JSON array (`file_client.py:44`) while the canonical path is line-wise JSONL —
  a **REVIEW_REQUIRED** format mismatch to resolve during the merge.
- **Migration subtasks.** (a) Reconcile the two ABCs (shared DTOs). (b) Move
  client selection to `BaseRegistry`. (c) Wire `ARI_MEMORY_BACKEND` to the
  dispatcher.

---

### 3.8 `BaseArtifactStore`  →  subtask 011

- **Purpose.** Read/write **experiment artefacts** (papers, figures, science
  data, EAR bundles) by logical name, hiding the flat checkpoint filesystem.
- **Current implementation candidates.** *No store class exists.* Behaviour is
  scattered: the pipeline's type-sniffing output writer
  (`pipeline/orchestrator.py` L757–826: `.tex`→`result["latex"]`, `.pdf`→
  copy-if-distinct, `generate_figures` manifest branch); hardwired filenames
  everywhere (`science_data.json`, `full_paper.tex`, `fig_*.pdf/png/svg`,
  `ear_published/`, `manifest.lock`); `ari/clone/` (digest-verified atomic
  extract, `_safe_extract_tar:84`) and `ari/publish/` (staged→promote) are the
  cleanest existing artefact movers. HTTP artefact registry
  `ari/registry/` (`FilesystemStorage`, content-addressed sha256[:16]) is a
  *remote* artefact store.
- **Methods.** `put(name, data|path)`, `get(name) -> path`, `exists(name)`,
  `list(kind)`. Absorbs the pipeline's `persist_outputs` type-sniffing.
- **State ownership.** Owns the mapping from logical artefact name → on-disk
  location; delegates path derivation to `RuntimePathResolver`.
- **Expected concrete implementations.** `CheckpointArtifactStore` (local flat
  layout, KEEP semantics), `RegistryArtifactStore` (wraps `ari/registry/` +
  `ari/publish` backends). Because layout may vary, `Base` is an **ABC**.
- **Composition relationships.** Held by `BasePipelineStage.persist_outputs`,
  `BaseWorkflowDriver`, and dashboard read paths; composes
  `RuntimePathResolver`.
- **Compatibility concerns.** The **flat checkpoint filenames are an on-disk
  contract** (`PathManager.META_FILES`, `paths.py:51–76`; workflow.yaml
  `{{checkpoint_dir}}/...` templating for ~40 paths). Any future
  `runs/<id>/{artifacts,...}` consolidation must ship behind a back-compat
  reader; **no path renames in this phase**. `.gitignore` already ignores all
  runtime dirs (`checkpoints/`, `workspace/`), so there is **no git-tracking
  migration cost** — only on-disk back-compat.
- **Migration subtasks.** (a) Introduce the store and route the pipeline output
  writer through `put()`. (b) Collapse hardwired filenames into a name→path
  table owned by `RuntimePathResolver`. (c) Keep `clone`/`publish`/`registry`
  as backends.

---

### 3.9 `BaseCheckpointStore`  →  subtask 011

- **Purpose.** Read/write the run's tree/results/idea JSON with the exact
  current layout and throttling.
- **Current implementation candidates.** `ari/checkpoint.py` (198 lines) —
  **module functions, not a class**: `save/load_tree_json`,
  `save_nodes_tree_json`, `save_results_json`, `load_nodes_tree()` (3-tier
  precedence `tree.json → nodes_tree.json → newest non-empty node_*/tree.json`,
  L86–137), throttled `save_tree_incremental()` (1.0 s, thread-locked,
  L150–183).
- **Methods.** `save_tree(tree)`, `load_tree()`, `save_results(results)`,
  `save_tree_incremental(tree)`, `load_nodes_tree()` — one-to-one with the
  existing functions.
- **State ownership.** Owns the checkpoint directory handle + the incremental
  writer's lock/monotonic-clock bookkeeping (currently module-global in
  `checkpoint.py`).
- **Expected concrete implementations.** `JsonCheckpointStore` (KEEP behaviour
  exactly — file names, key order, `indent=2, ensure_ascii=False` all preserved
  per the module docstring L14–16). Single implementation → this can be a
  **Protocol** with one concrete class; ABC not required.
- **Composition relationships.** Held by `BaseWorkflowDriver`, `BaseAgentLoop`
  (tree flush), and dashboard readers (`viz/api_state.py` is the current
  reader). Constructed in `ExecutionServices`.
- **Compatibility concerns.** **Checkpoint format is a hard external contract.**
  The `Node.to_dict()` formatting deliberately stays in caller code so the store
  is domain-agnostic (docstring L23–25) — preserve that boundary.
- **Migration subtasks.** (a) Wrap the module functions in
  `JsonCheckpointStore` with the module-global lock moved to an instance field.
  (b) Point `viz/api_state.py` at the store to remove its duplicated reader.

---

### 3.10 `BaseTraceStore`  →  subtask 011

- **Purpose.** Append and read execution traces, node reports, and structured
  access logs, decoupled from the executors that produce them.
- **Current implementation candidates.** *No unified store.* Producers are
  scattered: `node.trace_log.append`/`node.artifacts.append`
  (`agent/loop.py` L899–912); node-report reads in BFTS
  (`_get_node_report` L372, `_load_sibling_node_reports` L406) and writes in the
  loop (`cli/bfts_loop.py::write_node_report` L663–673); JSONL access logs
  `viz_access.jsonl` / `memory_access.jsonl` / `cost_trace.jsonl` written from
  `orchestrator/node_report/builder.py`, `viz/routes.py`, `viz/api_memory.py`,
  `viz/node_work_api.py`, `memory_cli.py`. Schema `node_report.schema.json`
  (JSON Schema draft-07) exists but has **no production importer**
  (`ari.schemas.load()` is used only by a test — DELETE_CANDIDATE for the
  loader API, not the schema).
- **Methods.** `append_trace(node_id, entry)`, `read_trace(node_id)`,
  `write_node_report(node_id, report)`, `read_node_report(node_id)`,
  `read_sibling_reports(node_id)`.
- **State ownership.** Owns the trace/report file locations and append cursors.
- **Expected concrete implementations.** `JsonlTraceStore` (local). Single
  implementation likely → **Protocol** with one class; a second in-memory
  variant helps tests.
- **Composition relationships.** Injected into `BaseAgentLoop` (removes trace
  file I/O from the loop) and `BaseStrategy` (removes the BFTS↔filesystem
  coupling, the "NodeReport repository" opportunity). Read by
  `DashboardViewService` (§3.20).
- **Compatibility concerns.** Access-log file names are in `META_FILES` and are
  read by the dashboard — keep names/format. Validate against
  `node_report.schema.json` here (finally giving that schema a runtime user).
- **Migration subtasks.** (a) Introduce the store; route BFTS node-report reads
  and the loop's trace appends through it. (b) Consolidate the ~5 ad-hoc JSONL
  writers behind `append_trace`.

---

### 3.11 `BasePipelineStage`  →  subtask 010

- **Purpose.** Encapsulate one post-BFTS pipeline step as an object with a
  uniform lifecycle, replacing the dict-driven inline handling.
- **Current implementation candidates.** *No stage class exists* — a "stage" is
  a plain `dict` parsed from the `pipeline:` list in
  `ari-core/config/workflow.yaml` (629 LOC, ~30 stages) by
  `pipeline/yaml_loader.py::load_pipeline` (L29). Per-stage logic is hand-rolled
  inside `run_pipeline` (`orchestrator.py` L548–911). Two dispatch modes:
  subprocess-MCP (`stage_runner.py::_run_stage_subprocess` L331, builds a script
  by string concatenation) and ReAct (`_run_react_stage` L51) — the ReAct path
  is **confirmed dormant in the default config** (`grep -c 'react:'
  config/workflow.yaml == 0`).
- **Methods.** `resolve_inputs(ctx)`, `should_skip(depends_on, skip_if_exists,
  disabled)`, `run(ctx)`, `persist_outputs(result)`, `evaluate_loopback(result)`
  — the five responsibilities currently smeared across `orchestrator.py`
  L561–901.
- **State ownership.** Owns its own config slice + resolved inputs; shared run
  state lives in a `StageContext` value object (kills the manual `tpl_vars` /
  `stage_outputs` dict threading).
- **Expected concrete implementations.** `SubprocessMCPStage`, `ReActStage`
  (replacing the `if stage_cfg.get("react")` fork at `orchestrator.py:691`).
  Two real behavioural variants → **ABC** with an abstract `run`.
- **Composition relationships.** Created and sequenced by `BaseWorkflowDriver`;
  uses `BaseSkillAdapter` (MCP dispatch), `BaseArtifactStore` (`persist_outputs`
  absorbs the type-sniffing writer, orchestrator L757–826), and
  `BasePromptBuilder` (ReAct stages).
- **Compatibility concerns.** `workflow.yaml` **stage schema is a config
  contract** (per-checkpoint copies exist, in `META_FILES`); the stage classes
  must read the *same* keys (`depends_on`, `skip_if_exists`, `loop_back_to`,
  `react`, `inputs`, `params`). Keep the regex `{{var}}` templating
  (`yaml_loader.py:84`) — not Jinja — to avoid changing resolution semantics.
- **Migration subtasks.** (a) Introduce `StageContext`. (b) Land the two stage
  classes wrapping the existing dispatch functions. (c) Move the output writer
  into `persist_outputs`.

---

### 3.12 `BaseWorkflowDriver`  →  subtask 010

- **Purpose.** Own the stage loop, loop-back cursor, pre-flight, and run state —
  the *one* place a pipeline is driven.
- **Current implementation candidates.** `pipeline/orchestrator.py::run_pipeline`
  (the 913-LOC god function, L548–911) **and its duplicate** in the dashboard
  worker `viz/api_paperbench_worker.py::_run_pipeline` (L168, threaded L313).
  Pre-flight lives partly in `orchestrator.py` L505–537 (BFTS sanity gate,
  `has_real_data`, `ARI_FORCE_PAPER` override) and `core.py::generate_paper_section`
  (L235–283).
- **Methods.** `run(context) -> RunResult`; private `_advance_cursor` (handles
  `loop_back_to` rewind + VLM-feedback injection, orchestrator L831–901),
  `_preflight` (cost-tracker init, `nodes_tree.json` load, verified_context,
  sanity gate).
- **State ownership.** Owns `_stage_idx`, the `StageContext` (formerly
  `tpl_vars`/`stage_outputs`), and the loop-back cursor. A single
  `WorkflowLocator` collapses the 3+ duplicated `config/workflow.yaml` discovery
  sites (`core.py:252–259`, `orchestrator.py:328–336`, `cli/lineage.py:57–60`).
- **Expected concrete implementations.** `PipelineWorkflowDriver` (MERGE of
  `run_pipeline` + the dashboard `_run_pipeline`). Effectively one implementation
  → **Protocol** + one class; a `DryRunDriver` aids tests.
- **Composition relationships.** Holds a `list[BasePipelineStage]`,
  `BaseCheckpointStore`, `BaseArtifactStore`, `BaseCostTracker`,
  `BaseSkillAdapter`, and `RuntimePathResolver`; entered from `cli/run.py` and
  the dashboard worker.
- **Compatibility concerns.** Entry point `core.py:235 generate_paper_section`
  is **internal** (CLI-only) but must keep working; the dashboard worker path
  feeds the **dashboard API** so its externally-visible progress/state writes
  must be preserved. The core→viz import in `cli/lineage.py:151` is removed by
  routing lineage launch through an injected hook, not a sideways import.
- **Migration subtasks.** (a) Extract `WorkflowLocator` + `StageContext`.
  (b) Land `PipelineWorkflowDriver`; make the dashboard worker call it.
  (c) Move pre-flight out of `core.py`.

---

### 3.13 `BaseSkillAdapter`  →  subtask 012

- **Purpose.** A typed facade over MCP skill invocation, hiding transport, the
  two divergent server idioms, and the flat tool namespace.
- **Current implementation candidates.** `ari/mcp/client.py::MCPClient` (L256)
  and `_SkillConnection` (L93); `list_tools()` (L297), `call_tool()` (L336,
  returns `{"result"|"error"}`), `_tool_registry: dict[tool_name→skill]` (L283,
  where **cross-skill name collisions silently clobber, last-skill-wins**,
  L325), `to_claude_mcp_config()` (emits `mcp__<skill>__<tool>`). Servers use
  **two idioms**: FastMCP (10 skills) vs low-level `mcp.server.Server` (4:
  coding, evaluator, hpc, orchestrator) with different return shapes.
- **Methods.** `list_tools(phase=None)`, `call_tool(name, args, timeout)`,
  `to_claude_mcp_config()` — keep the existing surface; add an optional
  fully-qualified `skill.tool` addressing to fix collisions without breaking
  bare names.
- **State ownership.** Owns per-skill connection pool, the tool registry, and
  timeout tiers (`DEFAULT_TOOL_TIMEOUT=300`, `SLOW=3600`, `VERY_SLOW=13 h`).
- **Expected concrete implementations.** `MCPSkillAdapter` (KEEP `MCPClient`
  behaviour), an `InProcessSkillAdapter` for `ari_skill_memory` (so core stops
  importing `ari_skill_memory.backends` directly at `agent/loop.py:1047`), and a
  `StubSkillAdapter` for tests. One substitution axis → **ABC**.
- **Composition relationships.** Injected into `BaseAgentLoop`,
  `BasePipelineStage`, and `BaseStrategy`; constructed in `ExecutionServices`
  (today `MCPClient(...)` at `core.py:140`).
- **Compatibility concerns.** **MCP tool names, `inputSchema`, the
  `{"result"|"error"}` envelope, and `mcp__<skill>__<tool>` naming are hard
  contracts.** The bare-name flat namespace must keep resolving; collision-fix
  is additive. The 14 servers' contracts are frozen — the adapter changes only
  the *client* side.
- **Migration subtasks.** (a) Extract the ABC; make `MCPClient` its subclass.
  (b) Add `InProcessSkillAdapter` and route the loop's direct
  `ari_skill_memory` import through it. (c) Add optional qualified addressing to
  close the silent-collision bug (**REVIEW_REQUIRED**: whether to warn or error
  on collision).

---

### 3.14 `BaseRegistry`  →  subtask 013

- **Purpose.** One import-driven, string-keyed factory pattern to replace the
  scattered ad-hoc dispatchers — DI, not entry-points.
- **Current implementation candidates.** **Naming trap:** `ari/registry/` (5
  files, 366 LOC) is an **HTTP artefact registry** (FastAPI, `build_app` at
  `app.py:22`), **not** a DI container, and it is wired into the CLI as `ari
  registry` (`cli/__init__.py:97`). The real string→impl dispatchers are three:
  publish backends `ari/publish/__init__.py::_load_backend` (L198, if/elif over
  `ari-registry|local-tarball|zenodo|gh` with lazy import of
  `publish/backends/*.py` — **DEAD-CODE WARNING: those four modules are
  referenced only by string and must be treated as live**); evaluator composites
  `_COMPOSITES` (`llm_evaluator.py:165`); and LLM routing
  `resolve_litellm_model` (`llm/routing.py:37`).
- **Methods.** `register(key, factory)`, `create(key, *args) -> T`, `keys()`.
- **State ownership.** Owns the key→factory table; instances are owned by their
  callers.
- **Expected concrete implementations.** A single generic
  `Registry[T]` used to back: composites (§3.6), memory-client selection (§3.7),
  and publish backends. **Must be named to avoid collision with the existing
  `ari/registry/` HTTP module** (e.g. `ari.factories` / `ari.di`, decided in
  subtask 013). No `importlib.metadata` entry-points exist
  (`pyproject.toml` declares only `ari = ari.cli:app`) so the registry is
  **import-driven, in-tree only**.
- **Composition relationships.** Consulted by `ExecutionServices` (§3.19) to
  build backends by config key; the natural first adopter is
  `BaseCompositeEvaluator`.
- **Compatibility concerns.** Publish backend names duplicate an enum in
  `ari/schemas/publish.schema.json:51` — keep in sync. `ari registry` CLI +
  the HTTP endpoints (`/artifact`, `/promote`, `/healthz`, `/version`) are a
  **contract** and are unrelated to this DI registry; the doc must not conflate
  them.
- **Migration subtasks.** (a) Introduce `Registry[T]` under a non-colliding
  name. (b) Migrate `_COMPOSITES` first, then `_load_backend`, then memory
  selection. (c) Leave `resolve_litellm_model` as-is initially (its keys are a
  provider-routing concern, not a factory) — **REVIEW_REQUIRED**.

---

### 3.15 `BaseCostTracker`  →  subtask 007

- **Purpose.** Record per-call token/cost/latency and persist a run cost trace,
  behind an interface (today it is a process-global monkeypatch).
- **Current implementation candidates.** `ari/cost_tracker.py` (448 LOC):
  `CostTracker` class (L77, **concrete, no ABC**) + module-global singleton
  `_tracker` + free functions `init/init_from_env/bootstrap_skill/record/get`
  (L190–353); `CallRecord` dataclass (L58, carries
  `component/op/backend/embedding_tokens/latency_ms`). Capture is a **global
  litellm monkeypatch** `_install_litellm_metadata_injector` (L288, replaces
  `litellm.completion`/`acompletion` process-wide) + `success_callback`
  `_litellm_success_handler` (L406). Public re-export is a **star-import**
  (`public/cost_tracker.py:7 from ari.cost_tracker import *`).
- **Methods.** `record(call: CallRecord)`, `get() -> summary`,
  `bootstrap_skill(...)`, `init_from_env()`; the module free functions become
  thin delegates to the injected instance.
- **State ownership.** Owns `_records`, the trace/summary file handles
  (`cost_trace.jsonl`, `cost_summary.json`), and pricing loaded from
  `ari/configs/model_prices.yaml` (`_load_pricing:17`).
- **Expected concrete implementations.** `LiteLLMCostTracker` (KEEP behaviour;
  replace the process-wide monkeypatch with an explicit callback registered by
  `BaseModelBackend`). Single implementation → **Protocol** + one class.
- **Composition relationships.** Injected into `BaseModelBackend` (the capture
  point) and `BaseWorkflowDriver` (pre-flight init); replaces the global
  singleton with an `ExecutionServices`-owned instance.
- **Compatibility concerns.** `ari.public.cost_tracker` re-exports
  `bootstrap_skill/record/init_from_env` by **star-import** — these names are a
  **public contract** and must remain module-level callables. `cost_trace.jsonl`
  format is an on-disk contract read by the dashboard. Known defects to fix
  behind the interface (not behaviour-preserve): `latency_ms` never populated
  though `start/end` are available (L406); `_reload_existing` drops the additive
  fields on restore (L91).
- **Migration subtasks.** (a) Define the Protocol; keep free functions as
  delegates. (b) Replace the global monkeypatch with a backend-registered
  callback. (c) Fix `latency_ms` / `_reload_existing` (**REVIEW_REQUIRED**:
  format-compatible?).

---

### 3.16 `BaseLogger`  →  subtask 007

- **Purpose.** A thin, injectable logging seam so components don't reach for
  module-global `logging.getLogger` and ad-hoc JSONL writers.
- **Current implementation candidates.** *No logger class exists.*
  `logging.getLogger(__name__)` is used across `checkpoint.py`, `core.py`,
  `cli/*`, `pipeline/*`, etc.; `LoggingConfig` is a Pydantic model
  (`config/__init__.py:170`); the run log path is `PathManager.log_file()` →
  `ari.log` (`paths.py:157`); structured JSONL access logs
  (`viz_access.jsonl`, `memory_access.jsonl`, `cost_trace.jsonl`) are written
  ad-hoc from ≥6 modules.
- **Methods.** Standard `debug/info/warning/error`, plus a structured
  `event(kind, **fields)` for the JSONL access logs.
- **State ownership.** Owns the run log handle; structured-event routing shares
  `RuntimePathResolver` for destinations.
- **Expected concrete implementations.** `StdLogger` (wraps stdlib `logging`,
  KEEP) and a `StructuredLogger` for the access-log JSONL. Because most code can
  keep using stdlib `logging`, this is the **lowest-priority / REVIEW_REQUIRED**
  abstraction — introduce only where injection removes a real coupling (e.g.
  the loop's trace writes), otherwise leave module loggers alone.
- **Composition relationships.** Optionally injected into executors and stores;
  configured from `LoggingConfig`.
- **Compatibility concerns.** `ari.log` filename and the access-log filenames
  are in `META_FILES` / read by the dashboard — preserve. No public API.
- **Migration subtasks.** (a) Decide scope (**REVIEW_REQUIRED** — may stay
  mostly stdlib). (b) Route structured access-log writes through
  `StructuredLogger` to remove the ≥6 duplicated writers.

---

### 3.17 `RuntimePathResolver`  →  subtask 011

- **Purpose.** The single source of truth for every on-disk location and for
  config/workflow discovery.
- **Current implementation candidates.** `ari/paths.py::PathManager` (304 lines;
  re-exported verbatim by `public/paths.py`, 6 lines) — derives
  `checkpoints_root/experiments_root/staging_root/paper_registry_root`,
  `checkpoint_dir(run_id)`, `node_work_dir(run_id, node_id)`,
  `new_staging_dir()`, `log_file()`; env pinning via `ARI_CHECKPOINT_DIR`
  (`from_env`, `from_checkpoint_dir`, L238–274). Config discovery is a **separate**
  module `ari/config/finder.py` (`package_config_root()` L28, `find_workflow_yaml`
  four-tier search L60–100). The `WorkflowLocator` from §3.12 folds into here.
- **Methods.** All current `PathManager` properties/methods **verbatim**, plus
  `find_workflow_yaml(...)` / `package_config_root()` absorbed from `finder.py`,
  plus the logical artefact-name→path table used by `BaseArtifactStore`.
- **State ownership.** Owns `workspace_root` and every derived path;
  `META_FILES`/`META_EXTENSIONS`/`_META_PATTERNS` (paths.py:51–85) stay here.
- **Expected concrete implementations.** `PathManager` (KEEP; likely the *only*
  implementation → **concrete class**, no ABC, tests pass a custom
  `workspace_root` as they do today).
- **Composition relationships.** Injected into every store, driver, and executor
  that touches disk. Constructed once in `ExecutionServices`.
- **Compatibility concerns.** `ari.public.paths.PathManager` is a **public
  contract** — name, constructor `PathManager(workspace_root=".")`, and derived
  paths must not change. Note the **workspace-root ambiguity**:
  `config/__init__.py:588` defaults to `{repo}/workspace/checkpoints/{run_id}`
  while shipped `config/default.yaml:14/39` still says `./checkpoints/{run_id}`
  — resolve consistently but preserve both readable (**REVIEW_REQUIRED**). The
  root `checkpoints/` dir appears purely legacy (empty, MOVE_TO_LEGACY once
  confirmed nothing writes it).
- **Migration subtasks.** (a) Merge `finder.py` discovery into the resolver
  (one workflow-locator). (b) Add the artefact-name table. (c) Keep
  `public/paths.py` re-export byte-stable.

---

### 3.18 `ExecutionContext`  →  subtask 013

- **Purpose.** An immutable per-run value object carrying identity + config +
  resolved paths, threaded explicitly instead of via env vars and module
  globals.
- **Current implementation candidates.** *Does not exist as a type.* The state
  is currently spread across `ARI_CHECKPOINT_DIR` env pinning
  (`paths.py:238`), `build_runtime`'s parameters (`cfg, experiment_text,
  checkpoint_dir`, `core.py:83`), the pipeline's manually-threaded `tpl_vars`
  dict, and — for the dashboard — the **module-global mutable state** in
  `viz/state.py` (`_checkpoint_dir`, `_launch_config`, `_running_procs`, ...,
  L18–30).
- **Methods.** Read-only accessors: `run_id`, `checkpoint_dir`, `config`
  (`ARIConfig`), `paths` (`RuntimePathResolver`), `experiment_text`.
- **State ownership.** Immutable snapshot of run identity/config; owns nothing
  mutable. It is the *input* to `ExecutionServices`.
- **Expected concrete implementations.** A single frozen `dataclass`
  `ExecutionContext` (concrete, no hierarchy).
- **Composition relationships.** Constructed at CLI entry (`cli/run.py`
  L322–323 generates the `run_id`) and at the dashboard launch; passed to
  `ExecutionServices.build(...)`. Replaces reliance on env-var hand-off between
  `cli/*` and the runtime.
- **Compatibility concerns.** `ARI_CHECKPOINT_DIR` hand-off is a **contract**
  with the GUI and skills (skills read their own phase env) — `ExecutionContext`
  wraps it but must keep setting/reading it for subprocess skills. The
  `run_id` format `{strftime}_{slug}` (run.py:322) is user-visible in directory
  names — preserve.
- **Migration subtasks.** (a) Define the dataclass. (b) Thread it through
  `build_runtime`/drivers. (c) Leave `viz/state.py` globals in place initially
  behind a context adapter (**REVIEW_REQUIRED** — dashboard globals are a large
  separate cleanup).

---

### 3.19 `ExecutionServices`  →  subtask 013

- **Purpose.** The **composition root** — the one object that builds and holds
  every wired service for a run, replacing the procedural `build_runtime`.
- **Current implementation candidates.** `ari/core.py::build_runtime` (L83–222)
  is the as-built composition root: it constructs per-phase `LLMClient`s
  (`_phase_llm`, L119–125), `LettaMemoryClient` (L130), `MCPClient` (L140),
  `BFTS` (L148), `LLMEvaluator` (L195), and `AgentLoop` (L219), then **returns a
  6-tuple** `(llm, memory, mcp, bfts, agent, metric_spec)` (L222). It is also
  polluted with rubric YAML loading (`_load_rubric_dict_for_axes`) and
  `_make_metric_spec` (L151).
- **Methods.** `build(context: ExecutionContext) -> ExecutionServices`;
  properties `model_backend`, `memory`, `skills`, `strategy`, `evaluator`,
  `agent_loop`, `cost_tracker`, `checkpoint_store`, `artifact_store`,
  `trace_store`, `prompt_registry`, `paths`.
- **State ownership.** Owns the constructed service instances for the run
  lifetime (what the 6-tuple loosely holds today), plus the per-phase backend
  fan-out (`ARI_MODEL_CODING/BFTS/EVAL`, honoured by `_phase_llm`).
- **Expected concrete implementations.** One concrete `ExecutionServices`
  (builder + holder). No hierarchy; test builds inject stubs by passing a custom
  `BaseRegistry`.
- **Composition relationships.** *This is where every `Base*` above is
  instantiated and wired.* Consumes `ExecutionContext` (§3.18) and
  `BaseRegistry` (§3.14); produced object is consumed by `cli/*`,
  `BaseWorkflowDriver`, and the dashboard worker.
- **Compatibility concerns.** `build_runtime`'s 6-tuple return is consumed by
  the CLI/loop; `ExecutionServices` must either keep a `to_legacy_tuple()`
  adapter or update those call sites atomically. The rubric/metric-spec loading
  currently in `core.py` is domain logic that should **move out** (to evaluator
  services), not live in the composition root.
- **Migration subtasks.** (a) Introduce `ExecutionServices` wrapping the exact
  current wiring; expose `to_legacy_tuple()` for callers. (b) Move
  `_load_rubric_dict_for_axes`/`_make_metric_spec` into evaluator services.
  (c) Migrate the BFTS loop and dashboard worker off the tuple.

---

### 3.20 `DashboardViewService`  →  subtask 014

- **Purpose.** A read-model layer that turns runtime state/stores into
  serialisable view objects for the dashboard API, separating HTTP routing from
  data assembly.
- **Current implementation candidates.** *Does not exist.* Today the assembly is
  **inline in the route handlers**: `viz/routes.py` (1197),
  `viz/api_experiment.py` (929), `viz/api_paperbench.py` (813), plus ~20
  `api_*.py` files build response dicts by hand from
  `checkpoint`/`state`/filesystem reads (a grep for `ViewService`/`to_dict`
  dataclass patterns in `viz/*.py` returns **nothing** — no view layer exists).
  Mutable state is `viz/state.py` module globals.
- **Methods.** `experiment_view(run_id) -> DashboardDTO`,
  `tree_view(run_id)`, `paperbench_view(run_id)`, `settings_view()` — one method
  per major frontend page (Home/Experiments/Results/Tree/Wizard/Workflow), each
  reading through `BaseCheckpointStore`/`BaseTraceStore`/`BaseArtifactStore`.
- **State ownership.** Stateless read-model; owns no mutable state (that stays
  in `viz/state.py` / the runtime).
- **Expected concrete implementations.** One `DashboardViewService`; the
  `api_*.py` handlers become thin adapters that call it and JSON-encode the DTO.
- **Composition relationships.** Consumes the three stores + `ExecutionServices`
  read side; consumed by `routes.py`/`api_*.py`; emits `DashboardDTO` (§3.21).
- **Compatibility concerns.** **The dashboard JSON API is a hard contract** with
  `frontend/src/services/api.ts` (863 lines) and `websocket.py`. The view
  service must emit **byte-identical JSON shapes** to the current inline
  handlers — this is a pure internal reorganisation behind an unchanged wire
  format. Endpoint paths and the websocket message schema are frozen.
- **Migration subtasks.** (a) Snapshot current JSON responses as golden tests.
  (b) Extract assembly for one page (Results) into the service. (c) Repeat
  page-by-page; handlers shrink to routing only.

---

### 3.21 `DashboardDTO`  →  subtask 014

- **Purpose.** Typed data-transfer objects for the dashboard read-model, so the
  wire schema is defined in one place instead of implied by ad-hoc dicts.
- **Current implementation candidates.** *Does not exist* — responses are bare
  `dict`s assembled in handlers (see §3.20). The **implicit** schema lives on
  the TypeScript side in `frontend/src/services/api.ts` (863) and the large
  view files (`Results/resultSections.tsx` 1590, `Results/resultTypes`).
- **Methods.** DTOs are data, not behaviour: frozen `dataclass`es with a
  `to_json()`/`asdict` boundary (e.g. `ExperimentDTO`, `NodeDTO`, `TreeDTO`,
  `PaperBenchResultDTO`).
- **State ownership.** Pure value objects; own nothing.
- **Expected concrete implementations.** A small set of frozen dataclasses,
  one per view method in §3.20. No hierarchy.
- **Composition relationships.** Produced by `DashboardViewService`; their field
  names/shapes are the mirror of the TS types in `services/api.ts`.
- **Compatibility concerns.** Field names/nesting are the **dashboard API
  contract** — the DTOs must serialise to exactly today's JSON keys. Introducing
  DTOs must not change the wire format; ideally generate/verify against
  `services/api.ts` types (a candidate `check_viz_api_schema.py` gate, listed as
  missing tooling).
- **Migration subtasks.** (a) Define DTOs from the *current* JSON (golden
  snapshots). (b) Optionally add a schema-parity check vs `services/api.ts`.

---

### 3.22 `PromptRegistry`  →  subtask 013

- **Purpose.** A catalog mapping logical prompt keys to loaders/versions, so
  callers request `"agent/system"` without knowing where it lives (core package
  vs a skill's own `src/prompts/`).
- **Current implementation candidates.** *Does not exist as a class* (grep for
  `PromptRegistry` returns nothing). The pieces exist: `ari/prompts/` with the
  externalised `.md` templates (`agent/system.md`,
  `evaluator/{extract_metrics,peer_review}.md`,
  `orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,
  root_idea_selector}.md`, `pipeline/keyword_librarian.md`,
  `viz/{wizard_chat_goal,wizard_generate_config}.md`) and skills carrying their
  own (`ari-skill-paper-re/src/prompts/`, `ari-skill-replicate/src/prompts/`).
  Hardcoded/inline prompts still remain in the large `server.py`/`loop.py`/
  pipeline/evaluator files (to be inventoried in a `check_prompts.py` gate).
- **Methods.** `get(key) -> PromptLoader-bound template`,
  `resolve(key) -> (text, version_id)`, `keys()`. Backed by `BaseRegistry`
  keyed by prompt namespace.
- **State ownership.** Owns the key→loader mapping (which base dir serves which
  namespace); templates themselves are owned by `PromptLoader`.
- **Expected concrete implementations.** One `FilesystemPromptRegistry` over
  `package_prompts_root()` plus registered skill prompt roots.
- **Composition relationships.** Consulted by `BasePromptBuilder` (§3.4);
  composes `PromptLoader` (§3.23) and `BaseRegistry` (§3.14).
- **Compatibility concerns.** No external contract, but prompt **keys are
  reproducibility-relevant** (`load_versioned` hashing exists,
  `_loader.py:45`). Keep existing key strings (`"agent/system"` etc.) stable.
- **Migration subtasks.** (a) Introduce the registry over the existing prompt
  dir. (b) Register skill prompt roots. (c) Feed the `check_prompts.py`
  inventory so inline prompts get migrated into the registry over time.

---

### 3.23 `PromptLoader`  →  subtask 013

- **Purpose.** Load a raw prompt template by key from external files (the
  lowest-level prompt seam).
- **Current implementation candidates.** **Already exists.**
  `ari/prompts/_loader.py::PromptLoader` (L21, a `Protocol`) +
  `FilesystemPromptLoader` (L35, reads `{base}/{key}.md`); `load_versioned`
  returns `(text, sha256[:12])` (L45–49); `package_prompts_root()` (L16).
  Re-exported by `ari/prompts/__init__.py` and `ari/protocols/__init__.py:20`.
- **Methods.** `load(key) -> str`; `load_versioned(key, version=None) ->
  (text, version_id)` — keep verbatim.
- **State ownership.** Owns only its base directory (`_base`, `_loader.py:38`).
- **Expected concrete implementations.** `FilesystemPromptLoader` (KEEP) plus a
  test in-memory loader (the module docstring already anticipates tests swapping
  loaders, L5). Stays a **Protocol** (no ABC).
- **Composition relationships.** Held by `PromptRegistry` (§3.22) and, through
  it, by `BasePromptBuilder`. This is the reference for the whole
  "swap-impl-behind-a-Protocol" style (alongside `ConfigLoader`).
- **Compatibility concerns.** None external; already an internal Protocol. Do
  not change the `.md`-by-key convention (templates are `.md`, **not** `.j2`).
- **Migration subtasks.** *None for the loader itself* (KEEP as-is); work is in
  `PromptRegistry`/`BasePromptBuilder` adopting it more widely.

---

### 3.24 `ReferenceGraphAnalyzer`  →  subtask 014

- **Purpose.** Build and query the import/reference graph of the codebase to
  drive dead-code detection, import-boundary enforcement, and doc↔source
  coupling — the analysis engine behind several missing quality gates.
- **Current implementation candidates.** *No graph analyzer exists as a class.*
  The nearest existing tooling is `scripts/docs/check_ref_coupling.py`
  (maps changed source paths → referencing docs via YAML front-matter
  `sources:`) and `check_doc_sources.py` (forward direction). Missing (to be
  **designed, not implemented now**): `analyze_references.py`,
  `check_dead_code.py`, `check_import_boundaries.py`,
  `check_public_api_contracts.py`, `check_complexity.py`. Note: string-keyed
  live modules (`publish/backends/*.py`, resolved only via `_load_backend`)
  must be seeded as **live roots** or the analyzer will false-flag them.
- **Methods.** `build_graph(root)`, `dead_nodes(entrypoints)`,
  `violations(boundary_rules)`, `references(path) -> set[path]`.
- **State ownership.** Owns the parsed graph for one analysis pass; stateless
  across passes.
- **Expected concrete implementations.** One `ReferenceGraphAnalyzer` consumed
  by the missing `analyze_references.py` / `check_dead_code.py` /
  `check_import_boundaries.py` scripts. `radon` is **not installed** (complexity
  gate must not depend on it); `ruff` **is** available; use stdlib `ast`.
- **Composition relationships.** Stands alone under `scripts/`; feeds
  `.github/workflows/refactor-guards.yml`-style gates. Not part of the runtime
  package.
- **Compatibility concerns.** Analysis-only; touches no runtime contract. Must
  treat the four string-referenced publish backends, the two console_scripts,
  and MCP `server.py` entrypoints as live roots (entrypoint seeds), and must
  not depend on `radon` or `pnpm` (neither present).
- **Migration subtasks.** (a) Build the analyzer over stdlib `ast`. (b) Emit the
  live-root seed list (string-keyed modules, entrypoints). (c) Wire the missing
  gate scripts; note `check_docs_source_sync.py` **overlaps** existing
  `check_doc_sources.py` — extend, don't duplicate.

---

## 4. Subtask map (007–014)

The 24 abstractions are grouped into eight downstream subtask documents. These
documents do **not exist yet**; the links below are forward references to be
created under `docs/refactoring/subtasks/` (or as top-level `NNN_*.md`).

| Subtask | Title | Abstractions | Primary area findings |
|---|---|---|---|
| **007** | `007_model_cost_logging.md` | BaseModelBackend, BaseCostTracker, BaseLogger | eval/llm |
| **008** | `008_agent_loop_and_strategy.md` | BaseStrategy, BaseAgentLoop, BasePromptBuilder | orch |
| **009** | `009_evaluation.md` | BaseEvaluator, BaseCompositeEvaluator | eval |
| **010** | `010_pipeline_workflow.md` | BasePipelineStage, BaseWorkflowDriver | pipe |
| **011** | `011_storage_and_paths.md` | BaseArtifactStore, BaseCheckpointStore, BaseTraceStore, RuntimePathResolver | storage |
| **012** | `012_memory_and_skill_adapters.md` | BaseMemoryClient, BaseSkillAdapter | eval/packaging |
| **013** | `013_registry_prompts_composition.md` | BaseRegistry, PromptRegistry, PromptLoader, ExecutionContext, ExecutionServices | registry/packaging |
| **014** | `014_dashboard_and_reference_analysis.md` | DashboardViewService, DashboardDTO, ReferenceGraphAnalyzer | viz/tooling |

### 4.1 Build/adoption order (dependency-first)

1. **011** (paths + stores) and **013**'s `PromptLoader`/`BaseRegistry` are
   foundation — most other abstractions inject them.
2. **007** (model backend/cost) — needed by 008 and 009.
3. **012** (skill adapter, memory) — needed by 008.
4. **009** (evaluator) — needed by 008.
5. **008** (agent loop, strategy, prompt builder) — the hot path.
6. **010** (pipeline/workflow driver) — consumes stores + skill adapter.
7. **013**'s `ExecutionContext`/`ExecutionServices` — the composition root that
   wires everything above.
8. **014** (dashboard read-model + reference analyzer) — last; reads through the
   stores and enforces the boundaries the earlier subtasks establish.

---

## 5. Classification summary

| Abstraction | Current code | Class | Disposition |
|---|---|---|---|
| BaseModelBackend | `llm/client.py::LLMClient` (26) | ABC/Protocol (new) | ADAPT |
| BaseStrategy | `orchestrator/bfts.py::BFTS` (845) | ABC (new) | ADAPT |
| BaseAgentLoop | `agent/loop.py` (1630) + `react_driver.py` (442) | ABC (new) | MERGE |
| BasePromptBuilder | inline in `bfts.py`/`loop.py` | Protocol (new) | ADAPT (extract) |
| BaseEvaluator | `protocols/evaluator.py::Evaluator` (18) + `LLMEvaluator` (240) | Protocol (exists) | KEEP |
| BaseCompositeEvaluator | `_COMPOSITES` dict (llm_evaluator.py:165) | interface (new) | ADAPT |
| BaseMemoryClient | `memory/client.py::MemoryClient` ABC (8) + skill `MemoryBackend` | ABC (exists ×2) | MERGE |
| BaseArtifactStore | scattered (pipeline L757–826, clone/publish/registry) | ABC (new) | ADAPT |
| BaseCheckpointStore | `checkpoint.py` module fns (198) | Protocol (new) | KEEP |
| BaseTraceStore | scattered trace/report/JSONL writers | Protocol (new) | ADAPT |
| BasePipelineStage | dict stages in `workflow.yaml` + orchestrator | ABC (new) | ADAPT |
| BaseWorkflowDriver | `orchestrator.py::run_pipeline` (913) + viz worker dup | Protocol (new) | MERGE |
| BaseSkillAdapter | `mcp/client.py::MCPClient` (256) | ABC (new) | ADAPT |
| BaseRegistry | 3 string dispatchers + `ari/registry/` name clash | generic (new) | ADAPT |
| BaseCostTracker | `cost_tracker.py::CostTracker` (448) | Protocol (new) | ADAPT |
| BaseLogger | stdlib `logging` + ad-hoc JSONL | Protocol (new) | REVIEW_REQUIRED |
| RuntimePathResolver | `paths.py::PathManager` (304) + `config/finder.py` | concrete (exists) | KEEP + MERGE finder |
| ExecutionContext | env vars + `build_runtime` args + `viz/state.py` | dataclass (new) | ADAPT |
| ExecutionServices | `core.py::build_runtime` (83–222) | concrete (new) | ADAPT |
| DashboardViewService | inline in `viz/routes.py` + `api_*.py` | concrete (new) | ADAPT |
| DashboardDTO | bare dicts + TS `services/api.ts` | dataclasses (new) | ADAPT |
| PromptRegistry | does not exist; `prompts/` dir + skill prompts | concrete (new) | ADAPT |
| PromptLoader | `prompts/_loader.py::PromptLoader` (21) | Protocol (exists) | KEEP |
| ReferenceGraphAnalyzer | does not exist; `scripts/docs/check_ref_coupling.py` | concrete (new, tooling) | ADAPT |

---

## 6. Open questions (REVIEW_REQUIRED, to resolve in subtasks)

1. **`BaseRegistry` naming** must not collide with the existing HTTP
   `ari/registry/` package (subtask 013).
2. **Two `MemoryClient` ABCs** (core `MemoryClient` vs skill `MemoryBackend`)
   diverge in types; whether the divergence is intentional is unconfirmed
   (subtask 012).
3. **`FileMemoryClient` JSON-array vs JSONL** mismatch (`file_client.py:44` vs
   canonical `memory_store.jsonl`) — confirm runtime impact (subtask 011/012).
4. **Workspace-root ambiguity** (`config/__init__.py:588` `workspace/checkpoints`
   vs `default.yaml` `./checkpoints`) — pick one, keep both readable
   (subtask 011).
5. **`BaseLogger` scope** — likely stays mostly stdlib `logging`; only the
   structured JSONL writers justify an abstraction (subtask 007).
6. **MCP silent-collision policy** — warn vs error on cross-skill tool-name
   clobber (`mcp/client.py:325`) (subtask 012).
7. **`resolve_litellm_model`** — keep as provider-routing or fold into
   `BaseRegistry` (subtask 013/007).
8. **`ari.schemas.load()` loader** — no production importer; DELETE_CANDIDATE
   for the loader API while keeping the JSON schema files (subtask 011).
9. **`ExecutionServices` legacy 6-tuple** — provide `to_legacy_tuple()` vs
   atomic call-site migration (subtask 013).

---

*End of 006 — Target Architecture Plan. Planning only; no runtime code changed.*

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
