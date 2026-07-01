# Subtask 008: Extract Model Backend Interface

> Phase 3: Core Architecture · Complexity (per `007_subtask_index.md`): High · Depends on: 007
> Classification of the central artifact: `LLMClient` → **ADAPT** (stays as the public adapter over a new `BaseModelBackend` interface).

## 1. Goal

Introduce a single, explicit **model-backend interface** so that every in-process
call site that needs an LLM completion depends on an abstraction — not on the
concrete `ari.llm.client.LLMClient` class and not on `litellm` directly.

Concretely: define `BaseModelBackend` (a structural interface) in the existing
`ari/protocols/` package, make the current `LLMClient`
(`ari-core/ari/llm/client.py:26`) satisfy it **without changing its public
surface**, and re-export it from `ari/protocols/__init__.py` (which already
lists `LLMClient` on its roadmap, see `ari-core/ari/protocols/__init__.py:14`).

This is the model-backend counterpart of the already-landed `Evaluator`
Protocol (`ari-core/ari/protocols/evaluator.py:18`) + its structural
implementation `LLMEvaluator`. The goal is to reproduce that exact,
low-risk pattern for the LLM path so downstream Phase-3/4 subtasks can inject
alternative backends (test stub, cli-shim, future providers) behind a stable
type.

The change is **purely additive** to the type system: no behavior of any
existing call must change in this subtask.

## 2. Background

ARI talks to every LLM through **litellm**. There are two in-process seams today:

1. **`LLMClient`** (`ari-core/ari/llm/client.py`, 234 LOC) — a *concrete* class
   with **no ABC or Protocol above it**. It wraps `litellm.completion`
   (`client.py:180`, `client.py:230`), forwards `node/phase/skill` via
   `metadata` (`client.py:122`), detects the cli-shim target
   (`_is_cli_shim_target`, `client.py:71`), and forwards MCP config + `work_dir`
   to the shim via `extra_body` (`client.py:153-179`).
2. **`resolve_litellm_model`** (`ari-core/ari/llm/routing.py:37`, 62 LOC total)
   — the single source of truth for litellm provider prefixes
   (`_KNOWN_PREFIXES`, `routing.py:21`).

`LLMClient` is a **stable public symbol**: it is re-exported at
`ari-core/ari/public/llm.py:8` (`from ari.llm.client import LLMClient`) and
documented in `ari-core/ari/public/__init__.py` as
`ari.public.llm` — "for callers that proxy through the ARI-side LLM client".
Skills are supposed to import from `ari.public.*` only.

The `ari/protocols/` package (`REFACTORING.md §11-3`) was created precisely to
host these interfaces. Its `__init__.py` docstring already declares the roadmap:

> More Protocols (**LLMClient**, MCPClient, MemoryClient, NodeStore,
> StageRunner) land in subsequent phases when their adopters are ready.
> — `ari-core/ari/protocols/__init__.py:14`

The target-architecture plan names this interface `BaseModelBackend`
(`docs/refactoring/006_target_architecture_plan.md:159`, §3.1) and assigns it to
this subtask, with the compatibility note that `LLMClient` must remain
importable and `LiteLLMBackend` "can simply *be* `LLMClient`"
(`006_target_architecture_plan.md:181-195`).

Subtask 007 (`define_core_interfaces_and_protocols`) is the design/stub gate for
this and the sibling extractions 009–014; per `007_subtask_index.md:54` it does
**not** change runtime code. This subtask (008) is the first extraction to touch
runtime code (`007_subtask_index.md:55`: "Runtime change: Yes").

## 3. Scope

In scope:

- Define `BaseModelBackend` as a `@runtime_checkable Protocol` in a new module
  `ari-core/ari/protocols/model_backend.py`, mirroring the shape and docstring
  style of `ari-core/ari/protocols/evaluator.py`.
- Re-export it from `ari-core/ari/protocols/__init__.py` and update that file's
  roadmap docstring (remove `LLMClient` from the "land in subsequent phases"
  list, since it now lands here).
- Confirm (and add a test asserting) that the concrete `LLMClient` structurally
  satisfies `BaseModelBackend` — no subclassing required, exactly like
  `LLMEvaluator` satisfies `Evaluator`.
