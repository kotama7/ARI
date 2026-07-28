# Task 02: EpochState and Registry

> **Status**: planned · **Depends on**: 00, 01 · **This is a temporary task plan** — see [INDEX.md](INDEX.md). It will be deleted once its deletion criteria are met.

## 1. Purpose

ARI-RQGM requires that, within one epoch, the active component set, prompt hashes,
utility policy, and scoring rule are **frozen** (global invariants 1–3, 10–12, 17), and
that all changes to component/prompt status happen only through an epoch-boundary
transaction validated by the ConstitutionalKernel. Today ARI has no epoch concept: BFTS
in-memory state does not survive `ari resume`, prompt identity exists only as the
`sha256[:12]` value from `FilesystemPromptLoader.load_versioned`, and no registry tracks
which component/prompt version produced which record.

This task designs the three foundational structures — **EpochState**,
**ComponentRegistry**, **PromptRegistry** — plus their checkpoint-scoped persistence,
the `prompt_hash`/`component_id`/`epoch_id` recording policy for every RQGM record, the
active-set freeze mechanism, and the epoch-boundary transaction protocol. Every later
task (Governance 05, TransitionEngine 09, FrontierRepair 10) reads or writes these
structures; none of them can be planned concretely without this state layer being fixed.

## 2. Scope

- Schema design for `EpochState`, `ComponentRegistry`, `PromptRegistry` (JSON Schema
  files + Python dataclasses).
- Decision and justification of the on-disk home for all three (checkpoint-scoped,
  event-log-as-truth + derived snapshots).
- `prompt_hash` computation policy relative to the existing prompt loader/snapshot
  infrastructure (reuse `hash12`, no second scheme).
- `component_id` / `epoch_id` / `prompt_hash` stamping policy for RQGM records, for
  `prompt_trace.jsonl` (the two reserved `PromptUseRecord` fields), and for
  `cost_trace.jsonl` (additive `epoch` metadata).
- Status lifecycle **enumeration and storage** (candidate → … → active → … → banned);
  a write API that only accepts status changes via transition events (invariant 10 at
  the storage layer).
- Active-set freeze: immutable per-epoch snapshot with a deterministic
  `epoch_fingerprint`.
- Epoch-boundary transaction: prepare/commit event protocol, crash recovery, resume
  reconstruction.
- Establishment of the RQGM **ImmutableAuditLog** file `{ckpt}/rqgm_audit.jsonl`
  (fixed filename, append-only hash-chained line envelope, filename-hygiene
  registration); the governance record *content* written into it is Task 05's (§5.9).
- `rqgm.enabled=false` compatibility guarantee: zero new files, zero behavior change.
- New `EpochStore` protocol beside the existing store protocols.

## 3. Non-goals

- **No implementation** in this task (plans only; implementation follows after review).
- Transition *rules* (which status changes are legal, promotion predicates) — Task 09.
- ConstitutionalKernel checks that *consume* these structures (epoch invariance,
  transition validation, audit integrity verification) — Task 04.
- The GovernanceOrchestrator audit *loop* (what gets audited, when, and by which
  submodule; which governance records are appended) — Task 05. The
  `rqgm_audit.jsonl` ImmutableAuditLog **file itself** (filename, hash-chain
  envelope, registration) is owned by this task (§5.9); Task 05 writes into it,
  Task 04 verifies it.
