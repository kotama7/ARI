---
sources:
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/segments.py
    role: implementation
  - path: ari-core/ari/manuscript/repair.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-09
---

# MC-ADR-001: runtime namespace

Decision: Manuscript-owned immutable attempts, transitions, segment records,
and repair transactions live under checkpoint-local `.ari-manuscript/`.
Research source records intentionally consumed by snapshots remain at the
checkpoint root. Alternatives were mixing files into RQGM state or PaperBuild
directories; both obscure ownership and couple independent axes. Compatibility:
`mode=off` never creates the namespace. Reverse only with an atomic migration
that preserves old paths and hash chains. Owning tests:
`test_off_is_exact_no_artifact_identity`, segment and state tests.
