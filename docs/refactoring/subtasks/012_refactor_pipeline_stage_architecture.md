# Subtask 012: Refactor Pipeline Stage Architecture

> Phase 3: Core Architecture · Depends on 007 · Risk: High · Runtime code change: **Yes** (when implemented)
>
> This document is a **planning artifact only**. Writing it changes no runtime
> code. It describes the work a later implementation session will perform.

## 1. Goal

Introduce a first-class **stage abstraction** and **workflow driver** for the
post-BFTS pipeline so that the single 913-LOC imperative loop in
`ari-core/ari/pipeline/orchestrator.py` (`run_pipeline`, defined at
`orchestrator.py:155`, stage loop at `:539-911`) is decomposed into:

- a `BasePipelineStage` interface with two subclasses (`SubprocessMCPStage`,
  `ReActStage`) that own one YAML-declared stage's lifecycle
  (`resolve_inputs → should_skip → run → persist_outputs → evaluate_loopback`);
- a `WorkflowDriver` that owns the index-based cursor loop, the shared
  `tpl_vars` / `stage_outputs` state, the loop-back rewind, and the pre-flight
  (cost-tracker init, `nodes_tree.json` load, verified-context wiring, BFTS
  sanity gate).

The refactor is **behavior-preserving**: the same `config/workflow.yaml`
(629 LOC, ~30 stages) drives the same stage sequence, `generate_paper_section`
remains the entry point, and every currently-passing pipeline test keeps
passing without edits to its assertions.

## 2. Background

The pipeline is **100% data-driven from YAML** — there are **no stage classes
today** (confirmed by inspection). A "stage" is a plain `dict` parsed from the
`pipeline:` list in `ari-core/config/workflow.yaml`. Loaders live in
`ari/pipeline/yaml_loader.py`: `load_pipeline()` (`:29`) returns stages with
`enabled != false`; `load_disabled_stage_names()` (`:43`) returns the
complement; `load_workflow()` (`:64`); `_resolve_templates()` (`:84`) does regex
`{{var}}` substitution with dot-notation (**not Jinja** — no filters/defaults).

Execution is a single imperative index-based loop in
`ari/pipeline/orchestrator.py`. Per stage the loop hand-rolls, inline:
`disabled_tools` skip (`:561`), `depends_on` resolution (`:571`),
`skip_if_exists` (`:604`), input/param template resolution (`:627`),
tool-specific fallback injection with hardcoded sets `_paper_tools` /
`_metrics_tools` (`:656-657`), dispatch (`:691` forks on `stage_cfg.get("react")`),
output persistence with **type-sniffing side effects** (`.tex → result["latex"]`,
`.pdf →` copy-if-distinct via `_copy_stage_output_if_distinct` at `:132`,
persistence block `:757-801`), a special-cased `generate_figures` manifest
branch (`:813-826`), and `loop_back_to` cursor rewind with VLM-feedback
injection (`:831-901`). There is no stage object, no registry, no state value
object — `tpl_vars` and `stage_outputs` dicts are threaded manually.

Two dispatch modes exist in `ari/pipeline/stage_runner.py` (471 LOC):

- **Subprocess MCP call** (default): `_run_stage_subprocess` (`:331`) builds a
  Python child script via **string concatenation** (`:367-404`), passes call
  args through a temp JSON file, and spawns `sys.executable -c` (`:449`). Fresh
  process per stage.
- **ReAct stage** (`stage_cfg["react"]`): `_run_react_stage` (`:51`) runs
  `pre_tool → run_react → post_tool` and installs sandbox git-shims. **This path
  is dormant in the shipped config**: `grep -c 'react:' config/workflow.yaml`
  returns `0` (verified). It is exercised only by tests / per-checkpoint YAML.