- PromptSpec content model, prompt evolution, candidate validation — Task 07. (This
  task registers prompt *identity + status + hash*; the spec payload is Task 07's.)
- Frontier staling / selective erasure semantics — Task 10.
- Epoch-boundary *triggering* policy (every N nodes vs. stagnation event) — Task 05
  decides when; this task defines what happens when the boundary fires.
- Cross-run (parent/fanout-child) epoch spanning — explicitly out of v1 scope; see §5.2.
- Mode-switch config plumbing (`ari.mode`, `RQGMConfig` on `ARIConfig`) — Task 01;
  this plan consumes `cfg.rqgm.*` as Task 01 defines it.

## 4. Existing ARI touchpoints

All paths repo-relative; verified to exist on branch `RQGM`.

| Touchpoint | Why it matters here |
|---|---|
| `ari-core/ari/paths.py` — `PathManager.META_FILES`, `_TRACE_FILES` | Every new checkpoint-root filename (`epoch_state.json`, `rqgm_registry.json`, `rqgm_transitions.jsonl`, `rqgm_audit.jsonl`) MUST be registered here, or it is copied into every node work dir and contaminates `node_report.files_changed`. |
| `ari-core/ari/checkpoint.py` — `JsonCheckpointStore`, `save_prompt_versions_json` shim | Template for the new snapshot writers (`save_epoch_state_json`, `save_rqgm_registry_json`): store method + module shim, `json.dumps(indent=2, ensure_ascii=False)`. |
| `ari-core/ari/prompts/_loader.py` — `FilesystemPromptLoader.load_versioned` | The existing prompt-hash primitive: `(text, sha256(text)[:12])`. RQGM `prompt_hash` **is** this value (§5.4). |
| `ari-core/ari/prompts/_provenance.py` — `hash12`, `PromptUseRecord`, `record_prompt_use` | `PromptUseRecord.prompt_version` and `.prompt_registry_version` are reserved always-`None` fields explicitly waiting for a registry layer; the epoch stamping policy (§5.5) fills them with zero schema break. Also the structural template for the new append-only event log (lock, run-pin no-op, never raises). |
| `ari-core/ari/prompts/registry.py` — `PromptRegistry`, `PromptEntry` | Existing *discovery catalogue* over committed `.md` templates. **Name collision** with the RQGM governance registry — resolved in §5.3 (different module + class name; the catalogue is delegated to, never replaced). |
| `ari-core/ari/protocols/stores.py` — `CheckpointStore`, `TraceStore` Protocols | The new `EpochStore` Protocol lands beside these, same structural-Protocol + module-shim style; stated file contract: "no on-disk contract changes here". |
| `ari-core/ari/orchestrator/lineage_decision.py` — `append_decision_log`, `read_decision_log` | The proven append-only JSONL discipline (self-contained records, returns bool, never raises into the loop) that `rqgm_transitions.jsonl` mirrors. |
| `ari-core/ari/cli/bfts_loop.py` — `_run_loop` outer `while` head; `_save_checkpoint` | The only natural epoch-boundary hook site (main thread, sees `all_nodes`/`frontier`/`pending`/`cfg`/`checkpoint_dir`); the prompt-versions rollup block (~line 917) is the template for best-effort snapshot emission. |
| `ari-core/ari/cli/run.py` — `run` / `resume` | `resume` rebuilds only a subset of Node state from `tree.json`; BFTS in-memory state starts empty → epoch state must be reconstructed from checkpoint files (§5.7). |
| `ari-core/ari/core.py` — `build_runtime` | Composition root; conditional construction precedent (`hpc_enabled` skill drop, `axis_mode` dispatch). The RQGM state layer is constructed here only when `cfg.rqgm.enabled` (wrapping, never extending the 6-tuple). |
| `ari-core/ari/config/__init__.py` — `ARIConfig`, `EvaluatorConfig`, `BFTSConfig` | Source of the utility-policy values frozen per epoch (`composite`, `axis_weights`, `frontier_score`); Task 01's `RQGMConfig` lives here. |
| `ari-core/ari/configs/defaults.yaml` | Sanctioned home for RQGM numeric defaults (e.g. default epoch length) per the PC7 precedent. |
| `ari-core/ari/schemas/node_report.schema.json` | Sibling location and style (draft-07, `schema_version` const) for the three new schema files, loadable via `ari.schemas.load` (flat basenames). |
| `ari-core/ari/cost_tracker.py` — `CallRecord`, `set_default_metadata` | Additive default-`None` `epoch` field + `set_default_metadata(epoch=...)` gives process-wide (skills included) per-epoch cost attribution with no reader breakage. |
| `ari-core/ari/trace_store.py` — `JsonlTraceStore.append_trace` | Dormant per-node JSONL seam; noted as the future per-node audit channel (adopted by Task 05, not here). |
| `ari-core/ari/orchestrator/node_report/builder.py` — blocklists (`_FILES_CHANGED_BLOCKLIST_NAMES`, `_INTERNAL_JSON_NAMES`) | New RQGM filenames must be added so they never appear as publishable artifacts or file diffs. |
| `ari-core/ari/lineage.py`; `ari-core/ari/viz/api_orchestrator.py` | Cross-run `meta.json` parent-pointer chain and child-launch gates; additive `meta.json` fields (`rqgm_epoch_id`) are the deferred cross-run channel (§5.2). |
| `ari-core/tests/test_prompt_provenance.py` — `test_new_filenames_are_meta_files` | Test pattern to copy for asserting META_FILES registration of the new filenames. |
| `docs/reference/file_formats.md`, `docs/reference/environment_variables.md` | Permanent docs that receive the new file formats on implementation (deletion criterion; note: documenting = SemVer freeze, so only the stable v1 surface goes there). |

## 5. Proposed design

### 5.1 On-disk home: checkpoint-scoped, JSONL-truth + derived snapshots

Four new checkpoint-root files (flat layout, per ARI convention; all registered in
`META_FILES`, the two JSONL files additionally in `_TRACE_FILES`):

| File | Pattern | Role |
|---|---|---|
| `{ckpt}/rqgm_transitions.jsonl` | append-only JSONL, hash-chained | **Source of truth.** Every epoch open/close, every registry status change, every registration event — one self-contained record per line. |
| `{ckpt}/rqgm_audit.jsonl` | append-only JSONL, hash-chained | **ImmutableAuditLog** (spec core-algorithm step 11). File established here (§5.9); governance record content written by Task 05's audit loop; chain integrity verified by Task 04. |
| `{ckpt}/epoch_state.json` | rewrite-whole snapshot | Derived rollup: the currently open (or last closed) EpochState. Fast-path read for the run loop, GUI, and resume. |
| `{ckpt}/rqgm_registry.json` | rewrite-whole snapshot | Derived rollup: current ComponentRegistry + PromptRegistry state in one file (one file keeps the two registries transactionally consistent and the META_FILES delta small). |

Justification:
- **Checkpoint-scoped** is mandatory (v0.5.0 invariant: `ARI_CHECKPOINT_DIR` is the
  single run pin, no `~/.ari`, hard CI gates). Nothing here introduces workspace-level
  or home-dir state.
- **JSONL-as-truth, snapshot-as-rollup** follows the strongest in-repo precedent
  (`prompt_trace.jsonl` → `prompt_versions.json`) and directly serves resume: snapshots
  can always be rebuilt by replaying the event log, so a torn snapshot write can never
  corrupt governance state.
- `tree.json` / `nodes_tree.json` / `results.json` / `meta.json` are **not touched**
  (contract-frozen key order; GUI + paper-pipeline consumers).
- Epoch-scoped *generated prompt text* (when Task 07 introduces it) will live under
  `{ckpt}/rqgm_prompts/` — this plan only reserves the directory name and the
  `source: checkpoint_file` reference kind (§5.3); nothing writes it in Task 02.

### 5.2 Epoch scope: one checkpoint

An epoch is scoped to **one run's checkpoint**. Rationale: all frozen quantities
(prompt set, utility policy, frontier) are per-run today; the lineage layer's
cross-run resolver (`_resolve_ckpt_by_run_id`) is scan-based and fragile; and the RQGM
paper's own freeze guarantees are per-archive. Child runs launched via
`switch_to_idea`/`fanout` start their own epoch 0. The only cross-run channel is
additive `meta.json` fields on the child (`rqgm_parent_epoch_id`,
`rqgm_registry_version`) written where `meta` is built in
`ari/viz/api_orchestrator.py`, read by nothing in Task 02 — reserved for a later task.

### 5.3 The three structures

New internal package `ari-core/ari/rqgm/` (NOT re-exported via `ari.public.*`, so no
public-API contract-snapshot churn):

- `ari/rqgm/state.py` — `EpochState` (frozen dataclass once the epoch opens).
- `ari/rqgm/registry.py` — `ComponentRegistry` and `GovernedPromptRegistry`.
  **Naming decision**: the on-disk/record name stays `PromptRegistry` (spec vocabulary),
  but the Python class is `GovernedPromptRegistry` to avoid colliding with the existing
  discovery catalogue `ari.prompts.registry.PromptRegistry`. The governed registry
  *delegates* template loading/hashing to the existing catalogue and loader; it never
  duplicates them.
- `ari/rqgm/events.py` — transition-event dataclasses + canonical hashing.
- `ari/rqgm/store.py` — `RqgmStateStore` implementing the new `EpochStore` Protocol,
  with module shims in `ari/checkpoint.py` style.

**ComponentRegistry** tracks components (`generator`, `reviewer`, `adversary`,
`defender`, `judge`, `router`, `prompt_mutator`, `clean_room_generator`,
`replay_selector`, plus the fixed-layer entries) with `tier` ∈
{`fixed`, `institutional`, `meta`} from day one (Task 11 needs it; adding it later
would be a schema bump). Fixed-tier entries are registered but constitutionally
immutable (their status can never leave `active`; enforced by Task 04/09).

**GovernedPromptRegistry** tracks prompt versions per role. Each entry references its
text by *source*, never inlines it:

- `source.kind = "committed_template"` → `source.key` is a `FilesystemPromptLoader`
  key (e.g. `orchestrator/bfts_expand`); hash obtained from `load_versioned`.
- `source.kind = "checkpoint_file"` → `source.path` relative to the checkpoint
  (reserved for Task 07 evolved prompts under `rqgm_prompts/`; carries the Gate-10
  carve-out decision, which stays in Task 07).

Status lifecycle (single shared enum for prompts and components; Task 09 owns the
transition *table*, this task owns the value set and storage):

```
candidate → validated → shadow → probationary_active → active
active → warning | probation | quarantine
quarantine → retired → banned
```

Storage-layer rule (invariant 10 enforced at the lowest level): registry objects
expose **no status setter**. The only mutation path is
`RqgmStateStore.apply_transition(events)` inside the epoch-boundary transaction; the
in-memory registries are rebuilt from the event log after commit.

### 5.4 prompt_hash: reuse the existing scheme, verbatim

- `prompt_hash` **is** `hash12(text) = sha256(text.encode("utf-8")).hexdigest()[:12]`,
  i.e. exactly the `version_id` returned by `FilesystemPromptLoader.load_versioned`
  and produced by `ari.prompts._provenance.hash12`. No second scheme is introduced
  (pinned by three existing test files and mirrored in skill-local loaders).
- Each PromptRegistry entry additionally stores `prompt_sha256` (full 64-hex digest)
  for collision-proof identification — precedented by
  `test_prompt_extraction.py::_EXPECTED_HASHES`. `prompt_hash` is derivable from it
  (first 12 hex chars); records carry only `prompt_hash`, registries carry both.
- Hashes are computed over **raw template bytes** (pre-`str.format`). Rendered-call
  provenance stays where it is today: `rendered_prompt_hash` in `prompt_trace.jsonl`.
- `registry_version = hash12(canonical_json(sorted entries))` where
  `canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False,
  separators=(",", ":"))` over `(prompt_id, role, status, prompt_sha256)` tuples.
  Deterministic; no wall-clock, git SHA, host, or absolute path enters any hash (P2).

### 5.5 epoch_id / component_id / prompt_hash recording policy

- Formats: `epoch_id = "epoch_%03d"` (per-checkpoint counter, starting `epoch_000`;
  exactly the spec's `epoch_004` form, and the form every other plan's schemas and
  examples already use); `component_id = "{role}_v{N}"`;
  `prompt_id = "{role}_prompt_v{N}"` (spec examples);
  `transition_id = "transition_%03d_to_%03d"`, embedding the two epoch sequence
  numbers at the same `%03d` width as `epoch_id` (e.g. `transition_003_to_004`
  for the `epoch_003` → `epoch_004` boundary; identical to the spec's
  `transition_004_to_005` example); `event_id = "evt_%06d"` (per-checkpoint
  monotonic counter over `rqgm_transitions.jsonl` lines, starting `evt_000000`).
- **Every RQGM record** (this task's events; later tasks' ProposalRecord,
  ReviewRecord, etc.) embeds the common base fields from the spec: `record_id`,
  `epoch_id`, `component_id`, `prompt_hash`, `role`, `created_at`, `source_refs`,
  `status`. This task publishes them as a shared JSON-Schema `$defs` block
  (`rqgm_record_base`) that the later schemas `$ref`.
- **prompt_trace.jsonl**: while an epoch is open, managed-prompt call sites that run
  under RQGM stamp `record_prompt_use(..., prompt_version=<prompt_id>,
  prompt_registry_version=<registry_version>)` — the two reserved fields fill without
  any schema break. Under `simple_bfts` / `rqgm.enabled=false` they remain `None`
  exactly as today.
- **cost_trace.jsonl**: at epoch open, the run loop calls
  `cost_tracker.set_default_metadata(epoch=<epoch_id>)`; `CallRecord` gains an
  additive default-`None` `epoch` field. Skills inherit it via the process-wide
  litellm injector. Budget *enforcement* stays out of scope (Task 12).
- **node linkage**: nodes are attributed to epochs via the transition log
  (`epoch_open` events record the node-count watermark) — `Node.to_dict()`,
  `tree.json`, and `node_report.schema.json` (`schema_version: const 1`) are NOT
  modified in this task. If a later task needs `epoch_id` inside node reports it must
  follow the optional-field-only-or-version-bump policy there.

### 5.6 Active-set freeze and the epoch-boundary transaction

**Freeze** (at epoch open):

1. Resolve the active set from the registries: `{role: component_id}` and
   `{role: prompt_hash}` for every role with an `active` (or `probationary_active`)
   entry.
2. Capture the utility policy from the resolved config: `evaluator.composite`,
   effective `axis_weights`, `bfts.frontier_score` (+ `depth_penalty_lambda`,
   `ucb_c`), and compute `utility_policy_hash = hash12(canonical_json(policy))`.
3. Construct `EpochState` and compute
   `epoch_fingerprint = hash12(canonical_json(EpochState minus metadata timestamps))`.
4. Persist: append `epoch_open` event; rewrite `epoch_state.json`.
5. `EpochState` is immutable in memory for the duration of the epoch (frozen
   dataclass); Task 04's `validate_epoch_invariance` later compares per-record
   `prompt_hash`/`component_id` against this frozen snapshot.

Score-comparability note: cross-epoch `_scientific_score` comparisons (Rule A,
stagnation detection, fallback ranking) are **epoch-relative by design**. This
task freezes the utility policy **per epoch**, which is what keeps comparisons
sound *within* one.

**Amended (Task 14).** This paragraph previously said the frozen policy is
"constant across epochs within a run (status quo preserved)" and deferred
per-epoch re-weighting to "a Task 10/13 decision (Q-40)". Both clauses are
repealed: [14_governed_utility_evolution.md](14_governed_utility_evolution.md)
§5.10 repeals invariant I-11 ("axes frozen per run") — it was a v1 deferral
recorded as behavior B-17 (Task 00 §5.8), never a property of the method, and it
contradicts pillar P1 — and designs the rewrite here, not in Task 10/13. The
policy is frozen per epoch and **rewritten at boundaries through the governed
path**, so a rewrite INVALIDATES cross-epoch comparability rather than
reconciling it. Task 02 froze the policy; Task 14 rewrites it. EpochState
already carried the fields, so the change was additive, as anticipated.

**Boundary transaction** (single writer: the `_run_loop` main thread at the outer
`while` head; multi-run coordination is out of scope by §5.2):

```
1. append event: epoch_transaction_prepare {transition_id, from_epoch, to_epoch}
2. append events: one per registry change (adopt/sanction/retire...), as provided
   by RegistryTransitionEngine (Task 09) and validated by the Kernel (Task 04)
3. append event: epoch_close {epoch_id, closing stats}
4. append event: epoch_open  {next epoch_id, frozen active set, fingerprint}
5. append event: epoch_transaction_commit {transition_id}
6. rewrite snapshots: rqgm_registry.json, epoch_state.json (best-effort, derived)
```

**Crash recovery rule**: on load, replay `rqgm_transitions.jsonl`; any events after
the last `..._prepare` **without** a matching `..._commit` are ignored (the
transaction never happened; the previous epoch is still open). Snapshots are
validated against replay and rebuilt on mismatch. This gives atomicity without file
locks beyond the existing single-writer discipline.

**Event integrity**: each event line carries
`event_hash = hash12(canonical_json(payload))` and `prev_event_hash` (of the previous
line; `""` for the first). Timestamps (`ts`, `ts_iso`) are metadata fields **outside**
the hashed payload, keeping P2's no-wall-clock-in-hashes rule intact. Verification of
the chain is Task 04's `validate_audit_log_integrity`; this task only writes the
fields. Like all ARI provenance writers, appends are lock-guarded, no-op without a
run pin, and never raise into the run loop.

### 5.7 Resume

`ari resume` restores RQGM state solely from the checkpoint: replay
`rqgm_transitions.jsonl` → rebuild registries and the open EpochState → verify
against snapshots → re-freeze in memory. No BFTS in-memory state is relied upon
(mirrors the tree.json subset-reconstruction reality). A checkpoint with **no** RQGM
files resumes exactly as today (absence-tolerant readers), including when a run
started under `simple_bfts` is resumed under `simple_bfts`. Switching mode at resume
time is a run-start switch and is allowed per Task 01; resuming `ari_rqgm` on a
checkpoint without RQGM files opens `epoch_000` fresh.

### 5.8 `rqgm.enabled=false` / `simple_bfts` compatibility

When `cfg.ari.mode == "simple_bfts"` or `cfg.rqgm.enabled == false` (Task 01 config):

- `build_runtime` constructs **nothing** from `ari/rqgm/`; the package is not imported
  on the hot path (lazy import behind the config gate, mirroring the
  `ari.memory`→skill funnel discipline).
- No RQGM file is created; `record_prompt_use` reserved fields stay `None`;
  `CallRecord.epoch` stays `None`; `_run_loop` behavior is byte-for-byte unchanged.
- All RQGM readers treat file absence as "RQGM never ran", never an error.

### 5.9 ImmutableAuditLog: `rqgm_audit.jsonl` (file owned here, content owned by Task 05)

The spec's ImmutableAuditLog (core algorithm step 11: log all outputs / judgments /
`prompt_hash` / `epoch_id`) lives at `{ckpt}/rqgm_audit.jsonl`. Ownership is split
explicitly so the artifact has exactly one owner per concern:

