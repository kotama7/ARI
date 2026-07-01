# Subtask 011: Separate BFTS Strategy from ReAct Loop

> Phase 3: Core Architecture · Complexity: High · Changes runtime code: **Yes**
> Depends on: **007** (`define_core_interfaces_and_protocols`)
> Planning date: 2026-07-01 · ari-core version 0.9.0 · git branch `main`

---

## 1. Goal

Cleanly separate the **search strategy** (which node to expand/run next — today
`ari/orchestrator/bfts.py`, 845 LOC) from the **single-node ReAct executor**
(Thought→Action→Observation over MCP tools — today `ari/agent/loop.py`, 1630 LOC),
so that:

- `BFTS` becomes a (near-)pure ranking/selection component: given nodes + config +
  an injected LLM, it decides *which* leaf to expand and *how many* children to
  generate, with no direct filesystem reads and no inline prompt/context
  serialization tangled into its ranking methods.
- `AgentLoop.run` (currently one ~1170-line method, L459–1630) is decomposed so
  that prompt assembly, message-window management, tool-result routing, and
  node evaluation/memory persistence live behind named seams rather than inside a
  single method body.
- The orchestrator glue `ari/cli/bfts_loop.py::_run_loop` (L85–837) depends on the
  strategy and executor through the interfaces introduced in subtask **007**
  (`NodeStore`, `StageRunner`, and — new here — a strategy/executor seam), not on
  concrete class internals.

Non-goal restatement: this is a *seam extraction and de-tangling* task, **not** a
rewrite of the BFTS algorithm or the ReAct control flow. Behavior must be
byte-for-byte equivalent for existing tests unless a test asserts on an internal
structure that the refactor intentionally moves (see Section 12/13).

---

## 2. Background

The orchestration core is composed at `ari/core.py::build_runtime` (L83–222), which
wires the LLM client(s), `MemoryClient`, `MCPClient`, `BFTS`, `AgentLoop`, and
`LLMEvaluator`. Concretely:

- `BFTS` is constructed once, at `ari/core.py:148` (`bfts = BFTS(cfg.bfts, bfts_llm)`;
  imported lazily at `ari/core.py:102`).
- `AgentLoop` is constructed once, at `ari/core.py:219`.
- `_run_loop` in `ari/cli/bfts_loop.py` drives them together: it calls
  `bfts.select_best_to_expand` (`bfts_loop.py:219`), `bfts.should_prune`
  (`bfts_loop.py:223`), `bfts.expand` (`bfts_loop.py:327`), and
  `bfts.select_next_node` (`bfts_loop.py:360`), and runs the executor via a
  `ThreadPoolExecutor` (`bfts_loop.py:373`) submitting `agent.run`
  (`bfts_loop.py:533`).

As-built responsibility split (verified by inspection):

- **`ari/orchestrator/bfts.py` = the search strategy.** `class BFTS` starts at
  `bfts.py:250`. Public selection/ranking methods: `select_next_node` (L418),
  `select_best_to_expand` (L520), `should_prune` (L498), `expand` (L577). Diversity
  accounting: `expansion_count` (L267), `record_run` (L271), `diversity_bonus`
  (L294). Deterministic fallbacks: `_fallback_score` (L322), `_select_fallback`
  (L356). It is *itself an LLM caller*: `self.llm.complete` at L485, L564, L762.
- **`ari/agent/loop.py` = the ReAct executor for one node.** `class AgentLoop` at
  L366; `run` at L459–1630. Its single LLM call is at L837.
- **`ari/agent/react_driver.py` (442 LOC) = a second, cleaner generic ReAct loop**
  (`run_react` at L231) already used by pipeline stages via
  `ari/pipeline/stage_runner.py:143`. This is direct evidence of duplicated ReAct
  logic (see Section 7, item E and Section 4).

Partial extraction is already done in the agent package: `tool_manager.py`,
`guidance.py`, `message_utils.py`, `metric_contract.py`, plus the
`ari/orchestrator/node_report/` builder and `ari/orchestrator/node_selection.py`
(the shared leaf selector). This subtask continues that trajectory.

Dependency on **007**: subtask 007 grounds on the existing `ari/protocols/` package
whose `__init__.py` docstring already declares that `NodeStore` and `StageRunner`
Protocols "land in subsequent phases when their adopters are ready." 011 is one such
adopter: the NodeReport read seam (Section 7, item B) should consume the `NodeStore`
Protocol defined by 007, and the executor seam should align with `StageRunner`.