A **Phase 3C split already happened**: the old ~1640-line `ari/pipeline.py`
module was broken into the `ari/pipeline/` package (see `ari/pipeline/__init__.py`
docstring). That split was **file-level only** — it moved helpers into sibling
modules and re-exported them from the package root, but it did **not** introduce
any stage/driver classes. Subtask 012 is the follow-on that introduces the
missing abstractions. The `ari/pipeline/__init__.py` re-exports and the
lazy-delegator functions (`_run_react_stage` / `_run_stage_subprocess` at
`orchestrator.py:42-56`) exist **specifically to keep test monkeypatch surfaces
stable**; 012 must preserve that guarantee.

Subtask 007 (`define_core_interfaces_and_protocols`) is the prerequisite: the
`ari/protocols/` package already names `StageRunner` as a protocol that "lands
in subsequent phases" (`ari/protocols/__init__.py:15`). 012 is the adopter that
turns that named-but-absent protocol into a concrete class hierarchy.

## 3. Scope

In scope (implementation phase, not this doc):

- Add `BasePipelineStage` (interface) + `SubprocessMCPStage` and `ReActStage`
  subclasses inside the `ari/pipeline/` package.
- Add a `WorkflowDriver` (or `BaseWorkflowDriver`) that owns the cursor loop and
  shared state, replacing the inline loop body of `run_pipeline`.
- Add a `StageContext` value object to eliminate manual `tpl_vars` /
  `stage_outputs` dict threading.
- Move the type-sniffing output writer (`orchestrator.py:757-826`) and the
  `_copy_stage_output_if_distinct` helper into `SubprocessMCPStage.persist()` /
  a shared `OutputSink`.
- Keep `run_pipeline`, `build_scientific_data`, `load_pipeline`, `load_workflow`,
  `_resolve_templates`, `_should_loop_back`, `_format_vlm_feedback`,
  `_run_stage_subprocess`, `_run_react_stage`, `_call_with_retry` importable from
  `ari.pipeline` (thin wrappers delegating to the new classes).
- Optionally collapse the 3+ duplicated `config/workflow.yaml` discovery sites
  behind a single `WorkflowLocator` helper (see Section 7 for the reach concern).

Out of scope: everything in Section 4.

## 4. Non-Goals

- Do **not** change `config/workflow.yaml` semantics, stage names, ordering, or
  the `{{var}}` template dialect. The YAML remains the contract.
- Do **not** add a Jinja engine or new template features.
- Do **not** revive or re-enable the ReAct path in the shipped config; keep it
  supported but dormant (it must still work for tests / per-checkpoint YAML).
