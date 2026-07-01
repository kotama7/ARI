# Subtask 009: Extract Evaluator Interface

> Phase 3: Core Architecture · Risk: Medium · Runtime code change: **Yes** · Depends on: 007
>
> Planning document only. Nothing here modifies runtime code; it hands a fresh
> coding session an executable plan. All paths are repository-real and verified
> against the tree at planning date 2026-07-01 (ari-core 0.9.0, branch `main`).

## 1. Goal

Formalize the **core evaluator interface** so that `AgentLoop` and the BFTS
orchestrator depend on a *structural contract* (`ari.protocols.Evaluator`) rather
than on the concrete `ari.evaluator.llm_evaluator.LLMEvaluator`. Concretely:

1. Make the `Evaluator` Protocol (`ari-core/ari/protocols/evaluator.py`, 40 LOC)
   describe the **full** contract the runtime actually uses — today it only
   declares the async `evaluate(...)`, but the sole consumer (`AgentLoop`) calls
   `evaluate_sync(...)` and mutates `evaluator.metric_spec`.
2. **Adopt** the Protocol at the injection seam: `AgentLoop.__init__` currently
   types `evaluator: object | None = None` (`ari-core/ari/agent/loop.py:372`).
   Retype it to `Evaluator | None` so the contract is checked at the boundary and
   test stubs / alternative evaluators plug in without subclassing.
3. Keep `LLMEvaluator` as the single canonical concrete implementation (it must
   continue to satisfy the Protocol *structurally* — no forced subclassing).

The deliverable is "Formalized `Evaluator` interface" (per
`docs/refactoring/007_subtask_index.md:56`): a complete, adopted Protocol plus the
seam retype, with zero behavior change and all evaluator tests green.

## 2. Background

- Subtask **007** (`define_core_interfaces_and_protocols`) established the
  `ari/protocols/` package as a deliberate Protocol home. Its `__init__.py`
  docstring names the roadmap (`LLMClient, MCPClient, MemoryClient, NodeStore,
  StageRunner` "land in subsequent phases") and already exposes `Evaluator`,
  `PromptLoader`, `ConfigLoader` (`ari-core/ari/protocols/__init__.py:19-23`).
- `Evaluator` was introduced in Phase PC6 as a `@runtime_checkable Protocol`
  (`ari-core/ari/protocols/evaluator.py:18-40`) with the intent that
  `AgentLoop` / BFTS "can swap in alternative implementations (e.g. regex-only
  extractor for tests, peer-review LLM for real runs) without inheriting from the
  concrete class." That intent is only *partly* realized: the Protocol exists and
  is exported, but nothing in the runtime is annotated with it — a repo-wide grep
  for `: Evaluator` / `-> Evaluator` finds **no** production annotation outside the
  Protocol definition itself.
- The concrete evaluator lives in `ari-core/ari/evaluator/` (3 py, 1261 LOC):
  `llm_evaluator.py` (723 LOC, class `LLMEvaluator` at `:240`), `dynamic_axes.py`
  (516 LOC), `__init__.py` (exports `LLMEvaluator`, `MetricSpec`).
- This subtask is a Phase-3 sibling of 008 (`extract_model_backend_interface`),
  010–014. Per the dependency graph, all fan out from 007. 009 is scoped narrowly
  to the *evaluator* seam and does **not** touch the LLM backend (008) or the
  BFTS/ReAct split (011).

## 3. Scope

In scope:

- Extend the `Evaluator` Protocol in `ari-core/ari/protocols/evaluator.py` to cover
  the **actual** runtime contract: the sync entry point `evaluate_sync(...)` and the
  mutable `metric_spec` attribute, in addition to the existing async `evaluate(...)`.
- Retype the injection seam(s): `AgentLoop.__init__`'s `evaluator` parameter
  (`ari-core/ari/agent/loop.py:372`) and, if a local annotation exists, the
  `evaluator` local in `ari-core/ari/core.py:195`.