---

## 3. Scope

In scope:

1. **BFTS strategy purity.** Extract the heavy inline context serialization out of
   `BFTS`:
   - `expand` context blocks (`bfts.py:604–760`: sci_note/depth_note/budget_note,
     sibling/ancestor/existing-children/diversity blocks),
   - candidate descriptions in `select_best_to_expand` (L537–550) and
     `select_next_node` (L451–470),
   into a dedicated `BFTSPromptBuilder` (new module under `ari/orchestrator/`).
   Leave `BFTS` as ranking/selection + LLM invocation over builder-produced strings.
2. **NodeReport read seam.** Route the four filesystem readers
   `_resolve_pm_and_run_id` (L43), `_format_parent_report_block` (L64),
   `_get_node_report` (L372), `_load_sibling_node_reports` (L406) through an
   injected `NodeStore`/report-store abstraction (from 007 / coordinated with
   subtask 010), removing the direct `ari.paths.PathManager` + filesystem coupling
   from `BFTS`.
3. **AgentLoop decomposition.** Split `AgentLoop.run` into named collaborators
   inside `ari/agent/`:
   - a **PromptAssembler** for system prompt (L489–554) and root/child user_content
     (module-level `build_working_context_messages`, L164–355),
   - a **MessageWindow** seam consolidating `_build_safe_window` (L725–805) and
     `repair_tool_message_order` (L113–155),
   - a **ToolResultRouter** for the domain-specific tool dispatch (the giant
     `if r["name"] == ...` router, L950–1318),
   - a **NodeEvaluationPersister** deduping the three `evaluate_sync` blocks
     (L1454, L1532, L1600) and the ~six near-identical `add_memory` "RESULT SUMMARY"
     calls (L921, L960, L1480, L1549, L1567, L1615).
4. **Executor/strategy seam.** Define (aligned with 007) a minimal strategy
   interface exposing `select_next_node`, `select_best_to_expand`, `should_prune`,
   `expand`, `record_run` and an executor interface exposing `run(node, experiment)`,
   so `_run_loop` binds to abstractions. `BFTS` and `AgentLoop` become the default
   implementations.

Deferred / coordinate elsewhere (see Section 4 and Section 15):

- Unifying `agent/loop.py` with `agent/react_driver.py` (large, REVIEW_REQUIRED).
- Pulling workspace/persistence out of `_run_loop` (file-copy L398–517, sterile
  detection L631–661, `write_node_report` L663–673, checkpoint save L712, lineage
  hooks L718–823) — overlaps subtasks **010** (checkpoint/trace store) and **012**
  (pipeline stage architecture); do only the minimum here to keep `BFTS` clean.

---

## 4. Non-Goals

- **No algorithm change.** Ranking math (`_fallback_score`, `diversity_bonus`),
  pruning cutoffs (`should_prune`), and the `expand` "≤1 child" contract stay
  semantically identical.
- **No merge of the two ReAct loops in this subtask.** `ari/agent/react_driver.py`
  (`run_react`, used by `pipeline/stage_runner.py:143`) and `ari/agent/loop.py`
  duplicate ReAct control flow, but unifying them is classified **REVIEW_REQUIRED**
  and is explicitly out of scope here to bound risk. Note the duplication in the doc
  produced by subtask 013 (reference graph / dead code) instead. Do not delete
  `react_driver.py`.
- **No prompt text changes.** The orchestrator prompt templates already live in
  `ari/prompts/orchestrator/{bfts_expand,bfts_expand_select,bfts_select,lineage_decision,root_idea_selector}.md`
  (loaded via `FilesystemPromptLoader`). This subtask relocates the *context
  serialization* around them, not the `.md` bodies. (Prompt-management policy is
  owned by the top-level plan `docs/refactoring/011_prompt_management_plan.md` — note
  the numeric collision: that is a *different* 011 in the top-level plan set.)
- **No lineage-decision refactor.** `ari/orchestrator/lineage_decision.py` and
  `root_idea_selector.py` are left untouched.
- **No config-schema change.** `BFTSConfig` (`ari.config.BFTSConfig`) and its
  `select_prompt` / `expand_select_prompt` attributes (asserted by
  `tests/test_bfts_prompt_selection.py`) stay exactly as-is.
