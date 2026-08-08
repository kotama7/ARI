---
sources:
  - path: ari-core/ari/viz/api_workflow.py
    role: implementation
  - path: ari-core/ari/viz/api_settings.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/viz/frontend/src/services/api/client.ts
    role: implementation
  - path: ari-core/ari/viz/frontend/src/components/Workflow/WorkflowPage.tsx
    role: implementation
  - path: ari-core/ari/viz/frontend/src/i18n/en.ts
    role: implementation
  - path: ari-core/tests/test_gui_workflow_write_guard.py
    role: test
last_verified: 2026-08-09
---

# GUI-ADR-10: bundled `workflow.yaml` write guard

Cited in source and tests as `ADR-10`. Accepted 2026-07-23 for the GUI refresh
program; it supersedes nothing and is not superseded — the Wave 2b
copy-on-write follow-up recorded below extends it rather than replacing it.

Context, as verified during the baseline audit: with no active checkpoint
selected, `POST /api/workflow`, `/api/workflow/flow`, `/api/workflow/skills`
and `/api/workflow/disabled-tools` rewrote the bundled
`ari-core/config/workflow.yaml` and answered success, changing without warning
the default pipeline that every later CLI and GUI run inherits. It compounded
an already confusing double-file semantics: an edit made with a checkpoint
active lands on that checkpoint's copy and affects only re-runs of the same
checkpoint, while a new launch always seeds itself from the bundled file, so
edits never propagate to a new run. Tracked as the program's risk RR-P0-1.

Decision: the four workflow-write endpoints refuse outright when no usable
checkpoint is active — HTTP 400, frozen refusal payload, no side effect — so
the bundled `workflow.yaml` is read-only from the GUI. CLI and hand editing of
that file are out of scope. Writes to the per-checkpoint copy stay as they
were, which keeps run-scoped editing. The check is one shared helper rather
than four copies, so a future write endpoint inherits it.

Two alternatives lost. An explicit opt-in, letting the user knowingly write
the bundled default, was rejected because the blast radius is every subsequent
CLI and GUI run and no per-request confirmation makes that visible at the
moment of clicking. Redirecting the write into a draft was rejected as needing
a draft layer that did not exist when the guard was needed; the draft layer
that later shipped (`create_run_draft` / `patch_run_draft` in
`ari-core/ari/viz/v1/config_api.py`) holds run configuration and never writes
`workflow.yaml`, so it would not have carried this case anyway.

Consequences accepted: a user who wants to edit a workflow must create or
select a run first — an added step with no lever to skip it; the behaviour
change (writes that used to appear to succeed now fail) is announced as
migration note MN-1; and no compatibility freeze was offered, because the old
behaviour was classified as a defect to repair, not a contract to preserve.
Saying *which run an edit affects* at save time was left to the Workflow
Studio work of a later wave; the guard deliberately shipped ahead of it.

Verified against the tree. `_workflow_write_guard` in
`ari-core/ari/viz/api_workflow.py` returns
`{"ok": False, "error": _NO_ACTIVE_CHECKPOINT_ERROR, "_status": 400}` when
`state._checkpoint_dir` is `None` or missing, and all four handlers call it
first (`_api_save_workflow` in `api_settings.py`; `_api_save_workflow_flow`,
`_api_save_skill_phases`, `_api_save_disabled_tools` in `api_workflow.py`);
`routes.py` pops `_status` into the HTTP status. No `/api/v1` route writes a
workflow, so the legacy four are the whole write surface. The Wave 2b
follow-up closed the residual case where a checkpoint is active but holds no
copy yet: `_checkpoint_workflow_path` copies the bundled file into the
checkpoint first and the edit lands on that copy. `POST /api/workflow` does
not use that helper — it seeds from the `path` the caller echoes back from
`GET /api/workflow` — but it too writes only `{checkpoint}/workflow.yaml`.

Where the code diverges from the record. The record says the GUI tells the
user why the write was refused, using the 400 error envelope. It does not: the
frontend's `post` in
`ari-core/ari/viz/frontend/src/services/api/client.ts` throws on any non-2xx
and discards the body, so the workflow page shows `POST /api/workflow/flow
failed: 400`. The refusal sentence exists only in `api_workflow.py` and its
test — no frontend file contains it. The save-time labelling of which run an
edit affects was still unbuilt when the program's plans were retired:
`frontend/src/components/Workflow/WorkflowPage.tsx` carries no
active-checkpoint or edit-scope wording and `frontend/src/i18n/en.ts` has no
such string. The guard itself shipped in Wave 2a, but
the RR-P0-1 risk row was never transcribed to closed — bookkeeping lag, not an
unfixed risk.

Permanent description: `docs/guides/migration.md`, section "Workflow editing
requires an active project (MN-1)", which quotes the frozen payload; and
`docs/reference/rest_api.md`, sections "Behaviour changes on the legacy
surface (MN notes)" and "Settings + workflow". Owning tests: the 16 cases in
`ari-core/tests/test_gui_workflow_write_guard.py` — a refusal test per
endpoint, a per-endpoint test that a write with a checkpoint active leaves the
bundled file byte-identical, four copy-on-write seeding tests, three direct
guard tests, and `test_frozen_payload_matches_module_constant`.
