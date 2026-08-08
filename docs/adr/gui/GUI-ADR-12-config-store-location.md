---
sources:
  - path: ari-core/ari/viz/v1/store.py
    role: implementation
  - path: ari-core/ari/paths.py
    role: implementation
  - path: ari-core/ari/viz/v1/config_api.py
    role: implementation
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/v1/launch.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: .github/workflows/refactor-guards.yml
    role: config
  - path: scripts/check_directory_policy.py
    role: implementation
  - path: ari-core/tests/test_gui_v1_store.py
    role: test
  - path: ari-core/tests/test_gui_v1_config_crud.py
    role: test
  - path: ari-core/tests/test_gui_v1_launch.py
    role: test
last_verified: 2026-08-09
---

# GUI-ADR-12: GUI config document store location

Decision (ADR-12, accepted 2026-07-23): the GUI-only configuration documents live
under `{workspace_root}/gui_store/`, a sibling of `checkpoints/` —
`project_config.json` (the single virtual `default` project of ADR-08),
`run_templates/{template_id}.json`, `run_drafts/{draft_id}.json`. The root is
resolved by `ari.paths.RuntimePathResolver.resolve_workspace_root()`, the same
policy every other workspace consumer uses (`ARI_CHECKPOINT_DIR` wins). Every
document is the envelope
`{"schema_version": 1, "kind": ..., "revision": n, "body": {...}}` serialized
deterministically (`sort_keys`, 2-space indent, trailing newline), with `kind` one
of `project_config` / `run_template` / `run_draft`. `revision` is a per-document
integer starting at 1 and incremented on every write; it is the
optimistic-concurrency token, so `write(expected_revision=k)` raises
`RevisionConflict` unless the current revision is exactly `k`, `0` meaning "must
not exist yet" (create-only) and `expected_revision=None` meaning unconditional
last-write-wins. Writes are atomic and durable — same-directory temp file, fsync,
`os.replace`, best-effort directory fsync — with files `0o600` and store
directories `0o700`: the owner-only mode, in-process lock, temp file, fsync and
atomic replace required of the secret write path, applied here to config that is not
secret. Document ids are supplied by the caller — the store never invents one — and
must fullmatch `^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$`, which admits no `/` and no `.`, so
path traversal is structurally impossible rather than filtered out. The isolation
requirement it discharges is that a client-supplied identifier never determines a
path outside the managed root. The CLI and the `simple_bfts` path never read
`gui_store/`: it is a GUI convenience layer, and launch still materializes every
effective value into the checkpoint (`launch_config.json` and its siblings), so
checkpoint artifacts and resume semantics are unchanged.

Alternatives were: per-run storage under `{ckpt}/` — rejected because run templates
and project defaults are longer-lived than a run and must survive the GUI's own
checkpoint-delete action; the repository `config/` tree — rejected because this is
user data, not repository data, and writing user state into the repo tree collides
with the directory policy (the shipped `workflow.yaml` there is write-guarded by
ADR-10); and a home-directory `~/.ari` global dir — rejected because the project
retired global dirs and nothing may depend on one existing, a rule CI enforces
(`.github/workflows/refactor-guards.yml` fails a new `~/.ari/` reference outside the
allowed deprecation sites, and fails if pytest creates `$HOME/.ari/` at all).

Consequences accepted: `gui_store/` is generated at runtime under the workspace and
never appears in the repo tree, so `scripts/check_directory_policy.py` needs no
entry for it — its Rule B polices only the top-level storage-family basenames
`checkpoint(s)`, `experiment(s)`, `staging`, `workspace(s)`, `run(s)`, and
`gui_store` is outside that family. Store lifetime is independent of checkpoint
lifetime, which means drafts accumulate: a draft outlives the launch it fed until
something deletes it, and nothing does — there is still no
`DELETE /api/v1/run-drafts/{draft_id}` route. Multi-project support would have to
extend the `project_config.json` singleton (for example to `projects/{project_id}.json`)
in a revision of this record. Supersedes: nothing, this is the first decision on the
question. Superseded by: nothing.

Program context this record replaces (the plan documents are deleted): the
configuration control plane specified seven scopes, of which Project default (project
config), Run template (versioned template) and Run draft (a document editable until
launch) were greenfield — the implementation's scope was effectively two-valued,
machine/env plus per-checkpoint, with project ≡ run ≡ checkpoint directory and no
global settings location — and the plan explicitly deferred "where these live and who
owns them" to an ADR. This is that ADR; the resolution order it feeds is schema
default → workflow default → execution profile → installation policy → project
default → run template → run draft override → allowed environment override →
validated effective config. The storage contract is now documented permanently in
`docs/reference/configuration.md` under §"GUI document store (`gui_store/`)".

Divergences from the tree as of this migration: the record decided that the HTTP
layer returns `ETag: "<revision>"`. It does not — no response sets an `ETag` header
and `ari-core/ari/viz/v1/openapi.json` declares none. `revision` travels in the JSON
body, the client sends it back as `If-Match: "<revision>"` (quoted or bare;
`router._parse_if_match` rejects weak validators), and the mapping to status codes is
the decided one: stale precondition → 409 `revision_conflict`, missing `If-Match` on a
PATCH/DELETE → 400 `invalid_request`, create collision → 409 `already_exists`. Draft
ids are not caller-supplied or deterministic: `POST /api/v1/run-drafts` mints
`draft-<12 hex>` from `uuid4` server-side and writes with `expected_revision=0`; the
caller-supplied-id property survives for templates and for the launch idempotency key.
The route layer also narrows template ids to lowercase `^[a-z0-9][a-z0-9_-]{0,63}$`,
tighter than the store regex. The store grew a fourth kind after this decision,
`launch` (`launches/{idempotency_key}.json`), holding idempotent-launch replay records
so a duplicate `POST /api/v1/runs` replays the same run across a server restart. And
the record scoped itself to the storage layer with routes deferred; those routes have
since shipped in `ari-core/ari/viz/v1/config_api.py`.

Owning tests: `ari-core/tests/test_gui_v1_store.py` (round-trip envelope and
deterministic serialization, monotonic revisions and `RevisionConflict`, crash-before-
replace leaving the previous document intact, `0o600`/`0o700` modes re-asserted on
rewrite, deterministic listing, id validation and traversal rejection, corrupt-document
semantics, and `TestFromEnv::test_checkpoint_dir_env_wins`, which pins the store to the
`checkpoints/` sibling and asserts the checkpoint tree is untouched),
`ari-core/tests/test_gui_v1_config_crud.py`, and
`ari-core/tests/test_gui_v1_launch.py`. Implementation:
`ari-core/ari/viz/v1/store.py`, with `ari-core/ari/viz/v1/config_api.py`,
`ari-core/ari/viz/v1/router.py` and `ari-core/ari/viz/v1/launch.py` as its only
consumers — nothing in `ari/` outside `ari.viz.v1` imports the store.