- Do **not** unify the separate ORS/PaperBench worker runner
  (`viz/api_paperbench_worker.py:168 _run_pipeline`, its docstring: "Drive the
  four-stage pipeline") into this driver in 012. That merge is a follow-on
  (candidate: a dedicated viz subtask); note it but leave it running.
- Do **not** resolve the `core → viz` back-edge (`cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment`) here; flag it as
  REVIEW_REQUIRED for a dependency-boundary subtask.
- Do **not** rename directories, move packages, or touch prompts, configs
  (other than optional locator dedup), MCP servers, or the frontend.
- Do **not** delete the lazy-delegator monkeypatch shims; they are load-bearing
  for tests (KEEP).

## 5. Current Files / Directories to Inspect

Primary target package — `ari-core/ari/pipeline/` (verified LOC):

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/pipeline/orchestrator.py` | 913 | `run_pipeline` (def `:155`, loop `:539-911`), `build_scientific_data`, sanity gate `:505-537`, output persistence `:757-826`, loop-back `:831-901`, lazy delegators `:42-56` |
| `ari-core/ari/pipeline/stage_runner.py` | 471 | `_run_react_stage` (`:51`), `_run_stage_subprocess` (`:331`, string-concat script build `:367-404`, subprocess spawn `:449`), `_call_with_retry` (`:33`) |
| `ari-core/ari/pipeline/yaml_loader.py` | 103 | `load_pipeline` (`:29`), `load_disabled_stage_names` (`:43`), `load_workflow` (`:64`), `_resolve_templates` (`:84`) |
| `ari-core/ari/pipeline/stage_control.py` | 68 | `_should_loop_back`, `_format_vlm_feedback` (pure helpers) |
| `ari-core/ari/pipeline/context_builder.py` | 140 | `build_best_nodes_context`, `_extract_keywords_from_nodes` |
| `ari-core/ari/pipeline/experiment_md.py` | 177 | `_promote_plan_to_experiment_md`, `_extract_plan_sections`, `parse_metric_from_experiment_md` |
| `ari-core/ari/pipeline/verified_context.py` | 135 | artifact-grounded verified context (exposed via `ari.public.verified_context`) |
| `ari-core/ari/pipeline/__init__.py` | 67 | sub-module map + public re-exports (the stable `ari.pipeline` surface) |
| `ari-core/ari/pipeline/claim_gate/` | dir | deterministic `claim_evidence_hard_gate`; **do not touch** in 012 |
| `ari-core/ari/pipeline/README.md` | 42 | package doc (update after refactor) |

Contract / entry / coupling files:

- `ari-core/config/workflow.yaml` — 629 LOC, ~30 stages; **the contract**. Read only.
- `ari-core/ari/core.py` — entry `generate_paper_section` (`:235`), imports
  `load_pipeline, run_pipeline` (`:239`), call site (`:280`); duplicate
  `workflow.yaml` discovery (`:253-258`).
- `ari-core/ari/protocols/__init__.py` — names `StageRunner` protocol (`:15`);
  `ari/protocols/evaluator.py` is the only concrete protocol today.
- `ari-core/ari/cli/lineage.py` — duplicate `workflow.yaml` discovery
  (`:56-59`); **core→viz back-edge** at `:151` / `:167`.
- `ari-core/ari/viz/api_paperbench_worker.py` — separate `_run_pipeline` (`:168`,
  four-stage ORS worker), thread launch (`:313`). Out of scope but read for
  context so the two runners are not accidentally merged.
- Config-discovery duplication to (optionally) collapse:
  `core.py:253-258`, `orchestrator.py:330-333`, `cli/lineage.py:56-59`.

## 6. Current Problems

1. **God function.** `run_pipeline` is 913 LOC; its stage loop (`:539-911`)
   inlines eight distinct concerns (disabled/depends/skip checks, template
   resolution, fallback-arg injection, dispatch fork, output persistence,
   figures special-case, loop-back rewind). No unit can be tested in isolation.
2. **No stage abstraction.** Adding a stage type or altering persistence means
   editing the monolith. The dispatch fork is a bare
   `if stage_cfg.get("react")` at `:691`.
3. **Type-sniffing side effects.** Output handling branches on filename suffix
   (`.tex`, `.pdf`, `.png`/`.jpg`) at `:757-801` and special-cases
   `generate_figures` / `"figures" in stage_name` at `:813-826`. This logic is
   opaque and duplicated conceptually with the skill tools that also write files.
4. **Manual state threading.** `tpl_vars` and `stage_outputs` dicts are passed
   and mutated by hand throughout the loop; there is no `StageContext`.
5. **Hardcoded tool sets.** `_paper_tools` and `_metrics_tools` (`:656-657`) bake
   tool names into orchestrator code, contradicting the package's stated "no
   hardcoded tool names" design (`ari/pipeline/README.md`).
6. **Duplicated workflow discovery.** Three sites re-derive `config/workflow.yaml`
   by parent-hopping `__file__` (`core.py:253-258`, `orchestrator.py:330-333`,
   `cli/lineage.py:56-59`), each with slightly different fallback lists.
7. **Dormant-but-forked ReAct path.** `_run_react_stage` is unused in shipped
   config (`grep -c 'react:' == 0`) yet forks the dispatch and carries git-shim
   setup — dead weight in the hot path that a subclass would isolate.
8. **Fragile subprocess bridge.** `_run_stage_subprocess` builds a child script
   via string concatenation (`:367-404`); correct today (args go through a temp
   JSON file) but brittle and untypable. A `SubprocessMCPStage` should own and
   encapsulate this.

## 7. Proposed Design / Policy

**Classification:** the `ari/pipeline/` package is **ADAPT** (internal refactor
behind stable re-exports), not MERGE or MOVE_TO_LEGACY. No file is a
DELETE_CANDIDATE. The `core → viz` back-edge and the duplicate ORS worker runner
are **REVIEW_REQUIRED** and deferred.

### 7.1 `BasePipelineStage` (interface)

Define (aligned with the 007 `StageRunner` protocol) an abstract stage that
encapsulates one YAML dict:

```
class BasePipelineStage:
    def __init__(self, cfg: dict, wf_cfg: dict): ...
    def should_skip(self, ctx: StageContext) -> bool         # disabled_tools + depends_on + skip_if_exists
    def resolve_inputs(self, ctx: StageContext) -> dict       # {{var}} resolution + fallback-arg injection
    def run(self, ctx: StageContext) -> Any                   # dispatch
    def persist_outputs(self, ctx: StageContext, result) -> None  # type-sniff writer + figures manifest
    def evaluate_loopback(self, ctx, result) -> str | None    # returns loop_back_to target or None
```

Subclasses:

- `SubprocessMCPStage` — wraps `_run_stage_subprocess`; owns output persistence
  and the `_paper_tools` / `_metrics_tools` fallback injection.
- `ReActStage` — wraps `_run_react_stage`; selected only when
  `cfg.get("react")` is truthy. Keeps the path dormant-by-default.

A tiny factory `make_stage(cfg, wf_cfg)` replaces the inline
`if stage_cfg.get("react")` fork (`orchestrator.py:691`).

### 7.2 `WorkflowDriver`

Owns the index-based cursor loop, `StageContext`, loop-back rewind, and
pre-flight (cost-tracker init, `nodes_tree.json` load, verified-context wiring,
BFTS sanity gate `:505-537` incl. `ARI_FORCE_PAPER` override). `run_pipeline`
becomes a thin function that builds a `WorkflowDriver` and calls `.run()`,
preserving its exact signature and return value.

### 7.3 `StageContext`

A dataclass carrying `tpl_vars`, `stage_outputs`, `checkpoint_dir`,
`config_path`, `disabled_stage_names`, and the current cursor. Replaces manual
dict threading. Mutation semantics must match the current loop exactly.

### 7.4 `OutputSink` / path handling

Extract `_copy_stage_output_if_distinct` (`:132`) and the `:757-826` writer into
an `OutputSink` used by `persist_outputs`. Preserve the exact suffix rules and
the `generate_figures` manifest schema (`{"figures", "latex_snippets",
"figure_kinds"}`).

### 7.5 `WorkflowLocator` (optional, low risk)

A single helper returning the resolved `config/workflow.yaml` path, adopted by
`core.py`, `orchestrator.py`, and `cli/lineage.py`. If adopting it in
`cli/lineage.py` risks disturbing the core→viz edge, scope the locator to the
pipeline package only and leave `cli/lineage.py` for a boundary subtask.

### 7.6 Compatibility policy

Every symbol currently re-exported from `ari.pipeline` (`__init__.py:38-66`)
and every lazy delegator (`orchestrator.py:42-56`) **must remain importable and
monkeypatchable** with identical names. New classes are additive; the functional
surface is preserved by delegation.

## 8. Concrete Work Items

1. Read 007's delivered `StageRunner` protocol and align `BasePipelineStage`'s
   method names/signatures with it.
2. Add `StageContext` dataclass (new module, e.g.
   `ari/pipeline/stage_context.py`).
3. Add `BasePipelineStage` + `SubprocessMCPStage` + `ReActStage` + `make_stage`
   (new module, e.g. `ari/pipeline/stages.py`), delegating to the existing
   `_run_stage_subprocess` / `_run_react_stage` internals.
4. Move the type-sniffing writer (`orchestrator.py:757-826`) and
   `_copy_stage_output_if_distinct` (`:132`) into an `OutputSink` used by
   `SubprocessMCPStage.persist_outputs`.
5. Move the `disabled_tools`/`depends_on`/`skip_if_exists` checks (`:561-625`)
   into `should_skip`, and the template/fallback-arg logic (`:627-680`) into
   `resolve_inputs`. Keep `_paper_tools`/`_metrics_tools` as class constants.
6. Add `WorkflowDriver` (new module, e.g. `ari/pipeline/driver.py`) owning the
   loop, pre-flight, sanity gate, and loop-back rewind.
7. Reduce `run_pipeline` in `orchestrator.py` to a thin wrapper constructing and
   running a `WorkflowDriver`; keep signature/return identical.
8. Update `ari/pipeline/__init__.py` to export the new classes **in addition to**
   the existing re-exports (never remove an existing name).
9. (Optional) add `WorkflowLocator` and adopt it in `orchestrator.py` and
   `core.py`; leave `cli/lineage.py` if it risks the viz edge.
10. Update `ari/pipeline/README.md` sub-module map to list the new modules.
11. Run the full test + lint gate (Section 12); fix only real breakages, never
    by weakening assertions.

## 9. Files Expected to Change

Modified (existing):

- `ari-core/ari/pipeline/orchestrator.py` — `run_pipeline` reduced to a thin
  driver wrapper; loop body / persistence / sanity gate relocated.
- `ari-core/ari/pipeline/__init__.py` — add new class re-exports (additive).
- `ari-core/ari/pipeline/README.md` — document the new modules.
- (Optional) `ari-core/ari/core.py` — adopt `WorkflowLocator` at `:253-258`
  (only if the optional item is taken; otherwise unchanged).

New files (all inside `ari-core/ari/pipeline/`):

- `stage_context.py` — `StageContext` value object.
- `stages.py` — `BasePipelineStage`, `SubprocessMCPStage`, `ReActStage`,
  `make_stage`.
- `driver.py` — `WorkflowDriver` + `OutputSink`.
- (Optional) `locator.py` — `WorkflowLocator`.

Must **not** change: `config/workflow.yaml`, `stage_runner.py` internals
(may be called by the new classes but its function signatures stay),
`yaml_loader.py`, `stage_control.py`, `claim_gate/`, `verified_context.py`,
`cli/lineage.py` (unless the optional locator is deliberately extended),
`viz/api_paperbench_worker.py`.

## 10. Files / APIs That Must Not Be Broken

- **Entry point:** `ari.core.generate_paper_section` (`core.py:235`) and its call
  to `run_pipeline` (`:280`) — signature and behavior unchanged.
- **Public re-exports** from `ari.pipeline` (`__init__.py:38-66`): `run_pipeline`,
  `build_scientific_data`, `load_pipeline`, `load_disabled_stage_names`,
  `load_workflow`, `_resolve_templates`, `_should_loop_back`,
  `_format_vlm_feedback`, `build_best_nodes_context`,
  `_extract_keywords_from_nodes`, `_call_with_retry`, `_run_react_stage`,
  `_run_stage_subprocess`, `_promote_plan_to_experiment_md`,
  `_extract_plan_sections`, `parse_metric_from_experiment_md`.
- **Lazy-delegator monkeypatch surfaces:** `ari.pipeline._run_react_stage` and
  `ari.pipeline._run_stage_subprocess` (`orchestrator.py:42-56`) must stay
  monkeypatchable and honored by the driver.
- **`config/workflow.yaml` contract:** stage names, `depends_on`, `skip_if_exists`,
  `loop_back_to`, `loop_threshold`, `loop_when_result_key`, `disabled_tools`,
  `react`, `{{var}}` template dialect — all unchanged.
- **Checkpoint file layout:** hardwired output filenames the pipeline writes
  (`nodes_tree.json`, `science_data.json`, `full_paper.tex`, `full_paper.pdf`,
  the `generate_figures` manifest, etc.) keep identical names and content.
- **`ari.public.verified_context`** (backed by `pipeline/verified_context.py`) —
  untouched.
- CLI `ari`, MCP tool contracts, dashboard API — untouched by this subtask.

## 11. Compatibility Constraints

- **Behavior-preserving refactor.** No stage may be added, removed, reordered,
  or renamed. The `ARI_FORCE_PAPER=1` override and the BFTS sanity gate
  (`orchestrator.py:505-537`) must behave identically.
- **ReAct path stays supported but dormant.** Do not enable it in shipped YAML;
  do not delete `_run_react_stage`. Its git-shim sandbox setup must remain
  callable for per-checkpoint YAML / tests.
- **Subprocess semantics unchanged.** Fresh process per stage, args via temp JSON
  file, env passthrough (`ARI_LLM_MODEL`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`,
  `ARI_CHECKPOINT_DIR`, etc.). `SubprocessMCPStage` wraps, not rewrites, this.