- **No `~/.ari/` reintroduction; no `sonfigs/`.** There is no `sonfigs/` directory in
  the repo — do not create one. Checkpoint-scoped storage (v0.5.0) is preserved.

---

## 5. Current Files / Directories to Inspect

Verified real paths (LOC / byte sizes as measured 2026-07-01):

| Path | Size | Role |
|---|---|---|
| `ari-core/ari/orchestrator/bfts.py` | 845 LOC | Search strategy (`class BFTS` @250); LLM calls @485/564/762; fs readers @43/64/372/406 |
| `ari-core/ari/orchestrator/__init__.py` | ~30 LOC | Package docstring/roadmap for orchestrator split |
| `ari-core/ari/orchestrator/node.py` | 7.2 KB | `Node`/`NodeLabel` data model |
| `ari-core/ari/orchestrator/node_selection.py` | 12.7 KB | Shared leaf selector `filter_nodes` (already extracted) |
| `ari-core/ari/orchestrator/node_report/` | dir | Per-node report builder + v0.5 legacy reconstruct |
| `ari-core/ari/orchestrator/lineage_decision.py` | 22.2 KB | Lineage LLM judge (out of scope, do not edit) |
| `ari-core/ari/agent/loop.py` | 1630 LOC | ReAct executor (`class AgentLoop` @366; `run` @459) |
| `ari-core/ari/agent/react_driver.py` | 442 LOC | Second generic ReAct loop `run_react` @231 (do not merge here) |
| `ari-core/ari/agent/tool_manager.py` | 5.2 KB | Already-extracted tool mgmt |
| `ari-core/ari/agent/guidance.py` | 5.0 KB | Already-extracted guidance |
| `ari-core/ari/agent/message_utils.py` | 2.0 KB | Already-extracted message utils |
| `ari-core/ari/agent/metric_contract.py` | 17.1 KB | Metric-contract handling |
| `ari-core/ari/cli/bfts_loop.py` | 911 LOC | Glue `_run_loop` @85; strategy calls @219/223/327/360; executor @373/533 |
| `ari-core/ari/core.py` | 282 LOC | Composition root `build_runtime` @83; `BFTS()` @148; `AgentLoop()` @219 |
| `ari-core/ari/protocols/__init__.py` | ~30 LOC | 007's Protocols (`Evaluator`, `PromptLoader`, `ConfigLoader`; `NodeStore`/`StageRunner` planned) |
| `ari-core/ari/pipeline/stage_runner.py` | — | Consumer of `run_react` @143 (evidence of ReAct duplication) |
| `ari-core/ari/prompts/orchestrator/*.md` | 6 files | `bfts_expand.md`, `bfts_expand_select.md`, `bfts_select.md`, `lineage_decision.md`, `root_idea_selector.md`, `README.md` |

Existing tests that pin the current seams (inspect before editing):

- `ari-core/tests/test_bfts.py`
- `ari-core/tests/test_bfts_diversity.py` (constructs `BFTS(cfg, mock_llm)` @42)
- `ari-core/tests/test_bfts_frontier_score.py`
- `ari-core/tests/test_bfts_prompt_selection.py` (asserts `config.select_prompt` /
  `config.expand_select_prompt` defaults @71–72; variant plumbing @31/52)
- `ari-core/tests/test_bfts_allow_web.py`
- `ari-core/tests/test_bfts_eval_config_integration.py`
- `ari-core/tests/test_idea_integration.py` (builds `BFTS(...)` @95/@119)
- `ari-core/tests/test_laptop_hpc_skill_drop.py` (**monkeypatches**
  `ari.orchestrator.bfts.BFTS` @97 — this import path MUST remain patchable)
- `ari-core/tests/test_run_loop.py`
- `ari-core/tests/test_orchestrator.py`
- `ari-core/tests/test_agent_smoke.py`
- `ari-core/tests/test_loop_message_order.py`
- `ari-core/tests/test_react_driver.py`
- `ari-core/tests/test_max_react_passthrough.py`
- `ari-core/tests/test_server.py` (imports `BFTSConfig` @1085)

---

## 6. Current Problems

1. **Strategy tangled with I/O and prompt-building (`bfts.py`).** `BFTS`'s ranking
   methods are interleaved with (a) direct filesystem reads of `node_report.json`
   via `_resolve_pm_and_run_id` (L43), `_format_parent_report_block` (L64),
   `_get_node_report` (L372), `_load_sibling_node_reports` (L406) — coupling `BFTS`
   to `ari.paths.PathManager` and the on-disk layout — and (b) heavy inline context
   serialization in `expand` (L604–760) and candidate descriptions (L451–470,
   L537–550). This makes the "which node next" logic hard to unit-test without a
   real checkpoint dir and hard to reason about independently of prompt formatting.