- Add/confirm a lightweight structural conformance assertion (test-level) that
  `LLMEvaluator` satisfies `Evaluator` via `isinstance(..., Evaluator)`
  (`@runtime_checkable`).
- Update the two READMEs / module docstrings that describe the Protocol
  (`ari-core/ari/protocols/README.md`, `ari-core/ari/protocols/__init__.py`,
  `ari-core/ari/protocols/evaluator.py` docstring) to reflect the completed contract.

Out of scope (see Non-Goals): composite-function refactor, LLM-routing change,
skill evaluator (`ari-skill-evaluator`) changes, config schema changes.

## 4. Non-Goals

- **Do not** introduce a `BaseEvaluator` ABC or force `LLMEvaluator` to subclass
  anything. The Protocol is structural by design; keeping `LLMEvaluator` concrete
  and unsubclassed is a stated goal of the PC6 design.
- **Do not** introduce a `BaseCompositeEvaluator` class hierarchy. The composites
  are plain functions in the `_COMPOSITES` registry
  (`ari-core/ari/evaluator/llm_evaluator.py:165-170`); KEEP them as-is. Turning them
  into classes is over-engineering and out of scope.
- **Do not** fix the `LLMEvaluator.evaluate` → `litellm.acompletion` direct-call
  concern (`llm_evaluator.py:585`). Routing the judge through `LLMClient` /
  `BaseModelBackend` is subtask **008**'s responsibility; 009 must leave the call
  site byte-identical.
- **Do not** change `EvaluatorConfig` (`ari-core/ari/config/__init__.py:204`) or its
  `composite` / `axis_mode` fields — that surface is re-exported as **public API**
  via `ari.public.config_schema` and is a contract.
- **Do not** touch `ari-skill-evaluator/src/server.py` (983 LOC). The MCP skill
  evaluator (`make_metric_spec`, `claim_evidence_hard_gate`,
  `evidence_grounded_semantic_review`) is a *separate* component with its own MCP
  tool contract; the core `Evaluator` interface is distinct from it.
- No changes to dynamic-axis behavior, prompts, checkpoint format, or dashboard API.

## 5. Current Files / Directories to Inspect

Protocol / interface surface:

- `ari-core/ari/protocols/evaluator.py` (40 LOC) — `Evaluator` `@runtime_checkable`
  Protocol; single async method `evaluate(goal, artifacts, summary, node_id=None,
  node_label=None) -> dict[str, Any]` (`:29-40`).
- `ari-core/ari/protocols/__init__.py` (23 LOC) — exports `Evaluator`,
  `PromptLoader`, `ConfigLoader`; roadmap docstring (`:14-16`).
- `ari-core/ari/protocols/README.md` (16 LOC) — points at the `__init__` docstring
  as authoritative.

Concrete implementation:

- `ari-core/ari/evaluator/llm_evaluator.py` (723 LOC):
  - `class LLMEvaluator` (`:240`); `__init__` (`:265`, keyword args `model,
    api_base, metric_spec, axis_weights, axes, *, checkpoint_dir, rubric,
    composite="harmonic_mean"`).
  - `async def evaluate(...)` (`:548-555`) — matches the Protocol shape today.
  - `def evaluate_sync(...)` (`:498-505`) — the method actually called by
    `AgentLoop`; **not** on the Protocol.
  - `_COMPOSITES: dict[str, callable]` (`:165-170`); `MetricSpec` dataclass
    (`:179`, mutated by `AgentLoop`); `AXIS_NAMES` (`:31`); `_default_scorer`
    (`:173`).
- `ari-core/ari/evaluator/dynamic_axes.py` (516 LOC) — axis derivation
  (`build_axes_for_run`, `AxisDef`); consumed via `axes=`/`rubric=` ctor args.
- `ari-core/ari/evaluator/__init__.py` (22 LOC) — `from .llm_evaluator import
  LLMEvaluator, MetricSpec`.
