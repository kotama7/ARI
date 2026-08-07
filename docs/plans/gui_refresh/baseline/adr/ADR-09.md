# ADR-09: Superseding the "no GUI toggle for RQGM in v1" decision — two mode intents are selectable for a NEW run

> Status: accepted (2026-07-27)  
> Owner: GUI refresh program (tasks 06/08)  
> Decision-by gate: G4 (adr_backlog.md)

## Context

`docs/guides/execution_modes.md` recorded an explicit product decision when the
RQGM execution mode shipped: `ari_rqgm` is *"opt-in, config only … there are no
CLI flags or GUI toggles for it in v1"*, restated in the guide's §Limitations
(v1) as *"No `--mode` CLI flag and no GUI toggle (env activation is
GUI-compatible by construction)"*. The GUI refresh honoured it literally: the
Configuration Studio collected the whole `Execution mode` category plus every
`rqgm.*` path into one disabled group, and `POST /api/v1/runs` recomputed the
same set from the registry and rejected a draft carrying any of them with
`mode_locked` (MN-10, MN-11 — both notes say "pending ADR-09").

That was the correct *default* posture, but it left a hole the program could
not close: the GUI is the only launch surface a user is offered, and it could
not express the single most consequential property of the run it was about to
start. A user who wanted a governed run had to leave the GUI, edit
`workflow.yaml` by hand (two keys, in two different blocks, that must agree),
and come back. Worse, the lock was indiscriminate — it treated "which algorithm
runs" and "what the epoch-boundary adversarial budget is" as the same kind of
decision, so the safe answer for 96 tuning leaves also silenced the 4 leaves
that decide what the run *is*.

Decision axes: (1) the standing `simple_bfts` invariant — a default run's
behaviour and artifacts must stay byte-identical, which is a program invariant
(INDEX §Global invariants) and not negotiable; (2) mode immutability — a run's
mode is fixed at start, downgrade-only at epoch boundaries
(`ari.rqgm.state.reconcile_resume_mode`), so any GUI path must be new-run only;
(3) the read-only-governance invariant — "GUI v1 の RQGM 操作は read-only とし、
registry や transition を直接編集しない" (INDEX §Global invariants) must survive
this decision intact; (4) minimum widening — open the smallest surface that
makes the launch honest, and make widening it further a deliberate edit.

## Decision