2. **`AgentLoop.run` is a ~1170-line method.** L459–1630 mixes: system-prompt
   assembly (L489–554), user_content assembly (L570–621 + module-level
   `build_working_context_messages` L164–355), context-window repair
   (`_build_safe_window` L725–805, `repair_tool_message_order` L113–155), a single
   LLM call (L837), a giant domain-specific tool router (L950–1318), triplicated
   `evaluate_sync` (L1454/1532/1600), and ~six near-identical `add_memory` "RESULT
   SUMMARY" writes (L921/960/1480/1549/1567/1615). The docstring claims "no
   domain-specific knowledge," yet the router reaches cross-layer into
   `ari_skill_memory.backends` (L1047) and `ari.pipeline._extract_plan_sections`
   (L1061, L1118).

3. **Duplicated ReAct logic.** `agent/loop.py` and the cleaner
   `agent/react_driver.py` (`run_react`, used by `pipeline/stage_runner.py:143`)
   implement the same Thought→Action→Observation control flow twice. (Unifying is
   deferred — see Section 4 — but the seam introduced here should make a later merge
   tractable.)

4. **Glue owns persistence, not just scheduling (`bfts_loop.py`).** `_run_loop`
   mixes pure scheduling (`ThreadPoolExecutor` fan-out @373/533) with
   workspace/persistence: file-copy inheritance (L398–517), sterile detection
   (L631–661), `write_node_report` (L663–673), memory consolidation (L686–708),
   checkpoint save (L712), lineage hooks (L718–823). This makes the strategy↔executor
   boundary implicit and undocumented.

5. **Composition root does more than compose (`core.py`).** `build_runtime`
   neighbors rubric YAML loading `_load_rubric_dict_for_axes` (L23–55), a generic
   `_make_metric_spec` (L62–76), and pipeline dispatch `generate_paper_section`
   (L235–283 with `print`/path resolution). Not this subtask's target to fix, but
   relevant when threading the new interfaces through `build_runtime`.

---

## 7. Proposed Design / Policy

Classification of the touched components:

| Component | Class | Rationale |
|---|---|---|
| `ari/orchestrator/bfts.py::BFTS` | **KEEP (ADAPT internals)** | Same public class name, ctor, methods; internals slimmed |
| `expand`/candidate context serialization | **MOVE** → new `BFTSPromptBuilder` | Pure string-building extracted out of `BFTS` |
| `_resolve_pm_and_run_id`/`_format_parent_report_block`/`_get_node_report`/`_load_sibling_node_reports` | **ADAPT** → injected `NodeStore` seam | Remove fs/`ari.paths` coupling from strategy |
| `ari/agent/loop.py::AgentLoop` | **KEEP (ADAPT internals)** | Same public class + `run(node, experiment)` signature |
| PromptAssembler / MessageWindow / ToolResultRouter / NodeEvaluationPersister | **MOVE** → new agent submodules | De-tangle `run` |
| Strategy + Executor interfaces | **ADAPT** (align with 007 Protocols) | `_run_loop` binds to abstractions |
| `ari/agent/react_driver.py` | **KEEP** | Merge deferred (REVIEW_REQUIRED) |
| `ari/orchestrator/lineage_decision.py`, `root_idea_selector.py` | **KEEP (untouched)** | Out of scope |

### A. `BFTSPromptBuilder` (new module in `ari/orchestrator/`)

A pure, deterministic string-builder that takes `(node, siblings, ancestors,
existing_children, diversity_state, budget)` and returns the context blocks that
`expand`/`select_*` currently inline. `BFTS` calls the builder, then feeds the result
into `self.llm.complete`. The builder reuses the existing `_PromptBudget` dataclass
(`bfts.py:26–37`) — move it into the builder module. No `.md` template body changes.

### B. NodeReport read seam (consume 007's `NodeStore`)