- `ari-core/ari/evaluator/README.md`.

Consumers / injection seams:

- `ari-core/ari/agent/loop.py` — `AgentLoop.__init__` `evaluator: object | None =
  None` (`:372`), stored `self.evaluator = evaluator` (`:380`). Runtime calls:
  `self.evaluator.evaluate_sync(...)` at `:1454`, `:1532`, `:1600`; mutation
  `self.evaluator.metric_spec = MetricSpec(...)` at `:1190`.
- `ari-core/ari/core.py:195` — constructs `LLMEvaluator(...)` and injects it into
  `AgentLoop(..., evaluator=evaluator, ...)` (`:219`).
- `ari-core/ari/config/__init__.py:204` — `EvaluatorConfig` (`composite` Literal at
  `:212-226`; `axis_mode` at `:227-233`). **Read-only for this subtask.**
- `ari-core/ari/public/config_schema.py:14,24` — public re-export of
  `EvaluatorConfig`. **Read-only for this subtask.**

Tests grounding the contract:

- `ari-core/tests/test_dynamic_axes.py` (584), `test_bfts_diversity.py` (418),
  `test_bfts_eval_config_integration.py` (260), `test_llm_evaluator_axes.py` (169),
  `test_evaluator_composite.py` (102), `test_evaluator_axis_mode.py` (48).
- `ari-core/tests/test_laptop_hpc_skill_drop.py:99` — patches
  `ari.evaluator.LLMEvaluator` with a stub `_StubEval` (proves the seam is already
  stubbed in tests; the retype must not reject such stubs).

## 6. Current Problems

1. **The Protocol under-specifies the real contract.** `Evaluator` declares only
   the async `evaluate(...)` (`protocols/evaluator.py:29`). But the sole runtime
   consumer, `AgentLoop`, never calls `evaluate`; it calls the **sync** wrapper
   `evaluate_sync(...)` (`loop.py:1454, 1532, 1600`) and additionally **mutates**
   `evaluator.metric_spec` (`loop.py:1190`). A stub that satisfies the current
   Protocol would still crash `AgentLoop`. The interface therefore does not
   describe what an evaluator must provide.
2. **The Protocol is defined but not adopted.** The injection point types the
   dependency as `evaluator: object | None = None` (`loop.py:372`), so the compiler
   / type-checker verifies nothing at the seam. A grep for `: Evaluator` /
   `-> Evaluator` finds no production annotation outside the Protocol module — the
   PC6 goal ("AgentLoop / BFTS can swap in alternative implementations") is only
   documented, not enforced.
3. **`metric_spec` is an undocumented part of the contract.** `AgentLoop` reaches
   into `self.evaluator.metric_spec` and reassigns it (`loop.py:1190`), yet the
   Protocol says nothing about a `metric_spec` attribute. Any conforming evaluator
   must expose a settable `metric_spec`, which is currently only discoverable by
   reading the loop.
4. **No structural-conformance test exists.** Nothing asserts that `LLMEvaluator`
   actually satisfies `Evaluator`. Because the Protocol is `@runtime_checkable`, a
   one-line `isinstance` check would lock this in, but it is absent.
5. **`Evaluator` return dict is only prose-documented.** The contract keys
   (`score, reason, has_real_data, has_paper_section, metrics`, plus the composite
   `metrics["_scientific_score"]`) live in docstrings and the concrete
   implementation, not in a typed structure. (Typing the dict is optional; see
   §7 — a `TypedDict` may be introduced but is not required.)

## 7. Proposed Design / Policy

Classification: `Evaluator` Protocol = **ADAPT** (extend to the full runtime
contract, backward-compatibly). `LLMEvaluator` = **KEEP** (concrete, unsubclassed).
`_COMPOSITES` function registry = **KEEP**. `AgentLoop.evaluator: object`
annotation = **ADAPT** (→ `Evaluator | None`). `EvaluatorConfig` /
`ari.public.config_schema` = **KEEP** (untouched public contract).

