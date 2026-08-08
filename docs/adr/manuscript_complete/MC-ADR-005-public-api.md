---
sources:
  - path: ari-core/ari/public/manuscript.py
    role: implementation
  - path: ari-core/ari/manuscript/coordinator.py
    role: implementation
  - path: ari-core/ari/manuscript/state.py
    role: implementation
  - path: ari-core/tests/test_contract_snapshots.py
    role: test
  - path: ari-core/tests/fixtures/contracts/public_api.json
    role: test
last_verified: 2026-08-09
---

# MC-ADR-005: stable read API

Decision: export frozen V1 models, the coordinator's `compile_manuscript`
entry point, and pure projection/evaluator helpers through
`ari.public.manuscript`; keep the mutable state store, runtime adapter, and
segment executor private. Internal-only APIs would force consumers to import
unstable modules, while exporting the state store would freeze mutation
semantics prematurely.
Compatibility is tracked by the public contract snapshot. Reverse by deprecating
symbols through the normal public-API policy. Owning tests: public API and
contract snapshot tests.