| Item | Decision |
|---|---|
| Scope | EXACTLY TWO orthogonal intents become selectable, each a mode leaf plus its interlock twin: **execution mode** `ari.mode` ∈ {`simple_bfts` (default), `ari_rqgm`} with `rqgm.enabled`, and **paper mode** `paper.mode` ∈ {`linear` (default), `rqgm_archive`} with `rqgm.paper.enabled`. Nothing else. The four leaves are `field_registry.MODE_SELECTION_PATHS`, the union of `MODE_INTERLOCK_PAIRS` |
| One intent = one control | ONE user-facing control writes BOTH keys of its pair in one step, so a single Studio save issues one PATCH carrying both. The GUI cannot produce a half-set document. The pair constants live in `field_registry.MODE_INTERLOCK_PAIRS` (the single source; `config/resolver.INTERLOCK_PAIRS` is now an alias of it) mirrored by `frontend/.../ConfigStudio/modeIntents.ts` |
| Half-set / disagreeing pair | Rejected outright as a typed 400 `mode_interlock_mismatch` (new, 7th member of the closed `field_registry.PATCH_REASONS` vocabulary) at run-template create/PATCH, run-draft create/PATCH, and launch. The check runs on the MERGED document values, never the raw patch, so a two-step edit that ENDS consistent is accepted. `POST /run-drafts/{id}/validate` keeps its existing `interlock_mismatch` reason (unchanged API contract) |
| New-run only | Both leaves stay `mutability: new_run_only`, `scope: run`. No GUI path may change the mode of an existing run: `ari resume` still reads `{ckpt}/rqgm_state.json` checkpoint-first and the persisted mode still wins over config and env, downgrade-only (`reconcile_resume_mode`). No GUI launch path writes that file |
| Project scope still refuses | The mode paths are `scope: run`, so the project config still rejects them with `not_project_scope` (`validate_patch`, unchanged). The Studio disables the controls in project scope and states the reason instead of pretending to work |
| Governance tuning stays file-only | The other **96** locked paths (`Execution mode` ∪ `rqgm.*` minus the four) — epoch, kernel, governance, adversarial, budgets, paper-archive tuning — keep rejecting with `mode_locked` at launch. They remain **visible READ-ONLY with their effective values** in a collapsed Studio group rendered by the shared `ConfigBrowser/ConfigReadOnlyTable`, and the UI copy says so: *"Governance tuning parameters come from configuration files in this release — they are not editable from the GUI; edit workflow.yaml to change them. Selecting a mode above is not a governance mutation."* The carve-out is SUBTRACTIVE by construction (`locked_launch_paths()` = registry-derived set MINUS `MODE_SELECTION_PATHS`), so widening the write surface requires editing that one set |
| Not a governance mutation | Selecting a mode chooses which algorithm a NEW run executes; it registers no component, adopts no policy, opens no epoch and rewrites no score. Every `/api/v1/runs/{run_id}/rqgm/*` route stays a GET and the Governance workspace stays read-only. The INDEX invariant is intact, not weakened |
| Display the RESOLVED mode | The launch review shows the mode read off the resolve-config manifest (post interlock resolution), never the raw selection. When the runtime resolvers (`resolve_effective_mode` / `resolve_paper_mode`) warn-and-fall-back — e.g. an env layer breaks a document-consistent pair — the review renders `requested → resolved` plus the resolver's warning verbatim, and the residual warning is additionally raised to a review-time `interlock_mismatch` error so the launch refuses rather than silently running the fallback |
| Materialization | A non-default selection is written BOTH ways: minimal `ari:` / `rqgm:` / `paper:` blocks merged into the **per-checkpoint** `workflow.yaml` copy (the bundled file is never touched; absent top-level keys → text append, so every existing byte and comment survives), and the documented `ARI_MODE` / `ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` env vars from `field_registry.ENV_OVERRIDES`. The checkpoint is therefore self-describing and every later phase reading `{ckpt}/workflow.yaml` agrees with the env |
| Default path byte-identical | Export and merge are VALUE-gated, not provenance-gated: a draft that selects nothing AND a draft that explicitly restates `simple_bfts` + `linear` both resolve to the defaults, so `_mode_selection()` returns `{}` — no `ari:`/`rqgm:`/`paper:` block is written, none of the four env vars is set, the artifact set is unchanged. Pinned by `TestDefaultPathUnchanged` in `ari-core/tests/test_gui_v1_mode_selection.py` |
| Kill-switch | **None is introduced.** The lever is leaving the default selection; the pre-existing `ARI_GUI_V2=0` capability flag (ADR-07) still removes the whole v2 Studio, and the legacy Wizard + `POST /api/launch` remain byte-identical and always launch `simple_bfts` + `linear` |

## Alternatives considered

- **Keep the full lock, document the workaround better** — rejected: the launch
  surface would stay unable to state what the run is, and users would keep
  hand-editing two interlocked keys in a file the GUI otherwise owns. The
  failure mode (a half-set pair that silently falls back to `simple_bfts` after
  a long run) is exactly what a paired control eliminates.
- **Open the whole `Execution mode` category + `rqgm.*` tree** — rejected: the
  ~96 tuning leaves are governance policy, not a run's identity; several are
  `expert` and only meaningful under an already-active mode. Editing them from
  a launch form would put governance parameters one click away from a research
  user and blur the read-only-governance invariant.
- **Two independent controls per pair (mode select + interlock checkbox)** —
  rejected: it makes an inconsistent pair *representable* in the UI, which is
  the one state the runtime handles by silently degrading. One control per
  intent makes the invalid state unconstructible.
- **A GUI "switch mode" action on a running/resumable run** — rejected: a run's
  mode is immutable except at epoch boundaries and downgrade-only; a GUI upgrade
  path has no legal switch point and would contradict `reconcile_resume_mode`.
- **Env-only activation from the GUI (set `ARI_MODE` for the subprocess, write
  nothing)** — rejected: the checkpoint would not describe itself, and later
  phases reading `{ckpt}/workflow.yaml` (the paper pipeline) could disagree with
  the exploration phase. Both materializations, or neither.

## Consequences

