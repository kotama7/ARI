# MC-ADR-004: PaperBuild companion binding

Decision: preserve `PaperBuildV1` and add manuscript artifact roles plus a
digest-bound `ManuscriptAuthoringBindingV1`; publication decision/lock remain
companions. Replacing PaperBuild would break legacy readers and conflate build
success with publication permission. Compatibility: extra roles are required
only in enforce. Reverse only in a versioned PaperBuild migration. Owning tests:
paper authoring/finalizer contract tests and publication logical-AND/freshness.
