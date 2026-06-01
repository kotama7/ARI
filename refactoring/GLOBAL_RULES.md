# Global Refactoring Rules

These rules apply to **every** requirement under `refactoring/requirements/`.
A requirement may add stricter rules, but may never relax these.

## Behavior-preservation rules

- **Preserve existing behavior.** Refactoring changes structure, not observable
  behavior. If behavior must change, it is a feature change and belongs in a
  separate, explicitly justified PR — not in a refactoring requirement.
- **Preserve public CLI commands.** All `ari ...` subcommands keep their names,
  arguments, and output contracts.
- **Preserve launch scripts.** `./start.sh`, `./start.sh gui`, `./start.sh status`,
  and `./shutdown.sh` keep their behavior and interface.
- **Preserve `ari viz`.** The dashboard launch path must keep working unchanged.
- **Preserve existing dashboard REST and WebSocket endpoints during migration.**
  Paths, methods, request shapes, and response shapes stay compatible. Old
  response fields are kept during transition even when new ones are added.
- **Preserve existing checkpoint formats.** Do not migrate or rewrite existing
  checkpoint files without a separate, dedicated migration plan.
- **Preserve existing workflow behavior.** BFTS, ReAct, post-BFTS pipeline,
  paper generation, review, reproduction, and PaperBench flows behave the same.
- **Preserve existing skill behavior.** Every `ari-skill-*` package keeps its
  current behavior and public surface.
- **Do not delete existing features.**

## Scope-discipline rules

- **Do not perform a full rewrite.** Refactor incrementally.
- **Do not introduce top-level `ari-gui` or `ari-api` packages in early
  refactoring.** Refactor `ari-core/ari/viz` and
  `ari-core/ari/viz/frontend` **in place** first. A package move may be
  considered only after a later migration requirement proves it is low-risk
  and worth the compatibility cost.
- **Prefer incremental migration** over big-bang changes.
- **Prefer compatibility wrappers** (thin re-exports / shims) during a
  transition so existing import paths and call sites keep working.
- **Keep each PR small and reviewable.**
- **Do not mix unrelated refactoring topics** in one PR.
- **Do not mix pure file movement with behavior changes** unless explicitly
  justified in the requirement.
- **Add tests or smoke checks before risky changes.** See
  `requirements/13_testing_smoke_guards.md`.

## Coupling rules

- **Avoid hidden coupling through global mutable state.** `ari.viz.state`
  holds shared mutable server state (`_running_procs`, `_checkpoint_dir`,
  `_settings_path`, `_clients`, `_loop`, …). Do not expand this surface;
  prefer passing explicit context.
- **Avoid GUI components containing API or domain logic.** Components call
  hooks/context, which call `services/api.ts` / `services/websocket.ts`.
- **Avoid backend route handlers containing large business logic.** Route
  handlers parse the request, call a service, and format the response.
- **Avoid core depending on concrete skill implementations.**
- **Avoid core depending on concrete LLM / HPC / container implementations.**
  Keep these behind their boundaries (`ari.llm`, `ari.container`, execution
  wrappers).

## Target dependency direction

```text
Frontend components
  -> hooks / context
    -> services/api.ts or services/websocket.ts
      -> dashboard REST/WebSocket API

Dashboard routes
  -> thin request parsing / response formatting
    -> viz service modules
      -> core/public/protocol interfaces
        -> domain models and filesystem/checkpoint abstractions

Skills
  -> ari.public / ari.protocols
    -> stable core contracts

Pipeline / workflow
  -> orchestration interfaces
    -> stage runners / phase implementations

Execution backends
  -> backend interfaces
    -> concrete LLM / HPC / container / filesystem implementations
```

## Prohibited or suspicious dependency directions

These are red flags. If a refactor introduces one, stop and justify it
explicitly, or route the work into a requirement that addresses the boundary.

```text
frontend component -> raw fetch, except explicitly justified upload/streaming cases
frontend component -> filesystem concept encoded ad hoc
frontend component -> backend implementation detail
core -> frontend
core -> dashboard route handler
core -> concrete skill package
core -> concrete LLM provider outside ari.llm boundary
core -> concrete HPC/SLURM implementation outside execution boundary
skill -> dashboard backend
skill -> frontend
route handler -> large business logic
route handler -> complex checkpoint parsing directly
route handler -> subprocess directly without service boundary
```

## Requirement-file lifecycle (binding)

- Requirement files are **temporary task-control files**.
- A requirement file must remain present while its requirement is incomplete.
- A requirement file may be deleted **only** when all completion criteria in
  its section 9 are satisfied, completion is recorded in `COMPLETED.md`, and
  the deletion happens in the **same PR**.
- **Do not delete a requirement file for partial completion.**

## Compatibility-wrapper removal policy (binding)

When a refactor introduces a compatibility wrapper (re-export, shim, alias, or a
public-first `try/except ImportError` fallback) to preserve an old import path or
endpoint:

- the wrapper **stays** until all known call sites are migrated;
- removing a wrapper is itself a behavior-sensitive change and requires its
  **own** requirement file (or an explicit, justified section in a later
  requirement) with its own checks;
- wrappers are **never** removed in the same PR that introduces them.

Examples of live wrappers introduced by this refactoring sequence:
`ari.public.*` re-exports (`container`, `cost_tracker`, `llm`, `paths`,
`config_schema`, `run_env`) over `ari.<module>` internals; the skills'
public-first `cost_tracker` fallback (req 09); the `ari.checkpoint.load_nodes_tree`
fallback in `checkpoint_api` (req 07). Their internal paths must keep working.

## Package-move gate (binding)

A move such as `ari-core/ari/viz` → a top-level `ari-gui` / `ari-api` package:

- is **forbidden** in early refactoring;
- may be **proposed** only after `00` and `01` are complete and the in-place
  refactors (`02`–`12`) have reduced the relevant coupling;
- requires a **new, dedicated migration requirement** that proves the move is
  low-risk and worth the compatibility cost, including a wrapper plan for old
  import paths and launch behavior (`start.sh`, `ari viz`).

No package move has been performed; `ari-core/ari/viz` and
`ari-core/ari/viz/frontend` were refactored **in place** throughout this
sequence, per the scope-discipline rule above.

## Sequence completion + final cleanup

The recommended execution order is recorded in `README.md`. When
`requirements/` is empty, the planned sequence is complete; the
`refactoring/` directory may then be removed in a final cleanup PR recorded in
`COMPLETED.md` (the `refactoring/notes/` assessments should first be folded into
`docs/` or per-directory `README.md`s where they carry durable value — see each
note's header). Until then, the presence of any file under `requirements/` means
that requirement is unfinished.
