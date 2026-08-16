---
sources:
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/contracts.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-16
---

# MC-ADR-002: attempt identity

Decision: attempt ID is derived from the complete source-snapshot digest and
profile digest. A differing payload at an existing immutable path is an error,
not an overwrite. Alternatives were timestamps and mutable “latest” folders;
neither detects stale reuse deterministically. Compatibility: old attempts are
retained and a new source creates a new sibling. Reverse only with a versioned
identity and collision migration. Owning tests: deterministic compile, digest
tamper, transition-chain, and auto-resume tests.