- **This task — the file.** Fixes the filename (Task 05 defers it here); defines the
  append-only, hash-chained line envelope, identical in discipline to
  `rqgm_transitions.jsonl` (§5.6): `event_hash = hash12(canonical_json(payload))`,
  `prev_event_hash` chaining, `ts`/`ts_iso` as metadata outside the hashed payload;
  writer behavior lock-guarded, no-op without a run pin, never raising into the run
  loop. Registers the filename in `META_FILES`, `_TRACE_FILES`, and the node-report
  blocklists (§8). Guarantees the file is never created under
  `rqgm.enabled=false` / `simple_bfts` (§5.8).
- **Task 05 — the content.** The GovernanceOrchestrator audit loop decides which
  governance records (observations, evidence bundles, motions, judgments,
  GovernanceReport, ...) are appended, and when; their payload schemas are Task
  05/06 deliverables.
- **Task 04 — the verification.** `validate_audit_log_integrity` checks the hash
  chain; Task 04 never writes.

`rqgm_transitions.jsonl` (§5.1) stays a separate file on purpose: it carries only
registry/epoch state-change events and must stay small enough for cheap replay at
resume (§5.7), while `rqgm_audit.jsonl` carries the high-volume per-node/per-epoch
governance evidence stream. The transaction protocol (§5.6) never depends on audit
volume.

