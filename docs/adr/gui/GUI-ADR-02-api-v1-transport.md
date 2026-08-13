---
sources:
  - path: ari-core/ari/viz/v1/router.py
    role: implementation
  - path: ari-core/ari/viz/routes.py
    role: implementation
  - path: ari-core/ari/viz/v1/errors.py
    role: implementation
  - path: ari-core/ari/viz/v1/dto.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.py
    role: implementation
  - path: ari-core/ari/viz/v1/openapi.json
    role: schema
  - path: ari-core/ari/viz/v1/__init__.py
    role: implementation
  - path: ari-core/ari/viz/__init__.py
    role: implementation
  - path: ari-core/pyproject.toml
    role: config
  - path: ari-core/ari/viz/frontend/package.json
    role: config
  - path: scripts/snapshot_contracts.py
    role: implementation
  - path: .github/workflows/contracts.yml
    role: config
  - path: .github/workflows/refactor-guards.yml
    role: config
  - path: ari-core/tests/test_gui_v1_api.py
    role: test
  - path: ari-core/tests/test_contract_snapshots.py
    role: test
  - path: ari-core/ari/viz/frontend/src/__tests__/v1TypesDrift.test.ts
    role: test
  - path: docs/concepts/gui_architecture.md
    role: doc
last_verified: 2026-08-13
---

# GUI-ADR-02: `/api/v1` transport and OpenAPI generation

Status: accepted (2026-07-23).

Decision: the canonical dashboard API lives under `/api/v1` and is built on the
stdlib `ThreadingHTTPServer` the server already runs — no FastAPI, no uvicorn,
no new runtime dependency. Routing is an in-repo declarative
`(method, path template, handler)` table, `ROUTES` in `ari/viz/v1/router.py`,
reached from the `/api/v1/` branch of `routes.py`; the router mints a
`request_id` per dispatch. Every v1 error is the envelope
`{code, message, details, request_id, retryable}` over a frozen code
vocabulary (`ari/viz/v1/errors.py`). DTOs are pydantic v2 models
(`ari/viz/v1/dto.py`; `pydantic>=2.13.4` is already an `ari-core` dependency).
`ari/viz/v1/openapi.py` derives OpenAPI 3.1 from exactly two sources — that
route table and the DTO JSON schemas — and emits it byte-stably, with the
result committed as `ari/viz/v1/openapi.json`. TypeScript types are generated
from that file by `openapi-typescript`, a frontend devDependency
(`npm run gen:v1types` → committed `src/services/api/v1types.gen.ts`); no
runtime client library is added.

Rejected: FastAPI/uvicorn, which the migration plan had already ruled against
by committing to keep the existing server deployment and static-bundle serving,
and which the repo's CI-pin history argues against — an unbounded new pin lets
CI install a newer release than the local one, so "green locally" stops meaning
"green in CI". Also rejected: hand-written TS types or a runtime-generated
client. Generating from the same table that dispatches is what makes the
contract undriftable, and a runtime client would re-add the dependency the
transport choice existed to avoid.

Consequences: routing, request validation and middleware equivalents are
in-repo assets to maintain, because there is no framework to inherit them from,
and a connection occupies a worker thread for as long as it is open, so
blocking work in a handler costs a thread rather than a coroutine (both are
described in `docs/concepts/gui_architecture.md`, "7. The backend seam"). The
unversioned endpoints stay in service as compatibility facades and migrate to
`/api/v1` gradually — GUI-ADR-11 defers its own endpoint-removal timing to this
facade policy. Drift is caught by tests instead of a framework. Owning tests:
`test_gui_v1_api.py::test_openapi_committed_matches_generated` and
`::test_openapi_covers_every_route_and_is_deterministic`; the frontend
`src/__tests__/v1TypesDrift.test.ts` re-runs openapi-typescript in memory and
asserts byte equality with the committed types. Legacy shape is frozen
separately by `scripts/snapshot_contracts.py` / `tests/test_contract_snapshots.py`.

Supersedes: nothing (first decision); not superseded. The `ari/viz/__init__.py`
docstring this ADR flagged as wrongly claiming FastAPI has since been corrected
and now states that neither FastAPI nor uvicorn appears under `ari/viz`.

Divergences from the decision as written. The migration step this ADR
implemented was "add `/api/v1` read-only resources and OpenAPI", and
`ari/viz/v1/__init__.py` still describes the package as "versioned read-only";
the surface has since grown mutations — the committed document covers GET,
POST, PUT, PATCH and DELETE across 36 paths, and the router now parses the
`If-Match` optimistic-concurrency header and translates a stale precondition
into the frozen 409 envelope (added under GUI-ADR-12 and GUI-ADR-05), so that
docstring is stale. And of the two backend drift gates, only the pytest
snapshot blocks: `pytest ari-core/tests/` runs in `refactor-guards.yml`, while
`scripts/check_viz_api_schema.py` runs in `contracts.yml` as `--warning-only`
under `continue-on-error: true`, not as the ratcheted `--fail-on-regression`
hard gate the plan called for. The frontend types drift test is a vitest test
with no workflow invoking it.
