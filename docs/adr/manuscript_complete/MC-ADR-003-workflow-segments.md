---
sources:
  - path: ari-core/config/workflow.yaml
    role: config
  - path: ari-core/ari/core.py
    role: implementation
  - path: ari-core/ari/manuscript/segments.py
    role: implementation
  - path: ari-core/tests/test_workflow_contract.py
    role: test
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-16
---

# MC-ADR-003: one segmented workflow

Decision: add `segment` metadata to the one existing workflow and derive
disabled-stage views per invocation. A separate manuscript workflow is
prohibited. Alternatives were duplicated YAML and stage-name hardcoding;
both drift from legacy order. Compatibility: the legacy all-stage call ignores
segment selection. Reverse only if a new workflow contract proves ordering and
dependency parity. Owning test: segment freshness/reuse
(`test_manuscript_complete.py`). The workflow-contract and
pipeline-architecture tests assert nothing about segments, and the two
segment-selection guards in `ari/core.py` are untested.