## 6. Data structures / schema changes

New JSON Schemas (draft-07, flat basenames beside `node_report.schema.json`, loadable
via `ari.schemas.load`): `epoch_state.schema.json`, `rqgm_registry.schema.json`,
`rqgm_transition_event.schema.json`. All carry `"schema_version": {"const": 1}`.

**EpochState** (`epoch_state.json`):

```json
{
  "schema_version": 1,
  "record_id": "epochstate_epoch_004",
  "epoch_id": "epoch_004",
  "epoch_seq": 4,
  "previous_epoch_id": "epoch_003",
  "opened_by_transition_id": "transition_003_to_004",
  "status": "open",
  "run_id": "20260705..._slug",
  "node_count_at_open": 17,
  "active_components": {"reviewer": "reviewer_v3", "generator": "generator_v2"},
  "active_prompt_hashes": {"reviewer": "a1b2c3d4e5f6", "generator": "0f9e8d7c6b5a"},
  "utility_policy": {
    "composite": "harmonic_mean",
    "axis_weights": {"novelty": 1.0, "rigor": 1.0},
    "frontier_score": "scientific_plus_diversity",
    "depth_penalty_lambda": 0.05,
    "ucb_c": 0.5,
    "utility_policy_hash": "c0ffee123456"
  },
  "registry_version": "deadbeef0123",
  "epoch_fingerprint": "feedface4567",
  "created_at": "2026-07-05T12:00:00Z"
}
```