- Optionally expose a naming alias `LiteLLMBackend = LLMClient` so the concrete
  litellm implementation has the target-architecture name, without renaming the
  public class.
- Add a focused unit test for the new interface.

Out of scope but explicitly acknowledged (see §4).

## 4. Non-Goals

- **Do NOT change any completion behavior.** The hardcoded `timeout=1800`
  (`client.py:180`), the `gpt-5*` temperature drop (`client.py:130`,
  `client.py:228`), and the qwen3 think-disable (`client.py:142`) stay exactly
  as they are in this subtask. Adding retry/backoff (absent everywhere today —
  no `num_retries`/tenacity) is a *follow-up*, not part of introducing the
  interface.
- **Do NOT touch `resolve_litellm_model` / `ari/llm/routing.py`.** Its keys are a
  compatibility surface (used by `cost_tracker._apply_ari_routing`,
  `cost_tracker.py:270-276`, and by `tests/test_llm_routing.py`). Consolidating
  routing into a factory is subtask **014**
  (`006_target_architecture_plan.md:654-675`).
- **Do NOT remove the direct `litellm.acompletion` call in the evaluator**
  (`ari-core/ari/evaluator/llm_evaluator.py:585`). Routing `LLMEvaluator`
  through the backend is coordinated with subtask **009**
  (`extract_evaluator_interface`); see `007_subtask_index.md:213-215`.
- **Do NOT change the cost_tracker litellm monkeypatch**
  (`_install_litellm_metadata_injector`, `cost_tracker.py:288`). Skills that
  call `litellm.acompletion` directly (paper, transform, plot, evaluator, idea,
  replicate, web, vlm, paper-re) rely on it for provider routing; this subtask
  does not migrate them onto the backend interface.
- **Do NOT migrate call sites off `LLMClient`.** Callers keep constructing
  `LLMClient(cfg.llm)` as they do today. Type annotations *may* be widened to
  `BaseModelBackend` where trivially safe, but no wiring changes.
- **Do NOT add a new public API export.** `ari.public.llm.LLMClient` is the only
  guaranteed public surface; do not promise `ari.public.*` access to
  `BaseModelBackend` in this subtask.

## 5. Current Files / Directories to Inspect

| Path | LOC | Role |
| --- | --- | --- |
| `ari-core/ari/llm/client.py` | 234 | Concrete `LLMClient` (L26); `complete()` L88, `stream()` L220, `_model_name()` L67, `_is_cli_shim_target()` L71, `set_context()` L42; dataclasses `LLMMessage` L13 / `LLMResponse` L19. **ADAPT target.** |
| `ari-core/ari/llm/routing.py` | 62 | `resolve_litellm_model` (L37), `_KNOWN_PREFIXES` (L21). **KEEP — do not edit.** |
| `ari-core/ari/llm/__init__.py` | 19 | Package exports (`resolve_litellm_model`). May add `LLMClient`/`LiteLLMBackend` re-exports. |
| `ari-core/ari/llm/cli_server.py` | 919 | OpenAI-compatible HTTP shim (`claude -p`/`codex exec`). **KEEP — read-only reference** for the `extra_body` contract. |
| `ari-core/ari/public/llm.py` | 10 | Stable public re-export of `LLMClient`. **Must not break.** |
| `ari-core/ari/public/__init__.py` | — | Public-surface docstring listing `ari.public.llm`. Read-only reference. |
| `ari-core/ari/protocols/__init__.py` | 23 | Protocol package aggregator; roadmap docstring names `LLMClient` (L14). **Edit to export the new Protocol.** |
| `ari-core/ari/protocols/evaluator.py` | 41 | Precedent: `@runtime_checkable` `Evaluator` Protocol. **Template to copy.** |
| `ari-core/ari/protocols/README.md` | — | Package README; update if it enumerates members. |
| `ari-core/ari/cost_tracker.py` | 448 | Global litellm monkeypatch + `_apply_ari_routing` (L255). **Read-only** — explains why skills route without importing routing. |
| `ari-core/ari/core.py` | — | `build_runtime` constructs `LLMClient` per phase (`_phase_llm` L119-125) and sets `llm.mcp_client = mcp` (L146-147). |
| `ari-core/ari/agent/react_driver.py` | — | `run_react(llm: LLMClient, ...)` (L232) — main `complete()` caller (L288). |
| `ari-core/ari/agent/loop.py` | 1630 | `AgentLoop(..., llm: LLMClient, ...)` (L369). |
| `ari-core/ari/orchestrator/bfts.py` | 845 | `BFTS(config, llm: LLMClient)` (L251). |
| `ari-core/ari/pipeline/stage_runner.py` | — | In-process `LLMClient` build (L145). |
| `ari-core/ari/cli/run.py` | — | Title-generation `LLMClient` (L293-294). |
| `ari-core/ari/viz/api_tools.py` | — | Dashboard `LLMClient` (L112-114) + a direct `litellm.completion` (L89). |
| `ari-core/ari/viz/api_experiment.py` | 929 | Lazy `LLMClient` import (L194). |