- **No new dependencies.** `radon` is not installed and `pnpm` is absent; use only
  the standard library + already-vendored packages. `ruff` is available.
- **Term discipline:** "deprecated" is reserved for external contracts. Internal
  pipeline code that this subtask supersedes is described as ADAPT/refactored,
  never "deprecated."
- **No `sonfigs/` involvement.** No `sonfigs/` directory exists in the repo; this
  subtask does not create or reference one.

## 12. Tests to Run

Baseline gate (run before and after; must be green after):

- `python -m compileall .`
- `ruff check .`
- `pytest -q` (full suite)

Targeted pipeline suites that must remain green (all under `ari-core/tests/`):

- `test_pipeline_e2e.py`
- `test_orchestrator.py`
- `test_workflow_contract.py` (1606 LOC — the primary contract guard)
- `test_workflow_template_resolution.py`
- `test_pipeline_metric_parsing.py`
- `test_pipeline_verified_context.py`
- `test_verified_context_wiring.py`
- `test_disabled_tools_flow.py`
- `test_loop_message_order.py`
- `test_run_loop.py`
- `test_child_node_workflow.py`
- `test_event_loop_and_csv.py`
- `test_include_ear_toggle.py`
- `test_idea_integration.py`
- `test_integration.py`
- `test_workflow_editor.py`