Replace the four in-`BFTS` filesystem readers with calls to an injected store
interface (`NodeStore` from subtask 007; backed by the artifact/checkpoint/trace
store from subtask 010). `BFTS.__init__` gains an optional `node_store=None` param
that defaults (for backward compat) to a small adapter wrapping the current
`ari.paths.PathManager`-based logic, so existing constructions
`BFTS(cfg.bfts, bfts_llm)` and test `BFTS(cfg, mock_llm)` keep working unchanged.
This removes the hard `from ari.paths import PathManager` reach from the strategy's
hot path while preserving behavior when no store is injected.

### C. Decompose `AgentLoop.run`

Introduce four collaborators under `ari/agent/` (new files), each a plain class or
function group with `AgentLoop.run` orchestrating them:

- `PromptAssembler`: owns system-prompt (L489–554) + user_content (L570–621) +
  `build_working_context_messages` (L164–355). Move `build_working_context_messages`
  into this module (keep a re-export shim in `loop.py` if any test imports it).
- `MessageWindow`: owns `_build_safe_window` (L725–805) and
  `repair_tool_message_order` (L113–155). `repair_tool_message_order` is module-level
  today and pinned by `tests/test_loop_message_order.py` — **keep the existing
  import path importable** (re-export).
- `ToolResultRouter`: owns the dispatch at L950–1318. Cross-layer reaches
  (`ari_skill_memory.backends` L1047, `ari.pipeline._extract_plan_sections` L1061/1118)
  are preserved but isolated behind this router so `AgentLoop` no longer imports them
  directly.
- `NodeEvaluationPersister`: single method that performs the evaluate-then-persist
  sequence, called from the three sites that today inline `evaluate_sync`
  (L1454/1532/1600) and the ~six `add_memory` "RESULT SUMMARY" writes
  (L921/960/1480/1549/1567/1615). Collapse the duplication into one path.

### D. Strategy / Executor seam

Define (in `ari/protocols/` per 007, or re-exported from there) a minimal
`SearchStrategy` Protocol (`select_next_node`, `select_best_to_expand`, `should_prune`,
`expand`, `record_run`, `expansion_count`, `diversity_bonus`) and a `NodeExecutor`
Protocol (`run(node, experiment) -> Node`). `BFTS` and `AgentLoop` satisfy them
structurally (no subclassing needed). `_run_loop` and `build_runtime` type-hint
against the Protocols; runtime construction is unchanged.

### E. ReAct unification — deferred