Tests that exercise this surface (inspect before editing):
`ari-core/tests/test_llm.py` (188), `ari-core/tests/test_llm_routing.py` (133),
`ari-core/tests/test_cost_tracker.py` (802),
`ari-core/tests/test_cli_shim_toolcalls.py` (419),
`ari-core/tests/test_react_driver.py` (256).

## 6. Current Problems

1. **No abstraction over the LLM backend.** `LLMClient` is concrete with no
   Protocol/ABC above it (`client.py:26`). Every caller depends on the concrete
   class name (`core.py:96`, `agent/loop.py:18`, `orchestrator/bfts.py:17`,
   `agent/react_driver.py:26`, `pipeline/stage_runner.py:145`,
   `cli/run.py:293`, `viz/api_tools.py:112`, `viz/api_experiment.py:194`).
   Substituting a test double requires `unittest.mock.patch`, not a typed swap.
2. **The interface roadmap is unfulfilled.** `ari/protocols/__init__.py:14`
   promises an `LLMClient` Protocol "in subsequent phases"; it does not exist.
   The evaluator seam already landed; the LLM seam is the missing sibling.
3. **litellm leaks past the abstraction.** In-process code paths bypass
   `LLMClient` and call litellm directly:
   `evaluator/llm_evaluator.py:585`, `orchestrator/root_idea_selector.py:169`,
   `orchestrator/lineage_decision.py:367`, `pipeline/context_builder.py:136`,
   `viz/api_tools.py:89`. Without an interface these leaks have no typed target
   to migrate toward. (Their *migration* is out of scope here; the interface is
   the prerequisite.)
4. **The naming is inconsistent with the target architecture.** The design docs
   speak of `BaseModelBackend`/`LiteLLMBackend`
   (`006_target_architecture_plan.md:159,181`); the code only has `LLMClient`.
   No shared vocabulary exists between plan and implementation.

Note: problems (3) largely *tracked* by the cost_tracker global monkeypatch
(`cost_tracker.py:288`), which normalizes `model`/`api_base` for any direct
litellm call — but that is a process-wide side effect, not a call-site
contract. This subtask does not fix that; it only supplies the interface those
later fixes will target.

## 7. Proposed Design / Policy

**Adopt the existing `Evaluator`-Protocol pattern verbatim for the LLM path.**

- Add `ari-core/ari/protocols/model_backend.py` defining a
  `@runtime_checkable Protocol` named **`BaseModelBackend`** (name chosen to
  match `006_target_architecture_plan.md`). Structural, not an ABC, so the
  existing public `LLMClient(config: LLMConfig)` constructor and its concrete
  behavior are untouched — exactly how `LLMEvaluator` satisfies `Evaluator`
  today without subclassing.