### 7.1 Complete the `Evaluator` Protocol

Extend `ari/protocols/evaluator.py` so the Protocol matches actual usage. Add the
sync entry point and the mutable attribute; keep the existing async method:

```python
@runtime_checkable
class Evaluator(Protocol):
    # Mutable per-run domain spec; AgentLoop reassigns this (loop.py:1190).
    metric_spec: Any  # a MetricSpec; kept loosely typed to avoid an import cycle

    async def evaluate(
        self, goal: str, artifacts: list[dict], summary: str,
        node_id: str | None = None, node_label: str | None = None,
    ) -> dict[str, Any]: ...

    def evaluate_sync(
        self, goal: str, artifacts: list[dict], summary: str,
        node_id: str | None = None, node_label: str | None = None,
    ) -> dict[str, Any]: ...
```

Notes:
- Keep it `@runtime_checkable`. Protocol attribute members participate in
  `isinstance` only by name presence, which is sufficient here.
- Type `metric_spec` loosely (`Any`) to avoid importing `MetricSpec` from
  `ari.evaluator` into `ari.protocols` (that would create a core→core dependency
  from the interface layer back into an implementation layer, defeating the point
  of the Protocol package). Alternatively, use `TYPE_CHECKING`-guarded import for
  editor hints only.
- **Optional** (nice-to-have, not required): introduce an `EvaluationResult`
  `TypedDict` (`total=False`) in the Protocol module capturing `score, reason,
  has_real_data, has_paper_section, metrics` and reference it as the return type.
  If added, it must be `total=False` so existing callers that read subsets keep
  type-checking.

### 7.2 Adopt the Protocol at the seam

- `ari/agent/loop.py:372`: change `evaluator: object | None = None` to
  `evaluator: "Evaluator | None" = None`, importing `Evaluator` under
  `TYPE_CHECKING` (to avoid any import-time cost / cycle) or at module top if the
  import graph is clean. Runtime behavior is unchanged — the annotation is
  advisory; `self.evaluator is not None` guards remain.
- `ari/core.py:195`: the local `evaluator` is already a concrete `LLMEvaluator`;
  no functional change. Optionally add `evaluator: "Evaluator"` annotation for
  documentation. Do not change construction.

### 7.3 Keep the composite registry and skill evaluator as-is

- `_COMPOSITES` stays a `dict[str, callable]` of module functions
  (`weighted_harmonic_mean` etc.). Its keys must remain in sync with
  `EvaluatorConfig.composite` (the Literal at `config/__init__.py:212`); this
  subtask does not touch either side of that sync, only preserves it.
- The MCP `ari-skill-evaluator` server is untouched. The core `Evaluator` Protocol
  is explicitly the *in-core BFTS judge* contract, not the skill tool contract.

### 7.4 Compatibility posture

The Protocol change is purely additive; `LLMEvaluator` already implements
`evaluate`, `evaluate_sync`, and `metric_spec`, so it continues to satisfy the
extended Protocol with **no implementation edits**. Test stubs that only implement
what `AgentLoop` calls will now be validated against a Protocol that matches those
same calls, so no existing stub breaks (e.g. `test_laptop_hpc_skill_drop.py`'s
`_StubEval`, which is patched in via `monkeypatch.setattr`, is not
`isinstance`-checked at the seam and remains valid).

## 8. Concrete Work Items

1. **Extend the Protocol** (`ari-core/ari/protocols/evaluator.py`): add
   `evaluate_sync(...)` with the exact signature of `LLMEvaluator.evaluate_sync`
   (`llm_evaluator.py:498-505`) and declare the `metric_spec` attribute member.
   Update the class docstring to state that `evaluate_sync` is the entry point used
   by `AgentLoop` and that `metric_spec` is reassigned per-run.
