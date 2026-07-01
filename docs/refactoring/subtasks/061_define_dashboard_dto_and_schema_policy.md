# Subtask 061: Define Dashboard DTO and Schema Policy

> Phase 5: Dashboard Frontend
> Classification: **KEEP** (net-new policy artifact; ratifies decisions, redefines no runtime code)
> Runtime code change: **No** — Inventory: **No** (`docs/refactoring/007_subtask_index.md:108`)
> Inventory gate: **059** (`inventory_dashboard_frontend_backend_structure`); strongly consumes **060** (`inventory_dashboard_api_contracts`)
> Grounds: **062** (backend routes → services), **063** (FE API client + types), **065** (dashboard contract + schema tests) — `007_subtask_index.md:266`
> Coordinates with: **022** (`define_dashboard_dto_and_schema_tests`, Phase 4 backend counterpart), **030** (`add_viz_api_schema_checker_script`), **010** (`contract_preservation_policy`)

This document is a **PLANNING / POLICY** artifact. It changes **no runtime code**,
no imports, no prompts, no configs, no workflows, no `frontend/` TypeScript, and
no directory names. The only file it produces is this `.md`. It is self-contained:
a fresh coding session should be able to execute the downstream subtasks (062, 063,
065) after reading Sections 5, 6, 7, and 10. All paths are absolute-from-repo-root
(`/home/t-kotama/workplace/ARI`) and were verified 2026-07-01.

---

## 1. Goal

Produce a single, authoritative **Dashboard DTO & Schema Policy** that the
downstream Phase-5 subtasks (062 backend routes→services, 063 FE API client+types,
065 contract+schema tests) implement against without re-litigating design
questions. The policy must fix, as normative rules:

1. **Canonical wire contract.** Declare the **060 API-contract inventory** the
   single source of truth for every dashboard endpoint's path, method, JSON keys,
   status codes, and headers; declare the backend response dicts and the frontend
   TypeScript types **two typed views** of that one frozen contract, neither of
   which may drift from it.
2. **Response envelope.** Ratify the two envelopes that already coexist on the
   wire — `{"ok": bool, ...}` (launch/stage family) and `{"error": str}`
   (file/PaperBench family) — as the **only** two canonical envelopes, map each
   existing endpoint to one, and forbid inventing a third.
3. **Status handling.** Replace the `r.pop("_status", 200)` status-smuggling
   convention (`ari-core/ari/viz/routes.py:1047-1057,1088-1089`) with an explicit
   `(body, status)` return from the service layer — **without changing any wire
   status code**.
4. **Frontend DTO home.** Fix where TypeScript request/response DTOs live: shared
   domain/state types stay in `ari-core/ari/viz/frontend/src/types/index.ts`; the
   ~28 per-endpoint DTO interfaces currently inlined in `services/api.ts` are
   **ADAPT** — relocated into `src/types/`, leaving `services/api.ts` as a pure
   transport module.
5. **Client error regime.** Collapse the two divergent client regimes — `get`/
   `post` **throw** on non-2xx (`api.ts:18,24`) vs `pbGet`/`pbPost` **swallow** and
   return `{error}` bodies (`api.ts:~787,~792`) — into **one** typed transport
   contract, while preserving every wire shape.
6. **Schema source of truth.** Wire the already-shipped-but-orphaned JSON Schemas
   (`ari-core/ari/schemas/node_report.schema.json`,
   `ari-core/ari/schemas/publish.schema.json`; loaded via `ari.schemas.load()`,
   **no production importer today** — `007_subtask_index.md:169`) into the
   dashboard's `NodeReport` / publish DTOs, and pin the FE interfaces to them.
7. **Backend DTO technology.** Fix the stack: Pydantic v2 (already a dependency,
   `2.12.5`, used by `ari-core/ari/config/__init__.py` and re-exported via
   `ari.public.config_schema`) validates **untrusted POST request bodies**; typed
   response objects (dataclass/`TypedDict`) shape responses that serialize
   **byte-compatibly** through the existing `_json` helper (`routes.py:1190`).
8. **Public-boundary rule.** DTO construction in the service layer must depend on
   `ari.public.*`, not reach into internal `ari.paths` / `ari.checkpoint` /
   `ari.config.auto_config` / `ari.llm.client` / `ari_skill_memory.backends`
   modules the way today's route handlers do.

Success = a fresh coding session opening subtask 062, 063, or 065 can read this one
document and know, without further design work, the exact DTO shapes, envelope
conventions, schema bindings, and error contract every refactored handler and every
FE type must satisfy.

## 2. Background

The dashboard is **not** a green-field API. Its wire contract already exists and is
consumed by exactly one client; this policy ratifies and constrains that contract.

**Backend (`ari-core/ari/viz/`).** A framework-free stdlib `http.server` app (no
Flask/FastAPI/ASGI). Route dispatch is two giant `if/elif` chains over `self.path`
inside one `BaseHTTPRequestHandler` subclass `_Handler`
(`routes.py:144-1026` GET, `1028-1188` POST). There is **no schema/validation
layer and no DTOs**: POST bodies are raw `bytes` → `json.loads(body)` inside each
handler; responses are ad-hoc `dict`s serialized by `_json(data, status)`
(`routes.py:1190-1197`). Two response conventions coexist —
`{"ok": bool, ...}` and `{"error": str}` (occurrence counts by module: `file_api.py`
≈28, `api_paperbench.py` ≈28, `api_settings.py` ≈15, `api_experiment.py` ≈10) — and
HTTP status is smuggled through the body via `r.pop("_status", 200)`
(`routes.py:1047-1057,1088-1089`). Handlers also reach into internal (non-`public`)
modules (`ari.paths.PathManager`, `ari.checkpoint`, `ari.config.auto_config`,
`ari.llm.client.LLMClient`, `ari_skill_memory.backends.get_backend`) directly.