- `docs/guides/execution_modes.md` is corrected: the config-file and env paths
  remain the canonical description, plus a GUI section stating where the control
  lives, that it is new-run only, that resume keeps the persisted mode, that one
  control writes both keys, and what the GUI shows on a resolver fallback. Its
  §Limitations (v1) no longer claims "no GUI toggle" (the `--mode` CLI flag is
  still absent — that part of the decision stands).
- `docs/guides/configuration_studio.md`, `docs/guides/rqgm_gui.md`,
  `docs/guides/dashboard.md` and `docs/reference/configuration.md` are updated
  where they described the lock as covering mode selection.
- The launched checkpoint is self-describing for a non-default mode (per-run
  `workflow.yaml` blocks + env), and unchanged for the default.
- Resume semantics are untouched; `{ckpt}/rqgm_state.json` remains the authority
  for an existing run.
- `PATCH_REASONS` grows to 7 (`mode_interlock_mismatch`); it is a closed
  vocabulary the GUI renders and `docs/reference/configuration.md` documents, so
  the addition is an API-visible, documented change (MN-12).
- The task 06 residual "governance step — ADR-09 user-gated deferral" is
  discharged: the step is delivered, not deferred.
- Announced as **MN-12** (before/after/why/rollback).

## What a future revision would need to unlock the rest

A follow-up ADR is required before ANY additional `rqgm.*` leaf becomes
editable. It must answer, at minimum:

1. **Which leaves, and why those** — an enumerated set, not a prefix. The
   subtractive shape of `locked_launch_paths()` means the diff is reviewable.
2. **Governance-mutation boundary** — a rule that distinguishes "configure a
   future run" from "edit the institution", strong enough to keep the INDEX
   read-only-governance invariant true, since several `rqgm.*` leaves (kernel
   enforcement, capability-adjacent knobs) are closer to policy than to tuning.
3. **Interlock/dependency semantics** — most tuning leaves carry `applies_when`
   gates; the paired-intent grammar used here (a NOTE, not a `path=value` gate,
   deliberately — a gate on the twin would make the interlock self-gating) does
   not generalise, so a dependency-aware validation story is needed.
4. **Determinism and audit** — whether a GUI-set governance parameter must be
   recorded in the governance audit trail rather than only in the checkpoint's
   `workflow.yaml` + `resolved_config.json`.
5. **The `simple_bfts` invariant proof** — the same byte-identical-default test
   obligation, extended to whatever is newly writable.

Unlocking mid-run mutation of a mode is explicitly OUT of scope for any future
revision short of changing the run-mode immutability rule itself.

## Supersedes / references

- Supersedes: the `docs/guides/execution_modes.md` statement *"there are no CLI
  flags or GUI toggles for it in v1"* and the §Limitations (v1) bullet *"no GUI
  toggle"*, for the NEW-RUN case only. The `--mode` CLI flag decision is
  unchanged; mid-run and resume mode changes remain forbidden.
- References: plan 05 §Interlocks (an inconsistent pair is resolved as one
  intent and reported as a validation error), plan 05:176, plan 05:173, plan 06
  §Launch protocol, plan 08 (read-only RQGM surface), INDEX §Global invariants,
  adr_backlog.md ADR-09, ADR-07 (flag/rollback policy), ADR-12 (GUI document
  store), MN-10 / MN-11 (the launch and Studio slices whose "pending ADR-09"
  lock this decision replaces), MN-12.
- Implementation: `ari-core/ari/config/field_registry.py`
  (`MODE_INTERLOCK_PAIRS`, `MODE_SELECTION_PATHS`, `PATCH_REASONS`,
  `validate_mode_interlocks`), `ari-core/ari/config/resolver.py`,
  `ari-core/ari/viz/v1/config_api.py` (`_validate_mode_pairs`,
  `_resolve_draft_manifest`, `_draft_validation_errors`),
  `ari-core/ari/viz/v1/launch.py` (`locked_launch_paths`, `_mode_selection`,
  `_mode_env`, `_merge_mode_blocks`),
  `ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx`,
  `.../ConfigStudio/modeIntents.ts`, `.../ConfigStudio/LaunchPanel.tsx`.
- Tests: `ari-core/tests/test_gui_v1_mode_selection.py`,
  `ari-core/tests/test_gui_v1_launch.py`
  (`test_governance_fields_stay_locked_after_adr09`),
  `ari-core/ari/viz/frontend/src/components/ConfigStudio/__tests__/ConfigStudioExecutionMode.test.tsx`.