- The Protocol declares the **minimal structural contract callers actually
  rely on**, grounded in the current call sites:
  - `complete(messages, tools=None, require_tool=True, *, node_id=None,
    phase=None, skill=None, work_dir=None) -> LLMResponse` — the sole method
    invoked by `react_driver` (`react_driver.py:288`), `agent/loop.py`,
    `orchestrator/bfts.py`, `viz/api_tools.py`, `viz/api_experiment.py`.
  - `stream(messages) -> Iterator[str]` — present on `LLMClient`
    (`client.py:220`); include it for completeness (no in-tree caller found, so
    mark it optional in the docstring rather than a hard requirement).
  - `set_context(*, node_id=None, phase=None, skill=None, work_dir=None) -> None`
    — `client.py:42`; part of the surface even if callers currently pass
    context inline.
  - Attribute `mcp_client` — set post-construction at `core.py:146-147`
    (`llm.mcp_client = mcp`). Document it as an optional injected attribute (the
    `Evaluator` Protocol precedent documents only the method; keep the attribute
    as a docstring note, not a typed field, to avoid Protocol-attribute
    strictness).
  - Return type `LLMResponse` and input type `LLMMessage` remain the dataclasses
    defined in `client.py:13-23`; the Protocol references them by import.
- Keep `LLMResponse`/`LLMMessage` where they are (`ari/llm/client.py`). The
  Protocol imports them; do not relocate them in this subtask (relocation would
  perturb `from ari.llm.client import ... LLMMessage, LLMResponse`, which
  `orchestrator/bfts.py:17` and `agent/loop.py:18` rely on).
- Re-export `BaseModelBackend` from `ari/protocols/__init__.py` and prune the
  `LLMClient` entry from the roadmap docstring.
- **Optional (recommended)** naming bridge: define `LiteLLMBackend = LLMClient`
  in `ari/llm/__init__.py` (a plain alias, no new class) so downstream subtasks
  and docs can reference the target-architecture name without a rename.
  `LLMClient` remains the canonical, public name.

**Classification summary**

| Artifact | Classification | Action |
| --- | --- | --- |
| `LLMClient` (`llm/client.py:26`) | ADAPT | Left concrete; declared to satisfy `BaseModelBackend` structurally. |
| `resolve_litellm_model` (`routing.py:37`) | KEEP | Untouched (owned by 014). |
| `cli_server.py` shim | KEEP | Untouched. |
| `ari.public.llm.LLMClient` | KEEP | Public symbol preserved verbatim. |
| `BaseModelBackend` (new) | KEEP (new) | New interface module + re-export. |
| `LiteLLMBackend` alias | KEEP (new, optional) | Naming bridge only. |
| Direct litellm call sites (evaluator/orchestrator/pipeline/viz) | REVIEW_REQUIRED | Not migrated here; flagged for 009/012/014. |

## 8. Concrete Work Items

1. **Create `ari-core/ari/protocols/model_backend.py`.** Copy the header/style
   of `protocols/evaluator.py`. Define `@runtime_checkable class
   BaseModelBackend(Protocol)` with `complete(...)`, `stream(...)`,
   `set_context(...)` as described in §7. Import `LLMMessage`/`LLMResponse` from
   `ari.llm.client` for type references (guard against import cycles — the
   Protocol module is imported by `protocols/__init__.py`, and `ari.llm.client`
   imports only `ari.config`, so `protocols → llm.client` is acyclic; verify with
   `python -c "import ari.protocols"`).
2. **Edit `ari-core/ari/protocols/__init__.py`.** Add
   `from ari.protocols.model_backend import BaseModelBackend  # noqa: F401`,
   append `"BaseModelBackend"` to `__all__`, and update the roadmap docstring
   (remove `LLMClient` from the "land in subsequent phases" sentence at L14;
   add a short line stating `BaseModelBackend` is now exposed, mirroring the
   `Evaluator`/`PromptLoader`/`ConfigLoader` bullet list).
3. **Add the structural-conformance assertion.** Prefer a test (item 6) over a
   runtime `assert isinstance(...)` in module scope. Do NOT make `LLMClient`
   subclass the Protocol.
4. **(Optional) Add `LiteLLMBackend` alias.** In `ari-core/ari/llm/__init__.py`,
   add `from ari.llm.client import LLMClient` and `LiteLLMBackend = LLMClient`,
   extend `__all__`. Purely additive; keep `resolve_litellm_model` export intact.