Frontend (`npm test` / `npm run build`): **not applicable** — this subtask
touches only `ari-core/ari/pipeline/` Python; no frontend files change.

CI guard to keep green: `.github/workflows/refactor-guards.yml` runs
`pytest ari-core/tests/ -q` under a redirected `HOME` and forbids new `~/.ari/`
references outside `migrations/` — the refactor must not introduce either.

## 13. Acceptance Criteria

1. `run_pipeline` in `orchestrator.py` is a thin wrapper (target: well under
   ~150 LOC) delegating to `WorkflowDriver`; the loop body concerns live in the
   new stage classes and driver.
2. `BasePipelineStage`, `SubprocessMCPStage`, `ReActStage`, `WorkflowDriver`,
   and `StageContext` exist inside `ari/pipeline/` and are importable.
3. All Section 12 tests pass with **no edits to test assertions**.
4. `python -m compileall .` and `ruff check .` are clean.
5. Every symbol in Section 10 remains importable from `ari.pipeline`, and the
   two lazy-delegator monkeypatch surfaces still work (verified by the existing
   tests that monkeypatch them).
6. `config/workflow.yaml` is byte-for-byte unchanged.
7. The ReAct path is still reachable via `cfg["react"]` (a unit test may set it)
   even though shipped YAML has zero `react:` occurrences.