2. **(Optional) Add `EvaluationResult` TypedDict** in the same module and reference
   it from both method return types; keep `total=False`.
3. **Retype the seam** (`ari-core/ari/agent/loop.py:372`): `evaluator: object |
   None` → `evaluator: "Evaluator | None"`; add a `TYPE_CHECKING` import
   `from ari.protocols import Evaluator`. Confirm no runtime import cycle
   (`ari.agent.loop` already imports many `ari.*` modules; `ari.protocols` is
   dependency-light — verify with `python -c "import ari.agent.loop"`).
4. **Optionally annotate** `ari-core/ari/core.py:195` local `evaluator` for
   documentation; no construction change.
5. **Add a conformance test** (new test in `ari-core/tests/`, e.g.
   `test_evaluator_protocol.py`): assert
   `isinstance(LLMEvaluator(model="dummy"), Evaluator)` is `True`, and assert a
   minimal stub exposing `evaluate`, `evaluate_sync`, `metric_spec` also passes,
   while a stub missing `evaluate_sync` fails `isinstance`. This locks the extended
   contract.
6. **Docs sync**: update `ari-core/ari/protocols/__init__.py` docstring bullet for
   `Evaluator` (`:10`) and `ari-core/ari/protocols/README.md` to note the contract
   now includes `evaluate_sync` + `metric_spec`. Run the docs coupling checks (§12)
   because these are tracked files.
7. **Verify no behavior drift**: run the full evaluator test set (§12) and confirm
   identical pass counts pre/post.

## 9. Files Expected to Change

- `ari-core/ari/protocols/evaluator.py` — extend Protocol (add `evaluate_sync`,
  `metric_spec`, optional `EvaluationResult`).
- `ari-core/ari/protocols/__init__.py` — docstring bullet refresh (no export
  change unless `EvaluationResult` is added, in which case add it to `__all__`).
- `ari-core/ari/protocols/README.md` — description refresh.
- `ari-core/ari/agent/loop.py` — retype `evaluator` param at `:372`; add
  `TYPE_CHECKING` import of `Evaluator`.
- `ari-core/ari/core.py` — (optional) annotate local `evaluator` at `:195`.
- `ari-core/tests/test_evaluator_protocol.py` — **new** conformance test.

Explicitly **not** changing: `ari-core/ari/evaluator/llm_evaluator.py`,
`ari-core/ari/evaluator/dynamic_axes.py`, `ari-core/ari/config/__init__.py`,
`ari-core/ari/public/config_schema.py`, `ari-skill-evaluator/**`.

## 10. Files / APIs That Must Not Be Broken

- **`ari.public.config_schema.EvaluatorConfig`** (public Python API) — untouched;
  `composite` Literal and `axis_mode` values must remain identical.
- **`_COMPOSITES` keys ↔ `EvaluatorConfig.composite` Literal** invariant — preserve
  (`harmonic_mean`, `arithmetic_mean`, `weighted_min`, `geometric_mean`).
- **`from ari.evaluator import LLMEvaluator, MetricSpec`** — the tests and `core.py`
  rely on these; import surface must not change.
- **Evaluator result-dict shape** returned by `evaluate`/`evaluate_sync`
  (`score, reason, has_real_data, has_paper_section, metrics`, incl.
  `metrics["_scientific_score"]`) — consumed by `AgentLoop`, BFTS scoring, and the
  dashboard. Do not alter keys or types.
- **`AgentLoop(..., evaluator=...)` call contract** — `core.py:219` passes
  `evaluator=` by keyword; the parameter name and default (`None`) must stay.
- **CLI `ari`, MCP `ari-skill-*` tool contracts, dashboard API endpoints/schema,
  checkpoint/output/config file formats** — none are touched by this subtask;
  verify no incidental drift.
- **`ari-skill-evaluator` MCP tools** (`make_metric_spec`,
  `claim_evidence_hard_gate`, `evidence_grounded_semantic_review`) — separate
  contract, not in scope.