5. **(Optional) Update READMEs.** If `ari-core/ari/protocols/README.md` (or
   `ari-core/ari/llm/README.md`) enumerates package members, add the new
   interface. Skip if the READMEs are prose-only. (Watch the readme-sync gate,
   see §11.)
6. **Add `ari-core/tests/test_model_backend_protocol.py`.** Assert:
   `isinstance(LLMClient(LLMConfig(backend="claude", model="claude-sonnet-4-5",
   api_key="x")), BaseModelBackend)` is `True` (runtime_checkable structural
   check); assert `BaseModelBackend` is importable from `ari.protocols`; assert
   a minimal hand-written stub with a `complete()` method also satisfies it
   (proves the seam enables test doubles). Mirror `tests/test_llm.py` fixtures.
7. **Grep-verify no accidental behavior change.** Confirm the diff touches only
   the files in §9 and adds no import of the Protocol into hot paths that would
   change routing.

## 9. Files Expected to Change

**New files**

- `ari-core/ari/protocols/model_backend.py` — the `BaseModelBackend` Protocol.
- `ari-core/tests/test_model_backend_protocol.py` — conformance + import tests.

**Modified files**

- `ari-core/ari/protocols/__init__.py` (23 LOC) — export + roadmap-docstring
  update.
- `ari-core/ari/llm/__init__.py` (19 LOC) — *optional* `LLMClient` /
  `LiteLLMBackend` re-export.
- `ari-core/ari/protocols/README.md` and/or `ari-core/ari/llm/README.md` —
  *optional*, only if they list members.

**Explicitly NOT changed** (interface is additive):
`ari-core/ari/llm/client.py`, `ari-core/ari/llm/routing.py`,
`ari-core/ari/llm/cli_server.py`, `ari-core/ari/public/llm.py`,
`ari-core/ari/cost_tracker.py`, and all `LLMClient` call sites
(`core.py`, `agent/*`, `orchestrator/*`, `pipeline/*`, `cli/run.py`, `viz/*`).

> Note on numbering: this document lives at
> `docs/refactoring/subtasks/008_extract_model_backend_interface.md`. It is
> distinct from the top-level `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
> which uses the phase-plan numbering scheme, not the subtask ID scheme.

## 10. Files / APIs That Must Not Be Broken

- **`ari.public.llm.LLMClient`** (`public/llm.py:8`) — stable public symbol per
  `ari.public.*` contract. Name, import path, and `LLMClient(config: LLMConfig)`
  constructor must be byte-for-byte compatible.
- **`LLMClient.complete` / `.stream` / `.set_context` signatures** and the
  `LLMMessage` / `LLMResponse` dataclasses (`client.py:13-23`). Consumed by
  `agent/react_driver.py`, `agent/loop.py`, `orchestrator/bfts.py`,
  `pipeline/stage_runner.py`, `viz/api_tools.py`, `viz/api_experiment.py`.
- **`from ari.llm.client import LLMClient, LLMMessage`** (`bfts.py:17`,
  `loop.py:18`) — do not relocate these symbols.
- **`ari.llm.routing.resolve_litellm_model`** (`routing.py:37`) — used by
  `cost_tracker._apply_ari_routing` (`cost_tracker.py:270`) and by
  `tests/test_llm_routing.py`. Untouched.
- **Test monkeypatch surface `ari.llm.client.litellm`** — `tests/test_llm.py`
  does `@patch("ari.llm.client.litellm")`. Keep `litellm` imported at module
  scope in `client.py`.
- **cli-shim `extra_body` contract** between `client.py:153-179` and
  `cli_server.py` (`mcp_config`, `allowed_mcp_tools`, `work_dir` keys). Untouched.
- **cost_tracker global litellm monkeypatch** (`cost_tracker.py:288`) — skills
  and direct-call sites depend on it. Untouched.
- **`ari-skill-* → ari-core` stable interface**: skills import from
  `ari.public.*` (e.g. `ari.public.cost_tracker`, `ari.public.llm`). No public
  export changes here.

## 11. Compatibility Constraints

- **Additive-only.** The interface is introduced *above* `LLMClient`; no method
  is renamed, moved, or re-typed on the concrete class. Matches the
  `006_target_architecture_plan.md:190-195` mandate that `LLMClient` "must
  remain importable with its current name and constructor" and that
  `LiteLLMBackend` "can simply *be* `LLMClient`".
- **Structural, not nominal.** Use `Protocol` + `@runtime_checkable` (as
  `Evaluator` does), so no `import`-time coupling is forced on `LLMClient` and no
  `isinstance`/MRO changes reach production paths.
- **No new hard dependency.** Do not add tenacity/backoff libraries or change
  `requirements.txt` / `requirements.lock` / `ari-core/pyproject.toml`.
- **Do not break `ari.public.*` docstring contract.** `public/__init__.py`
  enumerates exported submodules; do not add `BaseModelBackend` to the public
  surface in this subtask.
- **Docs/README gates.** The repo runs `scripts/readme_sync.py`,
  `scripts/docs/check_readme_parity.py`, and `.github/workflows/readme-sync.yml`
  / `docs-sync.yml`. If a per-directory README is edited, keep the ja/zh mirrors
  and parity checks satisfied. Prefer *no* README edits if avoidable.
- **`refactor-guards.yml`** asserts no new `~/.ari/` references and no `~/.ari/`
  writes during pytest. This subtask introduces neither; ensure the new test
  writes nothing to `$HOME`.

## 12. Tests to Run

Run from the repo root:

```bash
python -m compileall ari-core/ari/protocols ari-core/ari/llm
python -m compileall .
ruff check ari-core/ari/protocols ari-core/ari/llm ari-core/tests
ruff check .
pytest -q ari-core/tests/test_model_backend_protocol.py \
          ari-core/tests/test_llm.py \
          ari-core/tests/test_llm_routing.py \
          ari-core/tests/test_cost_tracker.py \
          ari-core/tests/test_cli_shim_toolcalls.py \
          ari-core/tests/test_react_driver.py
