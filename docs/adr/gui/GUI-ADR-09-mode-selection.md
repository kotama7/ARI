---
sources:
  - path: ari-core/ari/config/field_registry.py
    role: implementation
  - path: ari-core/ari/config/resolver.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/rqgm/mode.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_mode.py
    role: implementation
  - path: ari-core/ari/rqgm/state.py
    role: implementation
  - path: ari-core/ari/viz/api_capabilities.py
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/ExecutionSection.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/modeIntents.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/LaunchPanel.tsx
    role: implementation
  - path: ari-core/tests/test_gui_v1_mode_selection.py
    role: test
  - path: ari-core/tests/test_gui_v1_launch.py
    role: test
  - path: ari-core/ari/viz/frontend/src/components/ConfigStudio/__tests__/ConfigStudioExecutionMode.test.tsx
    role: test
  - path: docs/guides/execution_modes.md
    role: doc
last_verified: 2026-08-17
---

# GUI-ADR-09: GUI mode selection for a new run

Decision (ADR-09, accepted 2026-07-27): exactly two orthogonal intents become
GUI-selectable, each a mode leaf plus its interlock twin — execution mode
`ari.mode` ∈ {`simple_bfts`, `ari_rqgm`} with `rqgm.enabled`, and paper mode
`paper.mode` ∈ {`linear`, `rqgm_archive`} with `rqgm.paper.enabled`. The pairs
are `field_registry.MODE_INTERLOCK_PAIRS`; their union is
`MODE_SELECTION_PATHS`. One user-facing control writes BOTH keys of its pair in
one save, so the GUI cannot construct a half-set document; a document carrying
one half without an agreeing twin is a typed 400 `mode_interlock_mismatch`
(`validate_mode_interlocks`, the seventh member of the closed
`field_registry.PATCH_REASONS`) at run-template and run-draft create/PATCH and
at launch, evaluated on the MERGED values so a two-step edit that ends
consistent is accepted. Both leaves stay `mutability: new_run_only`,
`scope: run`: project scope still refuses them with `not_project_scope`, and no
GUI path changes an existing run's mode. Every other `Execution mode` /
`rqgm.*` leaf keeps rejecting with `mode_locked` and stays visible read-only
with its effective values; the carve-out is subtractive by construction
(`launch.locked_launch_paths()` = the registry-derived set MINUS
`MODE_SELECTION_PATHS`), so widening the write surface requires editing that one
set. A non-default selection is materialized BOTH ways — minimal `ari:` /
`rqgm:` / `paper:` blocks merged into the per-checkpoint `workflow.yaml` copy
(the bundled file is never touched; absent top-level keys are appended so every
existing byte and comment survives) and the documented `ARI_MODE` /
`ARI_RQGM_ENABLED` / `ARI_PAPER_MODE` / `ARI_RQGM_PAPER_ENABLED` env vars — so
the checkpoint is self-describing. Export and merge are VALUE-gated, not
provenance-gated (`launch._mode_selection`): a draft that selects nothing and a
draft that explicitly restates the defaults both resolve to `simple_bfts` +
`linear`, write no block and export no var. The launch review displays the
RESOLVED mode off the preview manifest, never the raw request; when
`resolve_effective_mode` / `resolve_paper_mode` warn-and-fall-back it renders
`requested → resolved` plus the warning verbatim and refuses the launch with an
`interlock_mismatch` validation error rather than silently running the fallback.

Alternatives were: keeping the full lock and documenting the hand-edit
workaround — rejected because the only launch surface offered to a user could
not state the most consequential property of the run, and the failure it left
open (a half-set pair that silently degrades to `simple_bfts` after a long run)
is exactly what a paired control eliminates; opening the whole `Execution mode`
category and `rqgm.*` tree — rejected because those leaves are governance
policy, not a run's identity, and several are only meaningful under an already
active mode; two independent controls per pair (mode select plus interlock
checkbox) — rejected because it makes the inconsistent pair representable, which
is the one state the runtime handles by degrading; a GUI "switch mode" action on
a running or resumable run — rejected because a run's mode is not GUI-mutable
and the path would contradict `rqgm.state.reconcile_resume_mode`; and env-only
activation writing nothing to the checkpoint — rejected because later phases
reading `{checkpoint}/workflow.yaml` could then disagree with the exploration
phase. Both materializations, or neither.