8. `ari/pipeline/README.md` reflects the new module map.
9. No new `~/.ari/` references; `refactor-guards.yml` stays green.

## 14. Rollback Plan

- The change is confined to `ari-core/ari/pipeline/` (plus optionally
  `core.py`). Revert is a single `git revert` of the implementation commit /
  branch; no data migration, no config or checkpoint format change is involved,
  so rollback cannot corrupt existing checkpoints.
- Because the refactor is behavior-preserving and gated by
  `test_workflow_contract.py` and `test_pipeline_e2e.py`, a regression surfaces
  in CI before merge. If a subtle loop-back or persistence regression is found
  post-merge, revert restores the exact prior `run_pipeline` implementation.
- Keep the new-class commit separate from the optional `WorkflowLocator` commit
  so the locator (which reaches `core.py`) can be rolled back independently.

## 15. Dependencies

Per the master dependency graph:

- **Depends on: 007** (`define_core_interfaces_and_protocols`). `007 -> 012`.
  007 delivers the `StageRunner` protocol / core interface stubs that
  `BasePipelineStage` must conform to (`ari/protocols/__init__.py:15` currently
  only *names* it). 012 must not start until 007's interfaces are settled.
- **Sibling extractions from 007** (`007 -> 008, 009, 010, 011, 012, 013, 014`):
  012 shares the 007 base but has no ordering constraint with 008–011/013/014.
  Coordinate with **011** (`separate_bfts_strategy_from_react_loop`): 011 also
  preserves lazy-delegator/monkeypatch surfaces and touches `agent/loop.py` +
  `orchestrator/bfts.py`; 012 touches `pipeline/`. They are disjoint file-wise
  but share the "preserve monkeypatch shims" policy — align conventions.