(`created_at` is metadata; excluded from `epoch_fingerprint`.)

**Registry snapshot** (`rqgm_registry.json`):

```json
{
  "schema_version": 1,
  "registry_version": "deadbeef0123",
  "as_of_event_hash": "77aa88bb99cc",
  "components": [
    {"component_id": "reviewer_v3", "role": "reviewer", "tier": "institutional",
     "status": "active", "prompt_id": "reviewer_prompt_v4",
     "epoch_id_registered": "epoch_002", "created_at": "...",
     "source_refs": ["transition_001_to_002"]}
  ],
  "prompts": [
    {"prompt_id": "reviewer_prompt_v4", "role": "reviewer", "status": "active",
     "prompt_hash": "a1b2c3d4e5f6",
     "prompt_sha256": "<full 64-hex>",
     "source": {"kind": "committed_template", "key": "evaluator/peer_review"},
     "spec_ref": null,
     "epoch_id_registered": "epoch_002", "created_at": "...",
     "source_refs": ["transition_001_to_002"]}
  ]
}
```

(`spec_ref` is a placeholder pointing at the Task 07 PromptSpec record; `null` in v1.)

**Transition event** (one line of `rqgm_transitions.jsonl`):

```json
{"schema_version": 1, "event_id": "evt_000042",
 "event_type": "prompt_status_change",
 "payload": {"prompt_id": "reviewer_prompt_v4", "from_status": "shadow",
             "to_status": "probationary_active",
             "transition_id": "transition_003_to_004",
             "epoch_id": "epoch_004", "component_id": "reviewer_v3",
             "role": "reviewer", "prompt_hash": "a1b2c3d4e5f6",
             "source_refs": ["governance_report_epoch_003"]},
 "event_hash": "112233445566", "prev_event_hash": "77aa88bb99cc",
 "ts": 1751700000.0, "ts_iso": "2026-07-05T12:00:00Z"}
```