**Frontend (`ari-core/ari/viz/frontend/`).** Vite 5 + React 18.3 + TypeScript 5.5.
Types are split across two homes:

- `src/types/index.ts` (264 lines) — shared domain/state types: `TreeNode`,
  `Checkpoint`, `Settings` (~37 declared fields, `:38-75`), `CostSummary` (`:79-85`),
  `AppState` (`:87-129`, including the JS-compat aliases `running`/`pid`/`llm_model`
  at `:118-120` that duplicate `is_running`/`running_pid`/`llm_model_actual`),
  `WorkflowStage`/`WorkflowData`, `ResourceMetrics`, `ReviewReport` (`:204-229`),
  `ReproReport` (`:235`), `CheckpointSummary` (`:237-264`).
- `src/services/api.ts` (863 lines) — the typed REST client, `API_BASE = ''`
  (same-origin), **~28 per-endpoint DTO interfaces declared inline** alongside the
  fetch wrappers (`MemoryEntry`, `MemoryResponse`, `NodeReport` at `:124-153`,
  `EARData`, `PublishSettings`, `PublishRecord`, `SubExperiment`, `ContainerImage`,
  `CheckpointFile`, `RubricSummary`, `FewshotListing`, …). Transport is four helpers:
  `get`/`post` (`:18,24`, throw on `!res.ok`) and `pbGet`/`pbPost` (`:~787,~792`,
  PaperBench regime that **never throws** and returns `{error}` bodies — the header
  comment at `api.ts:~780-785` documents this on purpose).

**Existing schema assets (currently under-used).** `ari-core/ari/schemas/` ships two
JSON Schemas (draft-07) with a `load(name)` / `schema_path(name)` loader
(`__init__.py`): `node_report.schema.json` (4.3 KB; `schema_version: const 1`;
`required` = `node_id,label,depth,status,files_changed,metrics,artifacts`) and
`publish.schema.json` (2.5 KB; carries a backend-name enum at `publish.schema.json:51`).
A repo-wide grep for `ari.schemas`/`schemas.load`/`*.schema.json` finds **no Python
production importer** — the schemas are shipped but not enforced
(`007_subtask_index.md:169`). Separately, `ari-core/ari/config/__init__.py` defines
Pydantic v2 models (`LLMConfig:14`, `SkillConfig:43`, `BFTSConfig:66`,
`CheckpointConfig:161`, `LoggingConfig:170`, `EvaluatorConfig:204`, `ARIConfig:241`)
re-exported through the stable `ari.public.config_schema` surface — so Pydantic is
already a first-class, blessed way to type ARI data.

The Phase-4 viz track already produced adjacent artifacts this policy must line up
with: **022** `define_dashboard_dto_and_schema_tests` (backend *shape* tests) and
**030** `add_viz_api_schema_checker_script` (`check_viz_api_schema.py`, a *path-set*
reconciliation gate). Subtask 061 is the Phase-5 **policy** that unifies both the
backend and frontend sides so 062/063/065 land against one rulebook.

> **`sonfigs/` note.** The master prompt's `sonfigs/` directory **does not exist**
> anywhere in the repo. The confusable trio is `ari-core/ari/config/` (locator
> code) vs `ari-core/ari/configs/` (packaged defaults) vs top-level
> `ari-core/config/` (rubric/profile data). None of them is a DTO/schema concern
> and none is touched here.

## 3. Scope

In scope — **decisions only**, captured in this document:

- The **canonical wire contract** rule binding backend dicts and FE types to the
  060 inventory (RULE-SSOT).
- The **two-envelope** ratification and the endpoint→envelope mapping rule
  (RULE-ENV).
- The **explicit `(body, status)`** service-return rule that retires `_status`
  smuggling without changing wire status codes (RULE-STATUS).
- The **FE DTO home** rule (shared `types/`, no inline DTOs in `services/api.ts`)
  and its per-interface classification (RULE-FE-HOME).
- The **single client error contract** rule (RULE-CLIENT).
- The **schema-binding** rule that un-orphans `ari/schemas/*.json` and pins the FE
  `NodeReport`/publish types to them (RULE-SCHEMA).
- The **backend DTO technology** rule (Pydantic for request validation; typed
  response objects that serialize byte-compatibly) (RULE-TECH).
- The **public-boundary** rule for DTO construction (RULE-PUB).
- The **JS-compat alias** freeze rule for `AppState` (RULE-ALIAS).
- A per-artifact **KEEP / ADAPT / MERGE / MOVE_TO_LEGACY / DELETE_CANDIDATE /
  REVIEW_REQUIRED** classification table (Section 7.10).

Out of scope (delegated / deferred):

- **Any** edit to `ari-core/ari/viz/*.py`, to `services/api.ts` / `types/index.ts`,
  or to endpoint paths/JSON keys/status codes — those are executed by **062**
  (backend) and **063** (frontend) under this policy, not here.
- **Writing the contract/schema tests** — that is **065** (and, on the backend,
  **022**); this doc only defines what they must assert.
- **The route-registry refactor** (replacing the `if/elif` dispatch) — **062**;
  the policy only fixes the DTO/envelope contract that survives it.
- **State/component decomposition** (god-components like `resultSections.tsx` 1590,
  `SettingsPage.tsx` 1049) — **064**.
- **HTTP framework swap, auth/CSRF, CORS tightening** — explicitly *not* a DTO/schema
  decision; separate concerns (security posture noted in the 059 inventory).
- **Settings information-architecture / progressive disclosure** — Phase 6
  (067–073); this policy only fixes the `Settings` **DTO**, not its UI grouping.

