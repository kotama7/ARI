---
sources:
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/runtime.py
    role: implementation
  - path: ari-core/ari/manuscript/publication.py
    role: implementation
  - path: ari-core/ari/rqgm/paper_runtime.py
    role: implementation
  - path: ari-skill-paper/src/authoring.py
    role: implementation
  - path: ari-skill-paper/src/finalize.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-16
---

# MC-ADR-009: audit publication semantics

Decision: audit emits the same shadow readiness and publication gate structure
but does not change legacy writer inputs, PaperBuild status, or publication
behavior. A shadow `publishable` is diagnostic and is not a lock. Alternatives
were suppressing the decision or enforcing it in audit; the former prevents
migration measurement and the latter violates shadow compatibility. Reverse
only with a new mode. Owning tests: audit writer-input identity, decision
logical-AND, and off/audit dispatch tests.