pytest -q            # full core suite; interface change must be a no-op elsewhere
```

Import smoke-check:

```bash
python -c "from ari.protocols import BaseModelBackend; \
from ari.llm.client import LLMClient; from ari.config import LLMConfig; \
c=LLMClient(LLMConfig(backend='claude', model='m', api_key='x')); \
print(isinstance(c, BaseModelBackend))"   # -> True
```

No frontend involved (`npm test` / `npm run build` not required for this subtask).

Tooling note: `ruff` and `python -m compileall`/`pytest` are available; `radon`
is **not** installed (irrelevant here).

## 13. Acceptance Criteria

1. `ari.protocols.BaseModelBackend` imports cleanly and is `@runtime_checkable`.
2. `isinstance(LLMClient(...), BaseModelBackend)` is `True` without any change to
   `LLMClient`'s source (`git diff` shows `client.py` unmodified).
3. `ari.public.llm.LLMClient` still imports and constructs identically
   (`LLMClient(config: LLMConfig)`).
4. `ari/protocols/__init__.py` no longer lists `LLMClient` as a *future* Protocol
   and exports `BaseModelBackend` in `__all__`.
5. New test `tests/test_model_backend_protocol.py` passes, including the
   hand-written-stub conformance case.
6. Full `pytest -q`, `ruff check .`, and `python -m compileall .` all pass with
   no new failures relative to the pre-change baseline.
7. `git diff --stat` shows only the files listed in §9; no call-site or behavior
   change.

## 14. Rollback Plan

The change is additive and isolated. To roll back:

1. `git rm ari-core/ari/protocols/model_backend.py
   ari-core/tests/test_model_backend_protocol.py`.
2. Revert the `ari/protocols/__init__.py` docstring/export edit and, if applied,
   the `ari/llm/__init__.py` alias and any README edits.
3. Re-run §12. Since no consumer was migrated to `BaseModelBackend`, removing it
   cannot break any runtime path — the pre-change import graph is fully restored.

No data/format migration is involved, so rollback is a pure code revert.

## 15. Dependencies

- **Depends on: 007** (`define_core_interfaces_and_protocols`). Per the
  dependency graph `007 -> 008, 009, 010, 011, 012, 013, 014`. Subtask 007 is the
  design/stub gate that establishes the `ari/protocols/` conventions
  (Protocol-vs-ABC choice, `__init__` aggregation, README format) this subtask
  follows. 007 is inventory/design-only and must precede this runtime change
  (`007_subtask_index.md:54`, "Runtime change: No").
- **Blocks: none directly.** 008 is a leaf of the `007 -> …` fan-out; no listed
  edge has 008 as a prerequisite.
- **Coordinates with (not a hard dependency):**
  - **009** (`extract_evaluator_interface`) — will route `LLMEvaluator` through
    the backend and delete the direct `litellm.acompletion`
    (`llm_evaluator.py:585`); it consumes the `BaseModelBackend` defined here.
  - **011** (`separate_bfts_strategy_from_react_loop`) — `BFTS` and `AgentLoop`
    hold the `LLMClient`; they may narrow their annotations to
    `BaseModelBackend`.
  - **014** (`refactor_registry_and_factory_layer`) — owns unifying
    `resolve_litellm_model` and backend selection; must not be pre-empted here.
- **Ordering vs inventory gates.** The inventory/design subtasks that must
  precede *any* runtime code change (001, 002, 020, 036, 045, 053, 059, 060, 067)
  and 007 should be complete before this subtask lands.

## 16. Risk Level

- **Changes runtime code: Yes** (additive: a new Protocol module + a package
  `__init__` export; optionally a name alias). Consistent with
  `007_subtask_index.md:55` ("Runtime change: Yes").
- **Risk: Low–Medium.** The `007_subtask_index.md` complexity rating is **High**,
  reflecting the *strategic* weight of the LLM seam and the size of the surface it
  abstracts. Scoped as specified here (structural Protocol above an unchanged
  concrete class, zero call-site migration), the *execution* risk is Low–Medium:
  the only realistic failure modes are (a) an import cycle
  (`protocols → llm.client`; verified acyclic in §8-1) and (b) accidentally
  editing `client.py`/behavior. Both are caught by §12/§13. The High complexity
  is retired incrementally by the coordinated subtasks (009/011/014) that migrate
  call sites onto the interface — those carry the behavioral risk, not this one.

## 17. Notes for Implementer

- **Copy `protocols/evaluator.py` almost verbatim.** It is the canonical,
  merged precedent (41 LOC): module docstring citing the roadmap,
  `@runtime_checkable`, one primary method, a docstring that treats the return
  value as the contract. Do the same for `complete()`.
- **Do not make `LLMClient` subclass the Protocol.** Structural satisfaction is
  the whole point; subclassing would couple `client.py` to `protocols` and
  invert the intended dependency direction.
- **Mind the `LLMMessage`/`LLMResponse` import direction.** They live in
  `ari.llm.client`; the Protocol references them. `ari.llm.client` imports only
  `ari.config` and `litellm`, so importing them into `ari.protocols.model_backend`
  is acyclic — but run `python -c "import ari.protocols"` after writing the file
  to be sure (a cycle would surface as an `ImportError` at collection time).
- **Keep `complete()`'s keyword-only signature exact.** Callers pass
  `phase=`, `skill=`, `work_dir=` as keywords (`react_driver.py:288`); the
  Protocol method signature should match so `runtime_checkable` structural checks
  and any future static typing stay honest.
- **The `mcp_client` attribute is real but optional.** `core.py:146-147` sets it
  after construction and `client.py:40` initializes it to `None`. Describe it in
  the Protocol docstring rather than declaring it as a Protocol member (Protocol
  attributes impose stricter conformance and are unnecessary for the current
  callers).
- **Leave `stream()` soft.** No in-tree caller was found for `LLMClient.stream`
  (`client.py:220`); include it in the Protocol for completeness but note in the
  docstring that an implementation may raise `NotImplementedError` if it only
  supports `complete()`.
- **Resist scope creep.** Retry/backoff, evaluator de-leaking, routing
  unification, and call-site migration each belong to a named later subtask
  (see §4 / §15). Landing 008 as a minimal, additive interface is what unblocks
  them safely.
- There is **no `sonfigs/` directory** and no top-level `pyproject.toml`; the
  core manifest is `ari-core/pyproject.toml`. Neither is touched here.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **008** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