## 4. Non-Goals

- **NOT** renaming, adding, removing, or reordering any dashboard endpoint, HTTP
  method, JSON key, status code, header, or WebSocket message type. Every wire shape
  is preserved (guarded downstream by 030's `check_viz_api_schema.py` and 065's
  contract tests).
- **NOT** changing the `_json` serializer's bytes (`json.dumps(..., ensure_ascii=False)`
  + `Access-Control-Allow-Origin: *`, `routes.py:1190-1197`) — response DTOs must
  serialize to the *same* bytes.
- **NOT** flipping `pbGet`/`pbPost` from swallow-to-throw in a way that changes what
  a PaperBench component observes; the unification (RULE-CLIENT) preserves the
  observable outcome.
- **NOT** introducing a wire-level envelope version field or an API version prefix
  (would break the frozen contract); drift is controlled by inventory + tests, not
  by versioning the wire.
- **NOT** deprecating anything: the `AppState` JS-compat aliases and the `repo`/
  `repro` vestigial fields are **preserved back-compat**, and the term "deprecated"
  is reserved for external contracts, never for these internal fields.
- **NOT** an LLM or network task; the policy is deterministic prose (design
  principle P2 applies to the tooling it grounds).

## 5. Current Files / Directories to Inspect

Verified 2026-07-01; line counts from `wc -l` unless noted.

Backend DTO/response surface (`ari-core/ari/viz/`):