Record the `loop.py` vs `react_driver.py` duplication as a follow-up (feed into
subtask 013's reference/dead-code report). Do **not** merge in 011.

---

## 8. Concrete Work Items

1. **Add `ari/orchestrator/bfts_prompt_builder.py`.** Move `_PromptBudget`
   (`bfts.py:26–37`), the `expand` context blocks (L604–760), and candidate
   descriptions (L451–470, L537–550) into pure builder functions/class. Update
   `expand`/`select_best_to_expand`/`select_next_node` to call the builder.
2. **Add a NodeReport store adapter** and thread it through `BFTS.__init__`
   (`node_store` param, default adapter preserving current behavior). Replace bodies
   of `_resolve_pm_and_run_id` (L43), `_format_parent_report_block` (L64),
   `_get_node_report` (L372), `_load_sibling_node_reports` (L406) with delegation to
   the store. Keep these method names as thin delegators if any test references them.
3. **Add `ari/agent/prompt_assembler.py`, `ari/agent/message_window.py`,
   `ari/agent/tool_result_router.py`, `ari/agent/node_eval_persister.py`.** Move the
   corresponding regions out of `loop.py`; wire `AgentLoop.run` to call them. Keep
   `repair_tool_message_order` and `build_working_context_messages` importable from
   their current module paths via re-export shims.
4. **Collapse duplication.** Route the 3 `evaluate_sync` sites and 6 `add_memory`
   sites through `NodeEvaluationPersister`.
5. **Define Protocols** (`SearchStrategy`, `NodeExecutor`) per 007 and type-hint
   `_run_loop` (`bfts_loop.py:85`) and `build_runtime` (`core.py:83`) against them.
   No behavioral change to construction (`core.py:148`, `core.py:219`).
6. **Update `ari/orchestrator/__init__.py` and `ari/agent/__init__.py`** exports to
   include the new modules; keep every currently-exported name.
7. **Run and update tests** only where they assert on moved *internal* structure;
   never relax a public-contract assertion (Section 10).

---

## 9. Files Expected to Change

Modified (real paths):

- `ari-core/ari/orchestrator/bfts.py` — slim `BFTS` to ranking/selection + builder +
  store delegation.
- `ari-core/ari/agent/loop.py` — decompose `run`; add re-export shims.
- `ari-core/ari/cli/bfts_loop.py` — type-hint `_run_loop` against Protocols
  (no scheduling logic change).
- `ari-core/ari/core.py` — type-hint `build_runtime`; pass optional `node_store` if
  threaded (construction call sites @148/@219 keep working defaults).
- `ari-core/ari/orchestrator/__init__.py` — export new builder module.
- `ari-core/ari/agent/__init__.py` — export new agent submodules.
- `ari-core/ari/protocols/__init__.py` — add `SearchStrategy` / `NodeExecutor`
  (coordinated with subtask 007; if 007 already added them, import from there).

New files (real, planned paths):

- `ari-core/ari/orchestrator/bfts_prompt_builder.py`
- `ari-core/ari/orchestrator/node_report_store.py` (adapter; or reuse 010's module)
- `ari-core/ari/agent/prompt_assembler.py`
- `ari-core/ari/agent/message_window.py`
- `ari-core/ari/agent/tool_result_router.py`
- `ari-core/ari/agent/node_eval_persister.py`
- `ari-core/ari/protocols/search.py` (if 007 does not already own these Protocols)

Tests likely touched (assert-on-internals only):
`ari-core/tests/test_bfts.py`, `test_bfts_diversity.py`, `test_bfts_frontier_score.py`,
`test_run_loop.py`, `test_orchestrator.py`, `test_agent_smoke.py`,
`test_loop_message_order.py`. New unit tests for `BFTSPromptBuilder` and
`NodeEvaluationPersister` are encouraged (align with subtask 018 boundary tests).

---

## 10. Files / APIs That Must Not Be Broken

- **`ari.orchestrator.bfts.BFTS` import path + class name** — monkeypatched by
  `tests/test_laptop_hpc_skill_drop.py:97` (`setattr("ari.orchestrator.bfts.BFTS",
  _StubBFTS)`). Must remain a patchable module-level symbol.
- **`BFTS` constructor signature** `BFTS(cfg.bfts, bfts_llm)` — used by
  `core.py:148` and tests (`BFTS(cfg, mock_llm)` in `test_bfts_diversity.py:42`;
  `BFTS(BFTSConfig(...), mock_llm)` in `test_idea_integration.py:95/119`). Any new
  params must be keyword-with-defaults.
- **`BFTS` public methods** called by glue: `select_next_node`, `select_best_to_expand`,
  `should_prune`, `expand`, `record_run` — signatures unchanged.
- **`BFTSConfig.select_prompt` / `.expand_select_prompt`** and their default values
  `"orchestrator/bfts_select"` / `"orchestrator/bfts_expand_select"` — asserted by
  `tests/test_bfts_prompt_selection.py:71–72`; variant plumbing @31/@52.
- **`AgentLoop` class name + `run(node, experiment)` signature** — constructed at
  `core.py:219`, submitted at `bfts_loop.py:533`.
- **`repair_tool_message_order` importable from `ari.agent.loop`** — pinned by
  `tests/test_loop_message_order.py`.
- **Prompt template ids/paths** under `ari/prompts/orchestrator/*.md` — loaded via
  `FilesystemPromptLoader`; asserted by `tests/test_prompt_extraction.py` and
  `tests/test_bfts_prompt_selection.py`.
- **`ari/agent/react_driver.py::run_react`** — consumed by `pipeline/stage_runner.py:143`;
  do not touch.
- **External contracts** (unchanged by this subtask, but re-stated): CLI `ari`
  (`ari.cli:app`), `ari.public.*` API, the 14 MCP `ari-skill-*` tool contracts, the
  dashboard API (`ari/viz/routes.py` + `api_*.py`), checkpoint/config file formats,
  and scripts referenced by `.github/workflows/`.

---

## 11. Compatibility Constraints

- **Additive-only public surface.** New params default to preserving current
  behavior; no positional signature changes; no renamed public symbols.
- **Re-export shims** for any moved module-level function that a test or another
  module imports by its current path (`repair_tool_message_order`,
  `build_working_context_messages`). Removing the shim later is a separate subtask.
- **Determinism (design principle P2).** The extracted `BFTSPromptBuilder` and the
  fallback/diversity math must produce identical strings/scores for identical inputs;
  do not reorder dict/set iteration in a way that changes prompt text. Do not
  introduce any new LLM call — `ari-skill-memory` and deterministic scoring paths
  keep their "no new LLM calls" property.
- **No new dependencies.** `radon` is not installed; do not add it. Use only
  `ruff`, `compileall`, `pytest` (all available).
- **No directory renames.** Do not touch `config/` vs `configs/` vs top-level
  `config/`; there is no `sonfigs/` and none may be created.
- **Checkpoint layout unchanged.** The NodeReport store adapter must read the same
  `node_report.json` at the same `PathManager.node_work_dir(run_id, node.id)` path
  it reads today (`bfts.py:77`).

---

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`):

1. `python -m compileall ari-core/ari` — syntax/import sanity for all moved code.
2. `ruff check .` — lint (ruff is available; must stay clean).
3. `pytest -q` — full suite. Targeted first pass:
   `pytest -q ari-core/tests/test_bfts.py ari-core/tests/test_bfts_diversity.py
   ari-core/tests/test_bfts_frontier_score.py ari-core/tests/test_bfts_prompt_selection.py
   ari-core/tests/test_bfts_allow_web.py ari-core/tests/test_bfts_eval_config_integration.py
   ari-core/tests/test_idea_integration.py ari-core/tests/test_laptop_hpc_skill_drop.py
   ari-core/tests/test_run_loop.py ari-core/tests/test_orchestrator.py
   ari-core/tests/test_agent_smoke.py ari-core/tests/test_loop_message_order.py
   ari-core/tests/test_react_driver.py ari-core/tests/test_max_react_passthrough.py
   ari-core/tests/test_prompt_extraction.py`.
4. `scripts/run_all_tests.sh` (repo aggregate) if present in the environment.

No frontend build is required — this subtask does not touch
`ari-core/ari/viz/frontend/` (so `npm test` / `npm build` are not applicable).

---

## 13. Acceptance Criteria

1. `python -m compileall ari-core/ari`, `ruff check .`, and `pytest -q` all pass with
   no new failures relative to `main`.
2. `ari.orchestrator.bfts.BFTS` is still a module-level, monkeypatchable symbol; the
   stub-injection in `tests/test_laptop_hpc_skill_drop.py:97` still works.
3. `grep -n "PathManager\|node_report.json" ari-core/ari/orchestrator/bfts.py` shows
   the filesystem coupling now goes through the injected store adapter (direct
   `PathManager` import removed from `BFTS`'s ranking hot path, or confined to the
   default adapter).
4. `AgentLoop.run` is materially smaller (target: the single method drops well below
   its current ~1170 lines; the domain tool router, evaluate/persist, prompt assembly,
   and window logic live in the new submodules).
5. Exactly one code path performs evaluate-then-persist (the former L1454/1532/1600 +
   add_memory sites now route through `NodeEvaluationPersister`).
6. `_run_loop` (`bfts_loop.py:85`) and `build_runtime` (`core.py:83`) reference the
   `SearchStrategy` / `NodeExecutor` Protocols; no behavioral change in construction.
7. No changes under `ari-core/ari/viz/`, no `.md` prompt-body edits, no config/dir
   renames, and `ari/agent/react_driver.py` unchanged.
8. `git diff --stat` touches only files in Section 9 (plus any strictly-internal test
   updates).

---

## 14. Rollback Plan

- The change is confined to `ari-core/ari/orchestrator/`, `ari-core/ari/agent/`,
  `ari-core/ari/cli/bfts_loop.py`, `ari-core/ari/core.py`, `ari-core/ari/protocols/`,
  and new sibling modules — no data/format migrations. Rollback is a single
  `git revert <merge>` (or branch drop) with no cleanup of on-disk state.
- Because all public signatures are additive and re-export shims preserve import
  paths, reverting cannot leave dangling imports in callers or tests.
- Land behind a small first PR that only introduces the Protocols + builder + store
  adapter (no `AgentLoop` decomposition), verify green, then a second PR for the
  `AgentLoop` split — so either half can be reverted independently.
- If `BFTSPromptBuilder` output diverges from the legacy inline strings (caught by a
  golden-string test), revert item 1 only; the store/Protocol changes are orthogonal.

---

## 15. Dependencies

Per the master dependency graph (`007 -> 008, 009, 010, 011, 012, 013, 014`):

- **Hard prerequisite: 007** (`define_core_interfaces_and_protocols`). 011 consumes
  the `NodeStore` and `StageRunner` Protocols that 007 lands in `ari/protocols/`
  (the package `__init__.py` already names them as "subsequent phases"). The
  `SearchStrategy` / `NodeExecutor` Protocols in Section 7-D should be defined by, or
  co-located with, 007's output.
- **Inventory/foundation subtasks that MUST precede any runtime code change**
  (repo-wide gate): **001, 002, 020, 036, 045, 053, 059, 060, 067**. 011 is a runtime
  code change, so these must be complete/merged before 011 lands.
- **Coordinate with (not blocked by):**
  - **010** (`extract_artifact_checkpoint_trace_store`) — the NodeReport read seam
    (Section 7-B) should reuse 010's store rather than a bespoke adapter if 010 lands
    first; otherwise 011 ships a minimal adapter that 010 later folds in.
  - **012** (`refactor_pipeline_stage_architecture`) — the deferred "pull persistence
    out of `_run_loop`" work and the ReAct-duplication cleanup overlap 012's stage
    driver; keep the executor Protocol compatible with 012's `StageRunner`.
  - **013** (`refactor_memory_boundary`) — the `add_memory`/`ari_skill_memory.backends`
    reaches consolidated in `NodeEvaluationPersister` / `ToolResultRouter` should not
    pre-empt 013's memory-boundary decisions; keep them behind the router seam.
  - **018** (`add_tests_for_architecture_boundaries`) — new unit tests for the
    extracted builder/persister feed into 018.
- **Downstream:** nothing in the graph lists 011 as a prerequisite for another
  subtask, but 011 unblocks the future ReAct-loop unification (deferred here).

---

## 16. Risk Level

**Changes runtime code: Yes.** **Risk: High.**

Rationale: `agent/loop.py` (1630 LOC) and `bfts.py` (845 LOC) sit on the hottest
control path of every ARI run; the `run` method is a single ~1170-line body with
tight coupling and test monkeypatch surfaces. The refactor is mechanically large and
touches the composition root. Risk is mitigated by: additive-only signatures,
re-export shims, golden-string tests for `BFTSPromptBuilder`, a two-PR split
(Protocols/builder first, `AgentLoop` decomposition second), and a broad existing
test set (14+ `test_bfts*/test_run_loop/test_orchestrator/test_agent*/test_react*`
files) that pins current behavior.

---

## 17. Notes for Implementer

- **Verify line anchors before editing** — the cited line numbers (e.g. `expand`
  L577, router L950–1318) are from the 2026-07-01 snapshot; `agent/loop.py` in
  particular has churned recently (`git log -- ari-core/ari/agent/loop.py`). Re-grep
  for the method/marker rather than trusting absolute lines.
- **Golden-string test first.** Before moving the `expand` serialization, capture the
  current `expand` prompt string for a fixed `(node, siblings, ...)` fixture and
  assert the builder reproduces it exactly. This is the single most important guard
  against silent behavioral drift (P2 determinism).
- **Only `BFTS` constructs the LLM calls.** Keep `self.llm.complete` (L485/564/762)
  inside `BFTS`; the builder returns *strings*, not responses. Do not let the builder
  acquire an LLM handle.
- **Keep `_PromptBudget` truncation semantics.** It centralizes context-window limits
  (`bfts.py:26–37`); moving it must not change any of the char/list caps.
- **Cross-layer reaches stay isolated, not removed.** `ari_skill_memory.backends`
  (loop.py L1047) and `ari.pipeline._extract_plan_sections` (L1061/1118) are pushed
  behind `ToolResultRouter`; do not attempt to sever the core→skill edge here — that
  is subtask 013's decision.
- **Do not merge `react_driver.py`.** It is a separate, cleaner ReAct loop consumed by
  the pipeline; unification is REVIEW_REQUIRED and out of scope. Just note it in the
  013 reference report.
- **No `sonfigs/`.** The "config/configs/sonfigs" trio in the master prompt is a
  hypothesized typo; only `ari-core/ari/config/` (code), `ari-core/ari/configs/`
  (packaged data), and top-level `config/` (rubric data) exist. This subtask touches
  none of them.
- **Composition root caveat.** `core.py::build_runtime` also carries unrelated
  concerns (`_load_rubric_dict_for_axes` L23, `_make_metric_spec` L62,
  `generate_paper_section` L235); leave them for their owning subtasks — only thread
  the new Protocol type hints and optional `node_store` through here.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **011** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