## 11. Compatibility Constraints

- Changes are **purely additive and advisory**: extending a `@runtime_checkable`
  Protocol and adding type annotations does not alter runtime dispatch. No
  compatibility adapter is required because no external contract changes.
- `metric_spec` is declared loosely (`Any`) in the Protocol to avoid an
  interface→implementation import cycle (`ari.protocols` must not import
  `ari.evaluator`). Enforce this: a new import edge from `ari/protocols/` into
  `ari/evaluator/` is a regression and must be rejected.
- The retyped `evaluator` param keeps `| None` and the `is not None` guards in
  `AgentLoop`, so injecting `None` (evaluator disabled) still works exactly as
  today.
- No `pyproject.toml`, `requirements*.txt`, workflow, or prompt file changes. There
  is **no** top-level `pyproject.toml`; the core manifest is
  `ari-core/pyproject.toml` and is not touched. (The prompt's "sonfigs" directory
  does not exist in this repo and is irrelevant here.)

## 12. Tests to Run

From repo root (`/home/t-kotama/workplace/ARI`):

- `python -m compileall ari-core/ari/protocols ari-core/ari/agent ari-core/ari/core.py`
  (fast syntax gate) and, before merge, `python -m compileall .`
- `ruff check .` (ruff is available; radon is not — no complexity gate here).
- `pytest -q ari-core/tests/test_dynamic_axes.py
  ari-core/tests/test_bfts_diversity.py
  ari-core/tests/test_bfts_eval_config_integration.py
  ari-core/tests/test_llm_evaluator_axes.py
  ari-core/tests/test_evaluator_composite.py
  ari-core/tests/test_evaluator_axis_mode.py
  ari-core/tests/test_laptop_hpc_skill_drop.py
  ari-core/tests/test_evaluator_protocol.py`
- `pytest -q` (full core suite; the large suites `test_server.py`,
  `test_workflow_contract.py`, `test_wizard.py`, `test_gui_errors.py` exercise the
  AgentLoop seam indirectly — confirm no regression).
- Docs/coupling guards for the tracked doc edits:
  `python scripts/docs/check_ref_coupling.py` and
  `python scripts/docs/check_doc_sources.py` (the `protocols/README.md` and
  docstring edits are the reason these matter). Confirm the `refactor-guards.yml`
  invariant still holds (no new `~/.ari` references; tests run under a redirected
  `HOME`).
- No frontend change → **no** `npm test` / `npm run build` required for this
  subtask.

## 13. Acceptance Criteria

1. `ari.protocols.Evaluator` declares `evaluate`, `evaluate_sync`, and
   `metric_spec`; `import ari.protocols` succeeds with no import cycle.
2. `isinstance(LLMEvaluator(model="dummy"), Evaluator)` is `True`
   (new `test_evaluator_protocol.py` passes), and a stub missing `evaluate_sync`
   fails the same check.
3. `AgentLoop.__init__`'s `evaluator` parameter is annotated `Evaluator | None`;
   `AgentLoop(..., evaluator=None)` and `AgentLoop(..., evaluator=<stub>)` both
   still work (existing tests unchanged).
4. All evaluator tests in §12 pass with the **same** pass counts as the pre-change
   baseline; no test needed modification to keep passing.
5. `python -m compileall .` and `ruff check .` are clean.
6. `ari-core/ari/evaluator/llm_evaluator.py` has **zero** diff (implementation
   untouched); `EvaluatorConfig` / `ari.public.config_schema` have zero diff.
7. Docs guards (`check_ref_coupling.py`, `check_doc_sources.py`) pass for the
   `protocols/` doc edits.

## 14. Rollback Plan

The change set is small and additive. Rollback is `git revert` of the single
commit (or manual reversal of the ≤5 touched files):