| Path | LOC | Relevance to this policy |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` | 1197 | `_json(data, status)` (`:1190`); `_status` smuggling (`:1047-1057,1088-1089`); the inlined `/state` builder (`:219-666`); wildcard CORS header. |
| `ari-core/ari/viz/api_experiment.py` | 929 | `/api/launch`, `/api/run-stage`, `/api/logs` (SSE); `{"ok"}` envelope + `_status`. |
| `ari-core/ari/viz/api_paperbench.py` | 813 | `/api/paperbench/*`; the `{"error"}` (200-status) envelope consumed by `pbGet`/`pbPost`. |
| `ari-core/ari/viz/api_settings.py` | 553 | `/api/settings` DTO (round-trips the flat settings object). |
| `ari-core/ari/viz/api_workflow.py` | 462 | `/api/workflow*`; feeds `WorkflowData`/`WorkflowStage`. |
| `ari-core/ari/viz/checkpoint_api.py` | 327 | `/api/checkpoints`, `/api/checkpoint/<id>/summary`; feeds `Checkpoint`, `CheckpointSummary`. |
| `ari-core/ari/viz/file_api.py` | 307 | `{"error"}` envelope + `_status`; file save/delete/compile DTOs. |
| `ari-core/ari/viz/ear.py` | 452 | `/api/nodes/<rid>/<nid>/report` → `NodeReport`; EAR DTOs. |
| `ari-core/ari/viz/api_publish.py` | 191 | `/api/publish/*` → publish DTOs (relate to `publish.schema.json`). |
| `ari-core/ari/viz/websocket.py` | 36 | Single `{"type":"update","data":<tree>,"timestamp":...}` message (a DTO too). |

Shipped schema assets:

| Path | Size | Relevance |
| --- | --- | --- |
| `ari-core/ari/schemas/__init__.py` | 21 lines | `load(name)` / `schema_path(name)` loader. |
| `ari-core/ari/schemas/node_report.schema.json` | 4.3 KB | Draft-07; `schema_version: const 1`; binds `/api/nodes/.../report` DTO. |
| `ari-core/ari/schemas/publish.schema.json` | 2.5 KB | Draft-07; backend-name enum at `:51`; binds `/api/publish/*` DTO. |
| `ari-core/ari/schemas/README.md` | — | Points at `docs/reference/file_formats.md`. |
| `ari-core/ari/config/__init__.py` | ~628 lines | Pydantic v2 models (LLM/BFTS/…/`ARIConfig`), the DTO-tech precedent. |
| `ari-core/ari/public/config_schema.py` | 26 lines | Stable re-export of those models; the blessed typing surface. |

Frontend type/transport surface (`ari-core/ari/viz/frontend/`):

| Path | LOC | Relevance |
| --- | --- | --- |
| `src/types/index.ts` | 264 | Shared domain/state types; `AppState` JS-compat aliases `:118-120`; `CheckpointSummary` `:237-264`. |
| `src/types/README.md` | — | Per-directory README (must stay accurate if 063 adds files here). |
| `src/services/api.ts` | 863 | Transport (`get`/`post`/`pbGet`/`pbPost`) + ~28 inline DTO interfaces (ADAPT targets). |
| `src/services/README.md` | — | Describes `api.ts`/`websocket.ts`. |
| `src/services/websocket.ts` | small | WS client URL (mirror of `websocket.py` message DTO). |

Upstream planning inputs (read, do not modify):

- `docs/refactoring/007_subtask_index.md:106-113` (Phase-5 rows), `:255-273`
  (Phase-5 narrative, incl. `:266` "061 grounds 062/063/065"), `:169`
  (`ari.schemas.load()` has no production importer), `:247-252` (022/030 context).
- `docs/refactoring/010_contract_preservation_policy.md` — the dashboard-API-is-a-
  preserved-contract rule this policy inherits.
- `docs/refactoring/008_viz_dashboard_refactoring_plan.md`,
  `docs/refactoring/014_dashboard_ux_refactoring_plan.md`.
- Subtask **059** (FE/BE structure inventory) and **060** (API contract inventory)
  — the frozen inputs this policy binds to.

## 6. Current Problems

Grounded, verified 2026-07-01:

1. **No DTO layer; two response envelopes; status is smuggled.** Handlers hand-build
   dicts and split between `{"ok": bool}` and `{"error": str}` with no shared type;
   HTTP status rides inside the body via `r.pop("_status", 200)`
   (`routes.py:1047-1057,1088-1089`). A refactor cannot safely reshape a handler
   because nothing pins the response contract in code.
2. **Two client error regimes are a documented contract hazard.** `get`/`post`
   throw on non-2xx (`api.ts:18,24`); `pbGet`/`pbPost` never throw and return
   `{error}` bodies (`api.ts:~787,~799`). A component written against the wrong
   regime silently mishandles errors. The header comment at `api.ts:~780-785`
   admits this is deliberate mirroring of pre-existing call-site behavior — i.e. it
   is frozen accidental complexity, not a design.
3. **DTOs live in two homes with no rule.** ~28 response/request interfaces are
   inlined in the 863-line transport module (`services/api.ts`) while the shared
   domain types sit in `types/index.ts` (264). There is no policy for which type
   goes where, so every new endpoint re-litigates it.
4. **Shipped schemas are orphaned.** `ari-core/ari/schemas/node_report.schema.json`
   and `publish.schema.json` exist with a loader but **no production importer**
   (`007_subtask_index.md:169`), while the very shapes they describe
   (`/api/nodes/.../report`, `/api/publish/*`) are re-typed by hand in both the
   backend dicts and the FE `NodeReport`/publish interfaces — three uncoordinated
   copies of one shape.
5. **DTO construction bypasses `ari.public.*`.** Handlers reach directly into
   `ari.paths.PathManager`, `ari.checkpoint`, `ari.config.auto_config`,
   `ari.llm.client.LLMClient`, and `ari_skill_memory.backends.get_backend`
   (`routes.py:203-205`), so response shapes are coupled to internal module layout
   the refactor intends to move.
6. **`AppState` carries duplicated fields with no canonical rule.** `running`/`pid`/
   `llm_model` (`types/index.ts:118-120`) duplicate `is_running`/`running_pid`/
   `llm_model_actual`; the type comments call them "JS-compat aliases" but no policy
   states which is canonical or forbids adding more, inviting further drift.
7. **No agreed DTO technology.** Pydantic v2 is available and already used for config
   (`ari/config/__init__.py`), yet the viz layer parses untrusted POST JSON with bare
   `json.loads` and zero validation — a strategy gap 062/063 will otherwise each
   resolve differently.

## 7. Proposed Design / Policy

**Policy statement.** The dashboard has exactly one wire contract (the 060
inventory). The backend response dicts and the frontend TypeScript types are two
*typed views* of that contract. This subtask fixes the DTO home, envelope,
status-return, error-regime, schema-binding, technology, and boundary rules so that
062/063/065 can implement typed views that provably serialize to — and validate
against — the unchanged wire. Every rule below is **contract-preserving**: it changes
internal representation, never the bytes on the wire.

### 7.1 RULE-SSOT — one contract, two views

- The **060 `inventory_dashboard_api_contracts`** artifact is the **single source of
  truth** for endpoint path, method, JSON keys, status codes, and headers.
- Backend response objects (062) and FE types (063) MUST each reconcile against 060;
  neither is authoritative over the other. Drift is caught by 030's path checker and
  065's shape tests, not by human review.
- No endpoint, key, or status code is invented, renamed, or dropped by any subtask
  governed by this policy.

### 7.2 RULE-ENV — two canonical envelopes, frozen

- The wire has exactly **two** response envelopes and no more:
  - **Success/result envelope** `{"ok": true, ...}` (with the `"ok": false` failure
    variant) — used by the launch/run-stage/mutation family.
  - **Error-body envelope** `{"error": "<message>", ...}` at HTTP 200 — used by the
    file-API and PaperBench families (the regime `pbGet`/`pbPost` read).
- 062 MUST publish an **endpoint→envelope map** (derived from 060) so each handler's
  envelope is explicit and stable. Adding an endpoint means picking one of the two
  envelopes, never a third convention.
- Rationale: both envelopes are already on the wire and consumed by shipped
  components; unifying to a single envelope would be a breaking change. The policy
  freezes the split and forbids growth.

### 7.3 RULE-STATUS — explicit `(body, status)`, unchanged codes

- The service layer returns an explicit `(body, status)` pair (e.g. a small typed
  `Response(body, status=200)` object). The route layer passes `status` straight to
  `_json(body, status)`.
- The `r.pop("_status", 200)` idiom (`routes.py:1047-1057,1088-1089`) is retired
  **at the code level only**; every emitted HTTP status code stays byte-for-byte
  identical to today (065 asserts a representative set).
- `_json` itself (`routes.py:1190-1197`) is **KEEP** and unchanged, including
  `ensure_ascii=False` and the wildcard CORS header, so serialized bytes are stable.

### 7.4 RULE-FE-HOME — DTO home split; transport stays pure

- **Shared domain/state types** (`TreeNode`, `Checkpoint`, `Settings`, `AppState`,
  `CostSummary`, `WorkflowData`, `ReviewReport`, `CheckpointSummary`, …) — **KEEP**
  in `src/types/index.ts`.
- **Per-endpoint request/response DTOs** currently inlined in `services/api.ts`
  (~28 interfaces: `MemoryEntry`, `MemoryResponse`, `NodeReport`, `EARData`,
  `PublishSettings`, `PublishRecord`, `SubExperiment`, `ContainerImage`,
  `CheckpointFile`, `RubricSummary`, `FewshotListing`, …) — **ADAPT**: relocate to
  `src/types/` (a new `src/types/api.ts`, or per-domain files) in 063. After 063,
  `services/api.ts` imports its types and contains **no** `export interface`/`type`
  declarations — it is pure transport.
- Any DTO that duplicates a `types/index.ts` shape is **MERGE**d into the shared type
  rather than re-declared.

### 7.5 RULE-CLIENT — one typed transport contract

- 063 collapses the four transport helpers into **one** contract that normalizes
  **both** wire envelopes and the HTTP status into a single typed result. The target
  shape is a discriminated result, e.g.
  `type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string; status: number }`,
  produced by one transport function; PaperBench calls stop using a separate swallow
  path.
- The unification MUST preserve each call site's **observable** behavior: where a
  component previously read `{error}` without a `try/catch` (PaperBench), it now reads
  `result.ok === false` / `result.error`; where a component relied on a thrown error,
  the throwing wrapper is retained as a thin adapter over `ApiResult`. No wire shape
  changes.
- Rationale: removes Problem #2 (the two-regime hazard) as a *code* hazard while the
  wire — including HTTP-200-with-`{error}` for PaperBench — stays frozen.

### 7.6 RULE-SCHEMA — un-orphan the shipped JSON Schemas

- `ari-core/ari/schemas/node_report.schema.json` and `publish.schema.json` are
  **KEEP** and become the **authoritative shape** for their two endpoint families:
  - `/api/nodes/<rid>/<nid>/report` responses (backend `ear.py`; FE `NodeReport`,
    `api.ts:124-153`) MUST conform to `node_report.schema.json` (`schema_version`
    const 1; required `node_id,label,depth,status,files_changed,metrics,artifacts`).
  - `/api/publish/*` records (backend `api_publish.py`; FE publish DTOs) MUST conform
    to `publish.schema.json`, including its backend-name enum (`:51`).
- 062 SHOULD wire `ari.schemas.load("node_report")` / `load("publish")` into the
  producing path as a **validation-in-tests** binding (via 065), turning the orphaned
  schemas into an enforced contract. Whether runtime request-path validation is
  enabled is a 062 performance decision; the *test-time* binding is mandatory.
- The FE `NodeReport` / publish interfaces are pinned to these schemas: 065 asserts
  the TS interface and the JSON Schema agree on required keys and types. This makes
  the JSON Schema the one place a shape is defined, ending the three-copy drift
  (Problem #4).

### 7.7 RULE-TECH — Pydantic for input, typed objects for output

- **Request bodies** (untrusted POST JSON currently `json.loads`-ed inline) are
  validated with **Pydantic v2** models (already a dependency, `2.12.5`, precedent in
  `ari/config/__init__.py`). Invalid bodies produce the **error envelope**
  (RULE-ENV) at the endpoint's documented status code — never a stack trace to the
  browser.
- **Response objects** are typed constructs (dataclass or `TypedDict`) whose
  `dict()`/`asdict()` serialization through `_json` yields **byte-compatible** JSON
  with today's hand-built dicts (key set, key order, `null` handling, `ensure_ascii`).
  065 pins this for a representative endpoint set.
- Reuse over reinvention: where a request body overlaps `ARIConfig`/`LLMConfig`/…,
  the request model composes or references `ari.public.config_schema` rather than
  re-declaring fields.

### 7.8 RULE-PUB — DTO construction depends only on `ari.public.*`

- Service-layer DTO builders depend on the stable `ari.public.*` surface
  (`claim_gate, config_schema, container, cost_tracker, llm, paths, run_env,
  verified_context`). Direct imports of internal `ari.paths.PathManager`,
  `ari.checkpoint`, `ari.config.auto_config`, `ari.llm.client`, or
  `ari_skill_memory.backends` in a handler are **ADAPT** — moved behind an adapter in
  062. Where `ari.public.*` lacks a needed accessor, 062 raises it as a gap (do not
  widen the public surface silently in 061).

### 7.9 RULE-ALIAS — freeze the JS-compat aliases

- On `AppState`, the snake_case field is **canonical**: `is_running` (not `running`),
  `running_pid` (not `pid`), `llm_model_actual` (not `llm_model`). The aliases at
  `types/index.ts:118-120` are **REVIEW_REQUIRED / KEEP-as-frozen**: the backend
  emits both, shipped components read them, so they remain, but **no new alias may be
  added**, and new consumers MUST read the canonical field. The vestigial
  `CheckpointSummary.repro` alias (`:251`) is **DELETE_CANDIDATE** only once 065
  confirms no backend emits it and no component reads it — otherwise KEEP.

### 7.10 Per-artifact classification

| Artifact | Classification | Rule / note |
| --- | --- | --- |
| `_json` serializer (`routes.py:1190`) | **KEEP** | Bytes frozen (RULE-STATUS). |
| `{"ok"}` + `{"error"}` envelopes | **KEEP** (freeze both) | RULE-ENV. |
| `r.pop("_status", 200)` idiom | **ADAPT** | → explicit `(body, status)`; 062 (RULE-STATUS). |
| Inline handler `json.loads(body)` (POST) | **ADAPT** | → Pydantic request models; 062 (RULE-TECH). |
| ~28 inline DTO interfaces in `api.ts` | **ADAPT / MERGE** | → `src/types/`; 063 (RULE-FE-HOME). |
| Shared types in `types/index.ts` | **KEEP** | RULE-FE-HOME. |
| `get`/`post` vs `pbGet`/`pbPost` split | **ADAPT** | → one `ApiResult` transport; 063 (RULE-CLIENT). |
| `ari/schemas/node_report.schema.json`, `publish.schema.json` | **KEEP** (bind + enforce) | RULE-SCHEMA. |
| `ari.schemas.load()` (no importer today) | **ADAPT** | Wire into producing path/tests; 062/065. |
| Direct internal `ari.*` / `ari_skill_memory` imports in handlers | **ADAPT** | Behind `ari.public.*`; 062 (RULE-PUB). |
| `AppState` aliases `running`/`pid`/`llm_model` | **REVIEW_REQUIRED (frozen KEEP)** | RULE-ALIAS. |
| `CheckpointSummary.repro` alias (`:251`) | **DELETE_CANDIDATE** (conditional) | RULE-ALIAS. |
| `Pydantic v2` (`ari.public.config_schema`) | **KEEP** (reuse as DTO tech) | RULE-TECH. |

## 8. Concrete Work Items

This subtask's only deliverable is this policy document. The work items are:

1. **Write Sections 7.1–7.10** as the normative rulebook (done in this file);
   confirm each rule is stated as a decision, not an option, so 062/063/065 need no
   further design.
2. **Cross-link into the master index.** Note (for whoever maintains
   `docs/refactoring/007_subtask_index.md`) that 061 grounds 062/063/065 and pairs
   with the Phase-4 backend counterpart 022 and checker 030. Do **not** edit
   `007_subtask_index.md` in this subtask if it already carries the `:266` line;
   only flag if missing.
3. **Freeze the endpoint→envelope mapping obligation** onto 062 (RULE-ENV) and the
   DTO-relocation list onto 063 (RULE-FE-HOME), and the schema-binding assertions
   onto 065 (RULE-SCHEMA) — captured in Section 9's "governed files" table so each
   downstream subtask knows exactly which files it owns.
4. **State the reconciliation with 022/030** (Section 15) so the backend *shape*
   tests (022) and the *path* checker (030) are recognized as the enforcement arm of
   RULE-SSOT, avoiding duplicate or conflicting checks.
5. **Do not touch runtime code, `types/index.ts`, `services/api.ts`, or any
   schema/JSON/YAML.** They are read-only inputs here.

## 9. Files Expected to Change

**In this subtask (061):**

| Path | Change |
| --- | --- |
| `docs/refactoring/subtasks/061_define_dashboard_dto_and_schema_policy.md` | **Created** — this policy document (the only file written) |

No other file — no `.py`, `.ts`, `.json`, `.yaml`, workflow, or README — is created
or modified in subtask 061.

**Files the policy will GOVERN in downstream subtasks (informational; NOT changed
here):**

| Path | Governed by | Subtask that edits it |
| --- | --- | --- |
| `ari-core/ari/viz/routes.py` (`_status` at `:1047-1057,1088-1089`; dispatch) | RULE-STATUS, RULE-ENV, RULE-PUB | 062 |
| `ari-core/ari/viz/api_experiment.py`, `api_paperbench.py`, `file_api.py`, `api_settings.py`, `api_workflow.py`, `checkpoint_api.py`, `ear.py`, `api_publish.py` | RULE-ENV, RULE-STATUS, RULE-TECH, RULE-SCHEMA | 062 |
| `ari-core/ari/schemas/node_report.schema.json`, `publish.schema.json` + `__init__.py` | RULE-SCHEMA (wire into producing path/tests; schemas themselves unchanged) | 062 / 065 |
| `ari-core/ari/viz/frontend/src/services/api.ts` (extract ~28 inline DTOs; one transport) | RULE-FE-HOME, RULE-CLIENT | 063 |
| `ari-core/ari/viz/frontend/src/types/index.ts` (+ new `src/types/api.ts`) | RULE-FE-HOME, RULE-ALIAS, RULE-MERGE | 063 |
| `ari-core/ari/viz/frontend/src/types/README.md`, `src/services/README.md` | Keep accurate when 063 adds/moves files | 063 |
| Dashboard contract + schema tests (new, under `ari-core/tests/` and/or `frontend/**/__tests__/`) | RULE-SSOT, RULE-SCHEMA, RULE-STATUS, RULE-CLIENT (assert the contract) | 065 |

## 10. Files / APIs That Must Not Be Broken

- **Dashboard REST + WS contract** — every path/method/JSON-key/status-code/header
  consumed by `services/api.ts` (863) and the WS message
  `{"type":"update","data":<tree>,"timestamp":...}` on `ws://host:(port+1)/ws`.
  This policy preserves all of them; downstream 062/063 must keep them byte-identical
  (enforced by 030 + 065).
