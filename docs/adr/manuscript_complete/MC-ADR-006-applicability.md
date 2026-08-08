---
sources:
  - path: ari-core/ari/manuscript/builder.py
    role: implementation
  - path: ari-core/ari/manuscript/profiles.py
    role: implementation
  - path: ari-core/ari/manuscript/readiness.py
    role: implementation
  - path: ari-core/ari/manuscript/snapshot.py
    role: implementation
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
  - path: ari-core/tests/fixtures/manuscript_complete/factory.py
    role: test
last_verified: 2026-08-09
---

# MC-ADR-006: applicability inputs

Decision: stochastic, comparative, and ablation applicability derives from
typed measurements/configurations, metric vocabulary, contributions, and node
labels. Reviewer or writer prose is not an applicability input. Alternatives
were manual free text and LLM classification; neither is replay-stable.
Compatibility: profile/evaluator versions bind the decision. Reverse only with
a new profile/evaluator version and labelled-fixture evaluation. Owning tests:
profile/readiness determinism and fixture evaluation tests.