Consequences accepted: `PATCH_REASONS` grows to seven, an API-visible change the
GUI renders and `docs/reference/configuration.md` documents under
§"Configuration control plane (`/api/v1/config/*`)"; the guides that described
the lock as covering mode selection were corrected, chiefly
`docs/guides/execution_modes.md` §"Selecting the mode from the GUI", whose
§"Limitations (v1)" no longer claims "no GUI toggle" (no `--mode` CLI flag is
still true); a non-default launch now leaves mode state in the checkpoint's own
`workflow.yaml`, while the default path stays byte-identical; resume semantics
are untouched, with `{checkpoint}/rqgm_state.json` still the authority for an
existing run. No kill-switch is introduced — the lever is leaving the default
selection, and the pre-existing `ARI_GUI_V2=0` capability flag from ADR-07
(`viz/api_capabilities.py`) still removes the whole v2 Studio while the legacy
wizard route `POST /api/launch` is unchanged and selects no mode at all — it
inherits whatever the configuration layers resolve to. Announced as
migration note MN-12 (`docs/guides/migration.md` §"Execution and paper mode are
selectable for a new run (MN-12)").

Reversing or widening: any ADDITIONAL `rqgm.*` leaf becoming editable requires a
follow-up ADR answering, at minimum, which leaves and why (an enumerated set,
not a prefix — the subtractive shape of `locked_launch_paths()` makes the diff
reviewable), where the boundary between "configure a future run" and "edit the
institution" lies, how `applies_when` dependency gates validate (the paired
grammar used here is a note rather than a `path=value` gate, deliberately, since
gating on the twin would make the interlock self-gating), whether a GUI-set
governance parameter must reach the governance audit trail rather than only the
checkpoint's `workflow.yaml` and `resolved_config.json`, and the same
byte-identical-default proof obligation extended to whatever is newly writable.
Mid-run mutation of a mode is out of scope for any such revision.

Supersedes: the `docs/guides/execution_modes.md` product decision that RQGM is
opt-in config only with no CLI flags or GUI toggles in v1, for the NEW-RUN case
only. The absent `--mode` CLI flag and the ban on mid-run and resume mode
changes are unchanged. Superseded by: nothing.

Program context this record replaces (the plan documents are deleted): the
control plane plan required that `ari.mode=ari_rqgm` and `rqgm.enabled=true` be
edited as one intent and treated as a validation error when inconsistent, while
the runtime resolves the same inconsistency as a warning plus `simple_bfts`
fallback — hence the rule that the GUI must show the resolved mode and say so
explicitly when a request fell back, and may report a run as governed only when
the resolved mode is `ari_rqgm`; the same plan recorded that RQGM is new-run
only, read-only on an active checkpoint, and that making mode selectable from
the GUI would supersede the shipped `docs/guides/execution_modes.md` decision
and so require an ADR plus documentation updates. The launch plan fixed the
protocol this decision plugs into: resolve-config for effective values and
digest, validate (schema, capability, secret, resource, mode), user approval of
an immutable review, idempotent run create, then the canonical run overview. The
governance plan kept every `/api/v1/runs/{run_id}/rqgm/*` route a GET, and the
program invariants held that a default `simple_bfts` run's behaviour and
artifacts must not change for GUI reasons, that execution mode and paper mode
are independent axes with no mode change during resume, and that GUI v1 RQGM
operation is read-only and never edits the registry or transitions directly.
Selecting a mode chooses which algorithm a NEW run executes — it registers no
component, adopts no policy, opens no epoch and rewrites no score — so those
invariants survive intact. The decision was gated at G4 in the program's ADR
backlog and discharged the launch task's deferred governance step.

Divergences from the tree as of this migration: the record says the remaining
locked set is 96 paths; `locked_launch_paths()` now returns 104, and
`docs/guides/execution_modes.md` states 104. The count is registry-derived and
will keep moving — the invariant is the subtractive rule, not the number. The
record also describes mode immutability as "downgrade-only at epoch
boundaries"; that is reserved design. `reconcile_resume_mode` implements only
persisted-mode-wins (a checkpoint with no `rqgm_state.json` is forced back to
`simple_bfts` with a warning), and `docs/guides/execution_modes.md`
§"Limitations (v1)" states there is no in-run transition at all. Neither
divergence touches what the GUI is permitted to do.

Owning tests: `ari-core/tests/test_gui_v1_mode_selection.py` (including
`TestDefaultPathUnchanged`, which pins the byte-identical default path),
`ari-core/tests/test_gui_v1_launch.py::TestLaunchValidation::test_governance_fields_stay_locked_after_adr09`,
and
`ari-core/ari/viz/frontend/src/components/ConfigStudio/__tests__/ConfigStudioExecutionMode.test.tsx`.
Implementation: `ari-core/ari/config/field_registry.py`,
`ari-core/ari/config/resolver.py` (`INTERLOCK_PAIRS` is an alias of
`MODE_INTERLOCK_PAIRS`), `ari-core/ari/viz/v1/config_api.py`
(`_validate_mode_pairs`, `_resolve_draft_manifest`, `_draft_validation_errors`),
`ari-core/ari/viz/v1/launch.py` (`locked_launch_paths`, `_mode_selection`,
`_mode_env`, `_merge_mode_blocks`), and the Configuration Studio components
`ExecutionSection.tsx`, `modeIntents.ts` and `LaunchPanel.tsx` under
`ari-core/ari/viz/frontend/src/components/ConfigStudio/`.