- **The two envelopes** `{"ok"}` and `{"error"}` and every emitted **status code** —
  frozen (RULE-ENV, RULE-STATUS).
- **`ari.public.*`** stable Python API (`claim_gate, config_schema, container,
  cost_tracker, llm, paths, run_env, verified_context`) — DTO builders depend on it;
  it is not widened by this policy.
- **`ari.schemas` loader + the two JSON Schemas** — `load()`/`schema_path()` and the
  file formats they describe (also referenced by `docs/reference/file_formats.md`);
  bound, not altered.
- **CLI `ari`** (`ari.cli:app`), **MCP tool contracts** of the 14 `ari-skill-*`
  servers, **checkpoint/config file formats** — untouched (this is a viz-only DTO
  concern).
- **Scripts called by `.github/workflows`** and the 5 existing workflows — unchanged;
  this policy adds no CI wiring.

## 11. Compatibility Constraints

- **Contract-preserving by construction.** Every rule changes internal representation
  behind an unchanged wire; nothing here (or in 062/063 under it) may alter a path,
  key, status, header, or the WS message. If a rule cannot be applied without a wire
  change, it is deferred and flagged, not forced.
- **Byte-stable serialization.** Response DTOs must serialize through the unchanged
  `_json` (`ensure_ascii=False`, wildcard CORS) to the same bytes; 065 pins a
  representative endpoint set. The `_status`→`(body, status)` change must not alter
  emitted codes.