Event types (closed set, v1): `epoch_transaction_prepare`, `component_registered`,
`prompt_registered`, `component_status_change`, `prompt_status_change`,
`epoch_close`, `epoch_open`, `epoch_transaction_commit`, `emergency_quarantine`
(the sole mid-epoch mutation, per the spec's emergency exception; still logged and
kernel-validated).

Shared `$defs`: `rqgm_record_base` (`record_id, epoch_id, component_id, prompt_hash,
role, created_at, source_refs, status`) and the status enum
(`candidate|validated|shadow|probationary_active|active|warning|probation|quarantine|retired|banned`).

`rqgm_audit.jsonl` lines reuse the same outer envelope (`event_id`, `event_type`,
`payload`, `event_hash`, `prev_event_hash`, `ts`, `ts_iso`) with an independent
per-file hash chain; the governance `payload` schemas inside it are owned by
Tasks 05/06 (§5.9) and are **not** part of this task's three schema files.

Config sketch (keys live in Task 01's `RQGMConfig`; numeric defaults in
`ari-core/ari/configs/defaults.yaml`):

```yaml
rqgm:
  enabled: false
  epoch:
    boundary: node_count      # v1: only node_count; trigger policy detail in Task 05
    nodes_per_epoch: 10
```

Additive dataclass fields: `CallRecord.epoch: str | None = None` (cost_tracker);
`PromptUseRecord` unchanged (fields already exist).

## 7. API / class changes

All internal (`ari/rqgm/`), nothing added to `ari.public.*`, no CLI surface change
(contract snapshots untouched).

```python
# ari/protocols/stores.py  (addition)
@runtime_checkable
class EpochStore(Protocol):
    def load_state(self, checkpoint_dir) -> "RqgmRuntimeState | None": ...
    def append_events(self, checkpoint_dir, events: list["TransitionEvent"]) -> bool: ...
    def save_snapshots(self, checkpoint_dir, state) -> None: ...   # best-effort
    def replay(self, checkpoint_dir) -> "RqgmRuntimeState | None": ...

# ari/rqgm/state.py
@dataclass(frozen=True)
class EpochState: ...                     # fields as in §6
def freeze_epoch(registries, cfg, *, epoch_seq, node_count) -> EpochState: ...
def epoch_fingerprint(state: EpochState) -> str: ...   # hash12 of canonical payload

# ari/rqgm/registry.py
class ComponentRegistry:                  # read-only view + registration via events
    def get(self, component_id) -> ComponentEntry | None: ...
    def active_set(self) -> dict[str, str]: ...          # role -> component_id
class GovernedPromptRegistry:
    def get(self, prompt_id) -> GovernedPromptEntry | None: ...
    def active_prompt_hashes(self) -> dict[str, str]: ...  # role -> prompt_hash
    def resolve_text(self, prompt_id) -> tuple[str, str]: ...
        # delegates to FilesystemPromptLoader.load_versioned for
        # committed_template sources; checkpoint_file kind deferred to Task 07
    def registry_version(self) -> str: ...

# ari/rqgm/store.py
class RqgmStateStore:                     # implements EpochStore
    def begin_transaction(self, transition_id) -> "EpochTransaction": ...
class EpochTransaction:                   # context manager: prepare .. commit
    def add(self, event: TransitionEvent) -> None: ...
```