- **Inventory prerequisites (must precede any runtime code change):** 001, 002,
  020, 036, 045, 053, 059, 060, 067. These are baseline/measurement/inventory
  subtasks; 012 is a runtime code change, so it must land only after those are
  complete, consistent with the master rule.
- **Downstream:** none declared in the graph take an edge from 012.

## 16. Risk Level

**Risk: High.** **Does this subtask change runtime code? Yes** — implementing 012
rewrites the internals of the pipeline's hot path (`run_pipeline`) and adds new
stage/driver classes. (Writing *this planning document* changes no runtime code.)

Risk drivers: `run_pipeline` is on the critical path for every paper generation;
the loop-back rewind (`:831-901`), the type-sniffing persistence (`:757-826`),
and the subprocess bridge (`stage_runner.py:331`) are subtle and lightly
documented. Mitigations: behavior-preserving mandate, the large
`test_workflow_contract.py` (1606 LOC) + `test_pipeline_e2e.py` guards, additive
re-exports, and separate commits for the optional locator.

## 17. Notes for Implementer

- **Start by reading 007's output.** Match `BasePipelineStage` method names to
  the delivered `StageRunner` protocol; do not invent a divergent shape.
- **Preserve the lazy delegators verbatim.** `orchestrator.py:42-56` and the
  `__init__.py` re-exports exist so tests can `monkeypatch.setattr(ari.pipeline,
  '_run_stage_subprocess', ...)`. The driver must call through the *package
  surface* (`import ari.pipeline as _p; _p._run_stage_subprocess(...)`) so
  monkeypatches are honored — do **not** bind the implementation directly.
- **The ReAct path has zero shipped usages** (`grep -c 'react:'
  config/workflow.yaml == 0`), but tests and per-checkpoint YAML may use it.
  Keep `ReActStage` fully functional; do not treat it as dead code.
- **Do not merge the ORS worker.** `viz/api_paperbench_worker.py:168
  _run_pipeline` is a *separate* four-stage reproducibility runner (its own
  docstring), not a duplicate of the paper pipeline. Merging it is a later
  subtask — resist the temptation here.
- **Leave the `core → viz` back-edge alone.** `cli/lineage.py:151` importing
  `ari.viz.api_orchestrator._api_launch_sub_experiment` is a known boundary
  violation; flag it REVIEW_REQUIRED for a dependency-boundary subtask, do not
  "fix" it inside 012.
- **Config discovery dedup is optional and lower-priority.** Three sites hop
  `__file__` to find `config/workflow.yaml` (`core.py:253-258`,
  `orchestrator.py:330-333`, `cli/lineage.py:56-59`) with *slightly different*
  fallback lists — replicate each site's fallback order exactly if you unify
  them, or skip `cli/lineage.py` to avoid the viz edge.
- **`sonfigs/` does not exist** — the confusable trio is `ari/config/` (code),
  `ari/configs/` (packaged defaults), and top-level `config/` (rubric + workflow
  data). This subtask reads `config/workflow.yaml`; it touches none of the
  config-consolidation concerns (that is subtask 003).
- **Keep persistence rules exact.** The suffix branches (`.tex`, `.pdf`,
  `.png`/`.jpg`) and the `generate_figures` manifest schema at `:757-826` are
  behavior; port them verbatim into `OutputSink`, do not "clean up" the rules.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **012** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