- **Observable client behavior preserved.** RULE-CLIENT's unification must keep the
  PaperBench swallow-behavior observable outcome (HTTP 200 + `{error}` still surfaces
  as an error to the component), and keep the throw-based call sites working via a
  thin adapter.
- **Schema back-compat.** Binding to `node_report.schema.json` must respect
  `schema_version: const 1` and the existing `required` set; legacy runs that predate
  a field are handled by the schema's optionality, not by relaxing the schema.
- **No new public surface.** DTO builders may only consume existing `ari.public.*`
  exports; any missing accessor is a 062 gap to raise, not a silent widening in 061.
- **No "deprecated" for internal fields.** The `AppState` aliases and vestigial
  fields are preserved back-compat, classified REVIEW_REQUIRED/DELETE_CANDIDATE, not
  "deprecated" — that term is reserved for external contracts.
- **Determinism (P2) for the enforcement arm.** The 030/065 checks and tests that
  enforce this policy are stdlib/deterministic, no LLM, no network.

## 12. Tests to Run

Subtask 061 writes only a Markdown policy document and changes **no code**, so the
gates below must simply **stay green** (they are the same gates the downstream
implementers 062/063/065 will run). Run from repo root
`/home/t-kotama/workplace/ARI` (editable installs set up by `setup.sh`:
`ari-skill-memory` then `ari-core`):