No existing public function signature changes. `build_runtime` gains a config-gated
internal branch (no return-tuple change). `_run_loop` gains one best-effort,
config-gated hook call at the outer-loop head (lineage-hook pattern: try/except +
warn; a state-layer failure degrades to "epoch continues", never crashes the run —
fail-closed semantics, if any, are a Task 04 decision).

## 8. Migration / compatibility

- **No migration needed**: no existing file is reshaped; all three files are new and
  additive. Old checkpoints have no RQGM files and keep resuming unchanged.
- `simple_bfts` (default): zero construction, zero writes, zero reads (§5.8) — existing
  ARI behavior preserved verbatim.
- `ari_rqgm` is opt-in via Task 01 config; nothing enabled by default.
- VirSci independence: this task neither reads nor requires anything VirSci-related;
  registries register VirSci-generator prompts only if Task 03 does so when
  `proposal_router.generators.virsci.enabled=true`. With VirSci off, no VirSci prompt
  is ever registered (spec guarantee, enforced at registration call sites in Task 03).
- `prompt_trace.jsonl` / `cost_trace.jsonl` readers: additive-default fields only;
  old files parse; absence = no data.
- Filename hygiene: `epoch_state.json`, `rqgm_registry.json`, `rqgm_transitions.jsonl`,
  `rqgm_audit.jsonl` added to `META_FILES`, `_TRACE_FILES` (JSONL), node-report
  blocklists, and `_INTERNAL_JSON_NAMES` — otherwise they leak into node work dirs
  and `files_changed`.
- readme-sync: new files under `ari-core/ari/` and `ari-core/tests/` get README
  Contents rows; new schema files likewise.

## 9. Tests

Unit (in `ari-core/tests/`, `monkeypatch.setenv("ARI_CHECKPOINT_DIR", tmp_path)`
convention, no `~/.ari` writes):

1. `test_rqgm_state_store.py` — event append/replay round-trip; prepare-without-commit
   events are discarded on load; snapshot rebuilt on snapshot/replay mismatch.
2. Hash discipline — `event_hash`/`prev_event_hash` chain over canonical payloads;
   timestamps excluded from hashes; `registry_version` and `epoch_fingerprint`
   deterministic across two processes (P2); source-grep test for forbidden imports
   (mirror `test_recorder_is_offline_no_llm_or_network_imports`).
3. `prompt_hash` equivalence — registry `prompt_hash` == `load_versioned(key)[1]` ==
   `hash12(text)` for every committed-template entry (mirrors
   `test_template_hash_matches_load_versioned`).
4. Freeze immutability — `EpochState` is frozen; mutation attempts raise; active set
   captured at open does not track later registry objects.
5. Status write-path — registries expose no setter; only
   `EpochTransaction.add` + commit changes status; `emergency_quarantine` is the sole
   accepted mid-epoch event type.
6. META_FILES registration — new filenames asserted in `PathManager.META_FILES` /
   `_TRACE_FILES` / node-report blocklists (pattern:
   `test_prompt_provenance.py::test_new_filenames_are_meta_files`).
7. `rqgm.enabled=false` regression — `build_runtime` + a stubbed `_run_loop` pass
   leaves the checkpoint with **no** RQGM file; `PromptUseRecord` reserved fields
   stay `None`; `CallRecord.epoch` stays `None`; `ari/rqgm` not imported
   (`sys.modules` assertion).
8. Resume — replay-only reconstruction (snapshots deleted) equals snapshot fast-path;
   resuming a non-RQGM checkpoint under `simple_bfts` behaves exactly as today.
9. Stamping — with an open epoch, `record_prompt_use` receives
   `prompt_version`/`prompt_registry_version`; `cost_tracker` records carry `epoch`.
10. Schema validation — all three schemas validate their example payloads and reject
    missing base fields; schemas load via `ari.schemas.load`.

Integration/smoke: an `ari_rqgm`-mode mini-run (2 epochs × 2 nodes, stub LLM) opens
`epoch_000`, crosses one boundary transactionally, and leaves a verifiable event
chain — shared with Task 01's mode smoke test.

Regression guard: full existing ari-core suite green with the feature merged and
disabled (CI runs it hard via refactor-guards; note MEMORY: unbounded pins mean CI
uses latest deps — keep new tests duck-typed).

## 10. Risks

- **Boundary placement churn**: Task 05 may redefine when boundaries fire; mitigated
  by keeping trigger policy out of this task (storage/transaction API is
  trigger-agnostic).
