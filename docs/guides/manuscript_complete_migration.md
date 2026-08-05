# Manuscript Complete migration and rollback

Legacy checkpoints are never retroactively declared complete.

- `off` performs no migration and creates no `.ari-manuscript` directory.
- `audit` lazily inventories the files that still exist. Historical gaps remain
  `missing` or `unavailable`; they are not reconstructed as successful facts.
- `enforce` requires a fresh current profile/readiness before new authoring and
  a fresh publication decision before lock.

Recommended migration procedure:

1. Copy or retain the legacy checkpoint unchanged.
2. Run `ari manuscript compile CHECKPOINT --mode audit`.
3. Inspect omissions, negative lanes, and unresolved requirements.
4. Select explicit recovery, retrieval, experiment, certification, disclosure,
   or human actions. Never edit the old paper/build to manufacture evidence.
5. Compile an enforce attempt and author a new bound build only when ready.
6. Keep the old paper as a legacy artifact; do not overwrite its historical
   status with the new decision.

Rollback changes configuration back to `off`. Additive attempts remain for
forensics and can be archived with the checkpoint. A rollback must not delete
repair failures, blocked drafts, or old publication decisions.

Known legacy information loss includes bounded configuration, claim, reference,
source, and prompt projections. Audit reports what is still observable and an
omission reason where possible; absence of historical bytes is not evidence
that an item never existed.
