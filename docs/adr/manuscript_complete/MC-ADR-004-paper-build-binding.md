---
sources:
  - path: ari-core/ari/paper_contract.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-skill-paper/src/authoring.py
    role: implementation
  - path: ari-skill-paper/src/finalize.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-16
---

# MC-ADR-004: PaperBuild companion binding

Decision: preserve `PaperBuildV1` and add manuscript artifact roles plus a
digest-bound `ManuscriptAuthoringBindingV1`; publication decision/lock remain
companions. Replacing PaperBuild would break legacy readers and conflate build
success with publication permission. Compatibility: extra roles are required
only in enforce. Reverse only in a versioned PaperBuild migration. Owning tests:
paper authoring/finalizer contract tests and publication logical-AND/freshness.