```bash
python -m compileall .          # syntax gate — unchanged; must stay green
ruff check .                    # lint (ruff IS available; radon is NOT) — unchanged
pytest -q                       # full suite — unchanged; must stay green
```

Frontend gates (**not required for 061** — no `frontend/` code changes here; listed
because they are the gates 063/064 must pass under this policy):

```bash
cd ari-core/ari/viz/frontend
npm test                        # Vitest — the home 065 contract/schema tests will join
npm run build                   # tsc + vite build — must pass after 063's type moves
npm run typecheck               # tsc --noEmit — proves DTO relocations type-check
```

Doc-hygiene checks relevant to adding this file (should pass unchanged; `docs/
refactoring/` is **not** part of the VitePress site — `docs/.vitepress/config.ts:97`
`srcExclude` excludes `**/README.md`, and the `scripts/docs/` checkers do not scan
`docs/refactoring/`):

```bash
python scripts/readme_sync.py --check     # no new tracked directory added by 061
# .github/workflows/refactor-guards.yml must stay green (no ~/.ari references)
```

## 13. Acceptance Criteria

1. `docs/refactoring/subtasks/061_define_dashboard_dto_and_schema_policy.md` exists,
   uses the exact 17-section template, and is the **only** file created/modified.
2. `python -m compileall .`, `ruff check .`, and `pytest -q` remain green (this
   subtask changes no code); no frontend build is required.
3. The document states, as **decisions** (not options), all ten rules: RULE-SSOT,
   RULE-ENV, RULE-STATUS, RULE-FE-HOME, RULE-CLIENT, RULE-SCHEMA, RULE-TECH,
   RULE-PUB, RULE-ALIAS, and the per-artifact classification table.
4. Every rule is **contract-preserving**: no proposed change alters a dashboard path,
   JSON key, status code, header, or the WS message; where a change would, it is
   explicitly deferred.
5. Section 9 lists real repo paths and assigns each governed file to 062, 063, or
   065 consistently with `007_subtask_index.md:266` ("061 grounds 062/063/065").
6. The policy binds the orphaned `ari/schemas/node_report.schema.json` /
   `publish.schema.json` to the `/api/nodes/.../report` and `/api/publish/*` DTOs and
   names 065 as the enforcement point (RULE-SCHEMA).
7. The FE DTO-home decision is unambiguous (shared types in `src/types/`, no inline
   DTOs in `services/api.ts` after 063) and the ~28 inline interfaces are classified
   ADAPT/MERGE.
8. Dependencies (Section 15) match the DEPENDENCY GRAPH edge `059 -> 061` and
   recognize 060 as the consumed contract inventory, 062/063/065 as downstream,
   022/030 as the enforcement arm.
9. Section 16 declares Runtime = **No**, Risk = **LOW**, consistent with
   `007_subtask_index.md:108`.

## 14. Rollback Plan

- The subtask adds exactly one Markdown file and touches no runtime code, so rollback
  is a single `git rm docs/refactoring/subtasks/061_define_dashboard_dto_and_schema_
  policy.md` (or `git revert`). Nothing imports or executes it; no gate, workflow,
  build, data format, or migration is affected.
- Because 061 only *documents* decisions, reverting it cannot break the dashboard, CI,
  or any test. If a rule proves wrong during 062/063/065, amend this policy in place
  (a follow-up edit to the same file), do not fork the decision into the
  implementation subtasks.

## 15. Dependencies

Consistent with the provided DEPENDENCY GRAPH (edge `059 -> 061`) and
`docs/refactoring/007_subtask_index.md:106-113,255-273`.

- **Hard predecessor (inventory gate): 059** `inventory_dashboard_frontend_backend_
  structure`. The graph lists `059 -> 060, 061, 062, 063, 064, 065, 066`; 059 is the
  Phase-5 fan-out inventory (FE stack, structure) and is on the master list of
  inventory subtasks that MUST precede any runtime code change (**001, 002, 020, 036,
  045, 053, 059, 060, 067**). 061 changes no runtime code but is gated on 059's
  inventory being fixed.
- **Strongly consumed (sequence before 061 in practice): 060** `inventory_dashboard_
  api_contracts`. Per the graph, 060 also depends only on 059 (sibling of 061), but
  RULE-SSOT makes the 060 contract table the source of truth this policy binds to, so
  authoring 061 after 060 is landed is strongly recommended. (The hard graph edge
  remains `059 -> 061`.)
