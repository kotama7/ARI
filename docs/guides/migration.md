---
sources:
  - path: ari-core/ari/migrations/v05_to_v07
    role: implementation
  - path: ari-core/ari/memory_cli.py
    role: implementation
last_verified: 2026-05-25
---

# Migration Guide

ARI's checkpoint format has evolved through three releases.  This
guide walks the upgrade paths.

| From | To | Headline change |
|---|---|---|
| v0.5 | v0.6 | Letta memory backend replaces JSONL |
| v0.6 | v0.7 | ORS / EAR registry / lineage decisions |
| v0.7 | v0.8 (future) | Refactored checkpoint format (`ari.public/` boundary) |
| v0.8 | v1.0 (future) | Legacy compatibility shims removed |

## v0.5 → v0.6

### What changed

- **Memory backend.**  `memory_store.jsonl` (per checkpoint) and the
  global `$HOME/.ari/global_memory.jsonl` (cross-experiment) are
  retired.  The default backend is now Letta (per-checkpoint agent
  with archival collections `ari_node_*` and `ari_react_*`).
- **`$HOME/.ari/` removed.**  v0.5.0 already deleted the global
  config directory; v0.6 makes the new layout the only writable
  surface.
- **Rubric system.**  `ari-skill-paper` adopted a YAML rubric
  selected by `ARI_RUBRIC`.

### Recipe

1. **Stand up a Letta service.**  Pick one of the deployment paths
   from `docs/hpc_setup.md#6-letta-memory-backend-deployment`:
   Apptainer SIF, docker-compose, or pip.
2. **Set the required env vars.**
   ```bash
   export LETTA_BASE_URL=http://127.0.0.1:8283
   export LETTA_EMBEDDING_CONFIG=/path/to/embedding.json
   export ARI_MEMORY_BACKEND=letta
   ```
3. **Migrate existing memory.**  In each v0.5 checkpoint:
   ```bash
   ARI_CHECKPOINT_DIR=/path/to/ckpt ari memory migrate
   ```
   The migrator reads `memory_store.jsonl` (and the legacy global
   JSONL if any), writes to the Letta agent, and snapshots the
   result into `memory_backup.jsonl.gz`.
4. **Delete the legacy JSONLs.**  After verifying the migration:
   ```bash
   rm /path/to/ckpt/memory_store.jsonl
   rm $HOME/.ari/global_memory.jsonl   # if it ever existed
   ```
5. **Pick a rubric.**  Choose a YAML from
   `ari-core/config/reviewer_rubrics/` and export it:
   ```bash
   export ARI_RUBRIC=neurips2025
   ```
   Subsequent paper review and BFTS scoring will use the new axes.

### Verification

- `ari memory health` returns `ok` and reports the agent name.
- A `search_memory` call from the agent loop returns embedding-
  ranked results.
- The dashboard `/api/memory/health` endpoint returns 200.

## v0.6 → v0.7

### What changed

- **ORS (Object Repository Spec).**  The reproducibility chain moved
  from `react_driver`'s ad-hoc replication to `ari-skill-replicate`
  (rubric generator) plus `ari-skill-paper-re` (PaperBench
  SimpleJudge grader).
- **EAR registry.**  EAR bundles can be published to a self-hosted
  `ari-registry` server (in addition to local-tarball / Zenodo /
  GitHub release).
- **Lineage decisions.**  `stagnation_rule` watches the BFTS
  composite score; when it fires, an LLM picks `continue` /
  `switch_to_idea` / `fanout` / `terminate`.  Decisions are
  appended to `lineage_decisions.jsonl`.
- **work_dir blacklist.**  Child node `work_dir` no longer inherits
  result files (`results.csv`, `slurm-*.out`, ...).  Existing
  checkpoints keep working but child runs that relied on inheritance
  must be re-run.

### Recipe

1. **Set up the rubric directory.**  Make sure
   `ari-core/config/reviewer_rubrics/` contains the rubrics you
   want.  `ARI_RUBRIC` selects the active one.
2. **(Optional) Stand up `ari registry serve`.**  Only required if
   you want to publish bundles via `ari://`.  Set
   `ARI_REGISTRY_DATA` first; `ARI_REGISTRIES_FILE` and
   `ARI_REGISTRY_TOKEN` configure the client side.
3. **Re-run sub-experiments that relied on result inheritance.**
   The blacklist guarantees children no longer copy
   `results.csv` / `slurm-*.out` / `node_report.json`.  Code,
   compiled binaries, and inputs still inherit.
4. **(Optional) Wire up the reproducibility flow.**  Once a paper is
   ready, run:
   ```bash
   ari ear curate <checkpoint>
   ari ear publish <checkpoint> --backend ari-registry
   ari replicate generate-rubric <checkpoint>
   ari paper-re grade <checkpoint>
   ```

### Verification

- `lineage_decisions.jsonl` is created the first time the
  stagnation rule fires.
- `manifest.lock` and `publish_record.json` appear after `ari ear
  publish`.

## v0.7 → v0.8 (future)

### Anticipated changes

- Skills can only import from `ari.public.*`.  The
  `tests/test_public_api_boundary.py` guard rail is already in
  place; v0.8 removes the deprecation shims.
- `ari/migrations/v05_to_v07/` housekeeping helpers move to a
  dedicated CLI surface (`ari migrate ...`) instead of being mixed
  into `ari run`.

### Pre-emptive steps

- Audit any custom skills for direct `from ari import <internal>`
  imports.  `python -m ari.dev.public_audit` (planned) lists them;
  for now `grep -rn 'from ari import\|from ari\.' my-skill/src/`
  works.
- Where you find an internal import, switch to the matching
  `ari.public.*` module (see `docs/reference/public_api.md`).

## v0.8 → v1.0 (future)

The deprecation programme (`CONTRIBUTING.md::Deprecation process`,
`docs/release_policy.md`) schedules:

- Removal of every `$HOME/.ari/...` filesystem fallback (currently
  emitting `DeprecationWarning`).
- Removal of `ari/migrations/v05_to_v07/` (forces users to migrate
  before upgrading).
- Removal of legacy `node_report` reconstruct helpers.

If you have not migrated by v1.0, ARI will refuse to launch with a
hard error pointing to this guide.

## See also

- `docs/refactor_audit.md` — current state of the migration debt.
- `CHANGELOG.md` — per-release notes.
- `ari memory migrate --help` — CLI options for the v0.5 → v0.6
  migrator.
- `docs/howto/troubleshooting.md` — what to do when migration
  fails.
