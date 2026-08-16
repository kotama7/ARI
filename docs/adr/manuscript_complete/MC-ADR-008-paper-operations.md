---
sources:
  - path: ari-core/ari/cli/projects.py
    role: implementation
  - path: ari-core/ari/cli/paper_dispatch.py
    role: implementation
  - path: ari-core/ari/cli/run.py
    role: implementation
  - path: ari-core/ari/cli/manuscript.py
    role: implementation
  - path: ari-core/ari/cli/manuscript_repair_runtime.py
    role: implementation
  - path: ari-core/tests/test_paper_mode.py
    role: test
  - path: ari-core/tests/test_manuscript_complete.py
    role: test
last_verified: 2026-08-16
---

# MC-ADR-008: operations allowed from `ari paper`

Decision: `ari paper` may run deterministic projection, compile readiness,
authoring, and verification, but receives no research repair executor. New
retrieval, experiment, certification, catalog promotion, or human decisions
must use `ari run`, `ari resume`, or explicit `ari manuscript repair`.
Delegating experiments to paper/archive would create recursive research search
and broaden authority. Reverse only with a new explicit command contract and
non-nesting proof. Owning tests: dispatch topology. The denial itself is
unasserted: `ari paper` simply omits `repair_executors=` at its
`run_paper_phase` call, and no test inspects that argument list.