- **Name collision confusion** (`PromptRegistry`): mitigated by
  `GovernedPromptRegistry` class name, module separation, and a docstring
  cross-reference in both modules.
- **Snapshot drift vs. event log**: torn writes could desynchronize rollups; mitigated
  by replay-verify-on-load and treating snapshots as disposable.
- **Hash-chain novelty**: no existing ARI log is tamper-evident; a canonicalization
  bug would poison Task 04's integrity check permanently within a run. Mitigated by
  pinning `canonical_json` with byte-golden tests before anything consumes it.
- **Hot-path overhead**: per-event fsync-free appends are cheap, but snapshot rewrites
  at every boundary must stay off the per-node path (boundary-only, best-effort).
- **Freeze vs. `probationary_active`**: treating probationary prompts as part of the
  frozen active set may complicate Task 09's shadow semantics; flagged for Task 09 to
  confirm or split.
- **Registry growth**: unbounded event logs across very long runs; acceptable v1
  (lineage_decisions.jsonl precedent), revisit with Task 12 budgets.

## 11. Completion criteria

Spec Task 02 criteria, made concrete:

1. **All three schemas defined**: `epoch_state.schema.json`,
   `rqgm_registry.schema.json` (components + prompts), and
   `rqgm_transition_event.schema.json` drafted in this plan (§6) with example
   payloads, a shared `rqgm_record_base` `$defs`, the status enum, and
   `schema_version: 1` policy — ready for implementation without further design.
2. **prompt_hash / component_id / epoch_id recording policy clear**: §5.4–§5.5 fix the
   hash scheme (reuse `hash12`, full sha256 stored registry-side), id formats,
   the mandatory base fields on every RQGM record, the `PromptUseRecord`
   reserved-field stamping rule, and the `CallRecord.epoch` attribution rule.
3. **Active set freeze specified**: §5.6 defines freeze inputs (active components,
   prompt hashes, utility policy), the immutable `EpochState`, the deterministic
   `epoch_fingerprint`, and the epoch-boundary prepare/commit transaction with crash
   recovery and the single-writer rule.
4. Additionally (required by the task-specific guidance): the persistence home is
   decided and justified (§5.1 checkpoint-scoped, JSONL-truth + snapshots), status
   lifecycle values and the no-setter storage rule are fixed (§5.3), resume behavior
   is specified (§5.7), `rqgm.enabled=false` compatibility is stated with a
   testable guarantee (§5.8, test 7), and the `rqgm_audit.jsonl` ImmutableAuditLog
   is established — filename, hash-chain envelope, registration — with content
   ownership delegated to Task 05 (§5.9).

## 12. Deletion criteria

This plan file may be deleted only when all of the following hold:

- The target feature/design is merged into the main branch.
- Corresponding tests have been added.
- CI is green.
- Key design decisions have been moved to permanent docs or code comments.
- No unresolved open questions remain, or they have been moved to another task plan.
- No downstream task depends solely on this plan file.
- INDEX.md task status has been updated to completed/deleted.
- Developers will not be confused by this file's absence.
- The deleted content remains available in git history.

Task-specific criteria (from the spec's Task 02 section):

- The three structures (EpochState, ComponentRegistry, PromptRegistry) are
  implemented.
- Hashes/ids (`prompt_hash`, `component_id`, `epoch_id`) are recorded on records as
  specified in §5.5.
- `rqgm.enabled=false` leaves existing behavior unchanged (verified by the
  regression test of §9.7 and the full existing suite).
- The registry lifecycle (status enum + event-only mutation rule) has been moved to
  permanent docs (schema reference / developer guide; file formats documented in
  `docs/reference/file_formats.md`).
- Tests have been added (the suite of §9).

## 13. Delete-after checklist

Verify before deleting this file:

- [ ] Implementation is complete.
- [ ] Tests exist.
- [ ] CI is green.
- [ ] Key design decisions have been moved to permanent docs.
- [ ] Unfinished items have been moved to another task plan.
- [ ] INDEX.md has been updated.
- [ ] Deleting this plan file will not strand any developer.
- [ ] The deletion reason can be stated in the commit message.

Task-specific items:

- [ ] `epoch_state.json`, `rqgm_registry.json`, `rqgm_transitions.jsonl`, and
      `rqgm_audit.jsonl` are registered in `META_FILES` / `_TRACE_FILES` /
      node-report blocklists and documented in `docs/reference/file_formats.md`.
- [ ] `prompt_hash` scheme reuse (no second scheme) is asserted by a test and noted
      in the schema reference.
- [ ] The `GovernedPromptRegistry` vs `ari.prompts.registry.PromptRegistry`
      distinction is documented in both modules' docstrings.
- [ ] Open items handed off: boundary trigger policy → Task 05; transition table →
      Task 09; `spec_ref`/checkpoint-file prompt sources and Gate-10 carve-out →
      Task 07; per-epoch utility re-weighting → Task 10/13; cross-run epoch fields →
      recorded in INDEX.md.
