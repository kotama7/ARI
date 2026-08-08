---
sources:
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/tests/test_manuscript_assurance_boundary.py
    role: test
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-09
---

# MC-ADR-007: no silent certified runner-up fallback

Decision: publication eligibility never silently replaces the scientific
winner with a certified runner-up. The alternative is reported and the winner
remains publication-blocked until an explicit selection decision creates a new
attempt. Automatic fallback hides the scientific subject change; rejecting all
alternatives loses useful diagnostics. Reverse only with a versioned selection
policy and mandatory disclosure. Owning tests: assurance-boundary and winner
selection tests.
