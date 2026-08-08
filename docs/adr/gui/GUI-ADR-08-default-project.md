# GUI-ADR-08: the implicit default project maps to the checkpoint search bases

Context: accepted 2026-07-23. The charter's baseline recorded that in the
shipped implementation project, run and checkpoint are the same thing — the
`YYYYMMDDHHMMSS_<slug>` directory name *is* the id, discovered by scanning a
fixed list of checkpoint search bases — and that separating `Project` from
`Run` is greenfield, so the
first implementation may start from a mapping onto one implicit default
project. The same document fixed the constraint that makes the mapping cheap:
filesystem artifacts stay the source of truth and the GUI's index / read model
is rebuildable derived data. Real multi-project persistence (creation, naming,
permissions) could not be settled until the configuration control plane landed
a Project scope, but `/api/v1` needed a project resource before that.

Decision: `/api/v1` exposes exactly one virtual project — `project_id` is the
literal `default` — and writes no file for it.
`ari.viz.v1.queries.list_projects` builds it at read time: `checkpoint_roots` are the search bases that exist
(deduplicated, from `ari.viz.checkpoint_finder._checkpoint_search_bases` via
the `api_state` facade) and `run_count` is the length of the scan. Its run list
is the existing checkpoint scan, not a new enumeration: the same
`^[0-9]{8,14}_` name filter and the same `experiments` / `__pycache__` /
`.git` skip set as the legacy listing, and the same one-portfolio ordering —
newest mtime first *after* the roots are merged, so which root was scanned
first cannot decide what "latest" means. `run_id` stays the checkpoint
directory name, which keeps the id identical to the legacy list's `id` and to
every existing fixture; the slug after the timestamp prefix is served
separately as `display_name` and is presentation only, never identity. Any
other project id gets a typed 404 envelope, from the run list and from the
project config endpoints alike.

The source record enumerated no rejected alternatives; it stated the decision,
its consequences and its supersedes line only. Nothing is reconstructed here,
because what the deciders weighed and set aside is not recoverable from the
decision or from the code.

Consequences accepted: the project has no lifecycle — no create, rename or
delete route exists for it, and clients read `projects[0]` without looking
further. Because nothing is persisted, adding or removing a search base
changes the project's contents immediately and deterministically; there is no
stale index to reconcile. Disambiguating identical checkpoint directory names
found under two different bases was deliberately left open, matching the
pre-existing behaviour: both directories are listed, they carry the same
`run_id`, and every run-scoped read resolves to whichever base
`checkpoint_finder._resolve_checkpoint_dir` reaches first.

Supersedes / superseded-by: first decision on this subject; not superseded. A
revision is reserved for the point where real multi-project persistence lands,
and GUI-ADR-12 depends on that revision — its `gui_store/project_config.json`
is a singleton only because this record says there is one project.

Divergence from the code: the record justified itself partly by claiming the
`/api/v1` URL structure would be project-scoped from day one and so avoid a
breaking change later. Only two paths carry the segment —
`/api/v1/projects/{project_id}/runs` and
`/api/v1/projects/{project_id}/config`. Every run-scoped endpoint is
`/api/v1/runs/{run_id}/…`, and the launch is `POST /api/v1/runs`, with no
project anywhere; `project_id` in a URL or cache key therefore narrows
nothing, and multi-project support will still have to decide what to do with
those paths. The "writes no file" rule also holds only for the enumeration
this record covers: GUI-ADR-12 later attached a durable singleton document,
`{workspace_root}/gui_store/project_config.json`, reached through `GET` and
`PATCH /api/v1/projects/default/config`.

Permanent references: `docs/concepts/gui_architecture.md`, section "5. The
entity model is one level deep"; `docs/reference/rest_api.md`, section
"Projects and runs".

Owning tests: `ari-core/tests/test_gui_v1_api.py` —
`test_projects_happy_path`, `test_runs_happy_path`,
`test_run_portfolio_is_globally_newest_first_across_roots`,
`test_unknown_project_returns_404_envelope` and `test_gets_are_side_effect_free`
(the project and run GETs write nothing into the checkpoint base);
`ari-core/tests/test_gui_v1_config_crud.py` — `test_unknown_project_is_404`.
