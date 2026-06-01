# Migration & Requirement-Deletion Policy (requirement 14 — finalizer)

Task-control note from `14_migration_and_requirement_deletion.md`, the
meta-requirement that governs the lifecycle of all others and is finished last.
Captured 2026-05-30. No production code.

## What this requirement did

req-14 specifies policy, and (per its own §5) is deleted once the policy is
settled and recorded in the **durable** docs. Because the requirement file
itself is deleted, the binding policy was moved into `refactoring/GLOBAL_RULES.md`
(the authoritative reference that survives), adding three sections:

1. **Compatibility-wrapper removal policy** — wrappers stay until all call sites
   migrate; removal needs its own requirement; never removed in the introducing
   PR. (Lists the live wrappers this sequence introduced: the `ari.public.*`
   re-exports, the skills' public-first `cost_tracker` fallback, the
   `checkpoint_api` → `load_nodes_tree` fallback.)
2. **Package-move gate** — `ari-core/ari/viz` → top-level `ari-gui`/`ari-api` is
   forbidden in early refactoring; allowed only after 00/01 + the in-place
   refactors, via a dedicated migration requirement with a wrapper plan. (No
   package move was performed; everything was refactored in place.)
3. **Sequence completion + final cleanup** — when `requirements/` is empty the
   sequence is done; `refactoring/` may then be removed in a final cleanup PR,
   after folding durable `notes/` content into `docs/` / per-dir READMEs.

The requirement-file lifecycle rule (temporary files; record-in-COMPLETED +
delete in the **same PR**; no partial-credit deletion) was already in
`GLOBAL_RULES.md` and each requirement's §9/§10 — confirmed consistent.

## Consistency check (req-14 §8)

- **Execution order** in `README.md` matches the canonical 14-item list and the
  order actually executed: 00 → 01 → 13 → 02 → 03 → 04 → 05 → 06 → 07 → 08 → 09 →
  10 → 11 → 12 → 14. ✓
- **Deletion policy** in `GLOBAL_RULES.md` matches every requirement's §9/§10
  ("record in COMPLETED.md, then delete in the same PR; not for partial
  completion"). All 14 prior requirements followed it — each `COMPLETED.md` entry
  carries `Requirement file deleted: yes`. ✓
- **In-place rule**: `ari.viz` / `ari.viz.frontend` were refactored in place; no
  top-level `ari-gui`/`ari-api` introduced. ✓

## State of the sequence at req-14 completion

Recorded complete in `COMPLETED.md` (15 entries incl. this one):
00, 01, 02, 03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 14.

**Remaining in `requirements/`: `15_frontend_remaining_large_components.md`** — a
follow-up created during req-03 (decomposing the other large frontend pages:
WorkflowPage/StepResources/Settings/DetailPanel/Monitor + finer splits of
`resultSections.tsx` + the deferred container seams/hooks). It was NOT in the
original README execution order (the plan's order ended at 14); it is a
genuine, scoped follow-up, so the directory is **not** yet empty and the final
`refactoring/` cleanup is **not** yet due.

Per the lifecycle rule, this directory is removed only once `requirements/` is
empty — i.e. after `15` (and any further follow-ups it spawns) complete. The
documentation-only requirements (00, 01, 10, 11, 12, 13, this one) left durable
assessments under `refactoring/notes/` whose durable parts should be folded into
`docs/` (the glossary/rest_api/configuration docs already absorbed the 06/07/08
content) during that final cleanup.

## Deferred-work ledger (all recorded in their notes' §12)

The implementation requirements deferred real follow-ups (each its own future
requirement, per the wrapper-removal / behavior-change rules):
- req-03 → **req-15** (remaining large frontend components).
- req-04 → MonitorPage/SettingsPage/ResultsView `useApi` adoption; AppContext
  poll → `usePolling`.
- req-05 → the larger `routes.py` fat handlers (`/state` builder, container/pull,
  static-serving, SSE scaffolding).
- req-06 → broad `Settings`⇄`/api/settings` reconcile; generated-types/OpenAPI.
- req-07 → checkpoint-discovery facade; `paper/` helper; reduce
  `ari.viz.state` active-checkpoint global.
- req-08 → central `ari.config` resolver; `ARI_PAPER_LANGUAGE` CLI re-derive.
- req-09 → public re-exports for `ari.publish` / `ari.clone` / `ari.lineage` /
  a `node_selection` protocol (shrink the contract-guard allowlist).
- req-10 → FlowMapping seam; canonical Stage schema; StageRunner protocol;
  `context_builder` → `LLMClient`.
- req-11 → (proposal-only) route `context_builder` through `resolve_litellm_model`.
- req-12 → `api_memory` → container facet; paper-re reproduce → `SlurmClient`;
  managed-process Runner owning the handle registry (the `ari.viz.state` follow-up).

These are the live backlog beyond `15`; none is required for the planned
sequence's completion.

## Checks

No production code changed. Policy/docs only. The full suites remain green from
req 09–12 (`pytest ari-core/tests` 2231 passed; `run_all_tests.sh` 2843 passed).