1. Restore `evaluator: object | None = None` at `ari/agent/loop.py:372` and drop
   the `TYPE_CHECKING` import.
2. Restore `ari/protocols/evaluator.py` to the 40-LOC single-method Protocol.
3. Revert the `protocols/__init__.py` / `README.md` docstring bullets.
4. Delete `ari-core/tests/test_evaluator_protocol.py`.

No data/format migration is involved, so rollback is risk-free and requires only
re-running §12. Because `LLMEvaluator` was never edited, reverting the Protocol
cannot break the runtime.

## 15. Dependencies

- **Hard prerequisite: 007** (`define_core_interfaces_and_protocols`). Per the
  dependency graph (`007 -> 008, 009, 010, 011, 012, 013, 014`), 009 must run after
  007 lands the `ari/protocols/` package conventions. In this repo 007's substrate
  already exists (the `Evaluator` Protocol is present), so 009 is largely an
  *extend + adopt* of 007's output.
- **Inventory gating.** 009 changes runtime code (Runtime Code Change = Yes,
  `007_subtask_index.md:56`). The global ordering requires the read-only inventory
  subtasks — **001, 002, 020, 036, 045, 053, 059, 060, 067** — to precede any
  runtime code change; ensure those are complete before executing 009.
- **Sibling coordination (not a graph edge): 008**
  (`extract_model_backend_interface`). 008 addresses `LLMEvaluator.evaluate`'s
  direct `litellm.acompletion` call (`llm_evaluator.py:585`). 009 deliberately does
  not touch that call, but if 008 lands first the evaluator's LLM path may route
  through `LLMClient`; either order is safe because 009 changes only the interface
  and annotations, not the call site. No hard edge between 008 and 009 exists in
  the graph.
- **Downstream:** 009 has no dependents in the graph (it is a leaf under 007).

## 16. Risk Level

**Medium** (matches `007_subtask_index.md:56`). **Runtime code change: Yes** — but
narrow and additive: it retypes one function parameter and extends a
`@runtime_checkable` Protocol; it does not alter dispatch, data, or any public
contract. The main risks are (a) accidentally creating an `ari.protocols →
ari.evaluator` import cycle (mitigated by the `Any`/`TYPE_CHECKING` policy in §7.1)
and (b) an over-strict `isinstance` conformance test that rejects legitimate test
stubs (mitigated by declaring only the members `AgentLoop` truly uses). Both are
caught by §12.

## 17. Notes for Implementer

- The single most important correction is that **`evaluate_sync`, not `evaluate`,
  is the method the runtime calls** (`loop.py:1454, 1532, 1600`). A Protocol that
  omits it is worse than useless — it validates the wrong shape. Add it.
- Do not import `MetricSpec` into `ari/protocols/evaluator.py`. Keep `metric_spec:
  Any` (or a `TYPE_CHECKING` import). The Protocol package must remain free of
  dependencies on implementation modules; this is what lets it be the seam.
- `LLMEvaluator(model="dummy")` constructs without any network (the tests use
  `model="dummy"`/`"test"`/`"stub"` throughout, e.g.
  `test_evaluator_composite.py:95`), so the `isinstance` conformance test needs no
  mocking of litellm.
- Leave `_COMPOSITES` and `EvaluatorConfig` alone. If you find yourself editing
  `llm_evaluator.py` or `config/__init__.py`, you have exceeded this subtask's
  scope — stop and re-read §4.
- The `ari-skill-evaluator` MCP server (983 LOC, separate package) is a red
  herring for this subtask: correctness/cost scoring lives there, but the *core*
  BFTS-judge `Evaluator` interface is what 009 formalizes. Do not conflate them.
- Confirm no `Evaluator` type annotation exists elsewhere before you start (grep
  `: Evaluator` / `-> Evaluator`): today the only match outside the Protocol module
  is the unrelated `EvaluatorConfig` field, so your retype at `loop.py:372` is the
  first real adopter.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **009** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