- **Downstream (this policy grounds them):** **062** `refactor_dashboard_backend_
  routes_to_services` (ADAPT; RULE-ENV/STATUS/TECH/PUB/SCHEMA), **063**
  `refactor_dashboard_frontend_api_client_and_types` (ADAPT; RULE-FE-HOME/CLIENT/
  ALIAS), **065** `add_dashboard_contract_and_schema_tests` (the enforcement of
  RULE-SSOT/SCHEMA/STATUS/CLIENT). `007_subtask_index.md:266`: "061 grounds
  062/063/065." (064 `refactor_dashboard_state_and_component_boundaries` and 066
  `add_dashboard_build_and_ci_plan` are siblings under 059 that this policy informs
  but does not gate.)
- **Enforcement arm (Phase-4 counterparts, coordinate — do not duplicate):** **022**
  `define_dashboard_dto_and_schema_tests` (backend *shape* tests) and **030**
  `add_viz_api_schema_checker_script` (`check_viz_api_schema.py`, *path-set*
  reconciliation). Both are gated by the Phase-4 viz inventory **020**; this policy
  treats them as the machine enforcement of RULE-SSOT so 065 does not re-implement
  their checks.
- **Upstream policy input:** `010_contract_preservation_policy.md` (dashboard API is a
  preserved contract), `008_viz_dashboard_refactoring_plan.md`,
  `014_dashboard_ux_refactoring_plan.md`.

## 16. Risk Level

- **Does this subtask change runtime code? NO.** It creates exactly one Markdown file
  (`docs/refactoring/subtasks/061_define_dashboard_dto_and_schema_policy.md`) and
  modifies **no** module under `ari-core/ari/`, no `frontend/` TypeScript, no schema/
  JSON/YAML, no import, no prompt, no workflow, and no directory name. This matches
  `007_subtask_index.md:108` (Runtime = No, Inventory = No).
- **Risk: LOW.** The only failure mode is a *policy* mistake — a rule that later
  proves impossible to implement contract-preservingly (e.g. a required schema
  binding that legacy `node_report.json` payloads violate). This is bounded because
  (a) the policy is validated by 065's tests before 062/063 land irreversible code,
  (b) every rule is explicitly contract-preserving with a "defer, don't force"
  escape, and (c) a wrong rule is fixed by editing this one document, never by
  breaking the wire. No runtime behavior, CI gate, or data format can regress from
  this subtask alone.

## 17. Notes for Implementer

- **This is a decision document, not code.** Do not touch `routes.py`, the `api_*.py`
  family, `services/api.ts`, `types/index.ts`, or `ari/schemas/*.json`. If you feel
  the urge to "just fix" the `_status` smuggling or the `pbGet`/`pbPost` split, stop —
  that is 062/063's job under this policy.
- **The wire is frozen; DTOs are internal.** Repeat this to yourself before every
  rule: paths, methods, JSON keys, status codes, headers, and the single WS
  `{"type":"update",...}` message do not change. 030's `check_viz_api_schema.py` and
  065's shape tests will catch any accidental drift.
- **Two envelopes, not one.** Do not "clean up" `{"ok"}` vs `{"error"}` into a single
  envelope — both are on the wire and consumed by shipped components (RULE-ENV). The
  win is *naming and freezing* them, not merging them.
- **Un-orphan the schemas, don't rewrite them.** `node_report.schema.json`
  (`schema_version` const 1) and `publish.schema.json` (backend-name enum at `:51`)
  already exist with a loader and no importer. The policy's value is binding the
  `/api/nodes/.../report` and `/api/publish/*` DTOs to them (RULE-SCHEMA); the schema
  files themselves are KEEP-unchanged.
- **Pydantic is already blessed.** `ari.public.config_schema` re-exports Pydantic v2
  models; reuse that stack for request-body validation (RULE-TECH) rather than
  introducing a second validation library. Response DTOs stay serialization-stable.
- **Aliases are frozen, not deprecated.** `AppState.running`/`pid`/`llm_model`
  (`types/index.ts:118-120`) stay; just declare the snake_case field canonical and
  forbid new aliases (RULE-ALIAS). Only `CheckpointSummary.repro` (`:251`) is a
  conditional DELETE_CANDIDATE, and only after 065 proves nothing emits/reads it.
- **`sonfigs/` does not exist.** Ignore it. Profile/rubric YAML the `/state` builder
  reads comes from top-level `ari-core/config/` (e.g. `routes.py:376,388,401,612`);
  it is not a DTO/schema concern here.
- **Coordinate, don't duplicate, with 022/030.** The backend shape tests (022) and
  the path checker (030) are the enforcement arm of RULE-SSOT; 065 should extend, not
  re-implement, them. Name them in the 062/065 hand-off so effort isn't duplicated.
- **`docs/refactoring/` is not the VitePress site.** Adding this file does not trip
  i18n/link/site checkers (`docs/.vitepress/config.ts:97` `srcExclude`; the
  `scripts/docs/` checkers do not scan this tree), and it needs no ja/zh mirror.

## 18. Retirement Condition

This subtask plan is a **temporary planning artifact**. It may be archived or
deleted (`git rm`) only after **all** of the following are verified against
primary sources (the repository state, the merged diff, and the index) — never
on assumption:

1. The **§13 Acceptance Criteria** of this document are met.
2. The implementing pull request is merged into `main`.
3. `docs/refactoring/007_subtask_index.md` marks subtask **061** as DONE.

Until every condition above is confirmed, this plan is **KEEP**. Before any
`git rm`, re-read this document's own conditions and check each one against the
current repository — see the canonical policy in
`docs/refactoring/007_subtask_index.md` ("Document Retirement Policy").
