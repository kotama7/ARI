---
sources:
  - path: ari-skill-tool-registry/src/models.py
    role: implementation
  - path: ari-skill-tool-registry/src/providers.py
    role: implementation
  - path: ari-skill-tool-registry/src/sources.py
    role: implementation
  - path: ari-skill-tool-registry/src/admission.py
    role: implementation
  - path: ari-skill-tool-registry/src/catalog.py
    role: implementation
  - path: ari-skill-tool-registry/src/broker.py
    role: implementation
  - path: ari-skill-tool-registry/src/storage.py
    role: implementation
  - path: ari-skill-tool-registry/src/tooluniverse_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/providers/tooluniverse-support-v1.json
    role: config
  - path: ari-skill-tool-registry/src/openroad_adapter.py
    role: implementation
  - path: ari-skill-tool-registry/providers/openroad-support-v1.json
    role: config
last_verified: 2026-08-02
---

# Federated Scientific Tool Registry

`ari-skill-tool-registry` imports large MCP collections behind five stable
operations: `discover`, `describe`, `invoke`, `get_status`, and `get_result`.
It is default-off. The model never receives every leaf schema, and adding a
collection does not require editing one file per leaf.

## Boundary and lifecycle

```text
few reviewed sources.yaml records
  -> isolated provider discovery
  -> canonical descriptors and visible origin chains
  -> graph, supply-chain, conformance, and scientific admission
  -> reviewed CATALOG.lock + derived catalog.index.json
  -> immutable five-operation runtime broker
```

`sources.yaml` is operator input and is not read by runtime. A changed sync emits
pending artifacts and a review diff. Only explicit `--approve` replaces the
active lock, and an already-running broker never observes that replacement.

Each `tool_ref` is an opaque digest of execution-relevant identity: provider and
adapter versions/digests, provider leaf name, schema, explicit defaults,
permissions and effects, determinism, semantic execution metadata, method
identity, and async lifecycle. Policy and source aliases are deliberately
excluded, so policy reassessment cannot masquerade as implementation drift.

## Progressive disclosure

`discover` returns bounded summaries and at most 25 results per page. `describe`
returns at most 4,000 characters per page and binds its cursor to the catalog,
tool, and section. `invoke` accepts only a full `tool_ref` from the active lock;
an unqualified name, stale identity, invalid arguments, or insufficient admission
fails closed. Provider-specific output is normalized to
`ari.result-envelope/v1`.

## Admission levels

| Level | Required evidence |
|---|---|
| `discovered` | Candidate and transparent leaf origin are known |
| `callable` | MCP conformance, immutable provider pin, verified launcher, allowed permissions |
| `reproducible` | Callable plus pinned dependencies and offline replay fixture |
| `scientifically_admitted` | Reproducible plus validation, limitations, semantics, units, and method identity |

Discovery is not authority. The registry reports evidence and policy decisions;
it does not declare an upstream collection scientifically correct.

## Multiple collections and conflicts

Collections compose through the same canonical descriptor and adapter boundary.
Execution-identical aliases collapse while retaining every source/origin chain.
Tools with a similar capability remain distinct by default. The catalog records
whether overlap is an exact duplicate, the same backend, a semantic near-match,
or an independent method. Diverse discovery can prefer different independence
groups, but results are not averaged automatically and disagreement is preserved.

This allows ToolUniverse, future collection packages, OpenROAD flows, quantum
simulators, or other MCP bundles to coexist without embedding package-specific
routing logic in the agent. A direct stdio MCP source needs no custom leaf code.
A non-stdio collection needs one `CatalogSource` plus one `ProviderAdapter`, with
contract, supply-chain, record/replay, and scientific conformance fixtures.

## ToolUniverse v1.3.1 adapter

ToolUniverse is integrated as one compact collection, not thousands of public
MCP tools. The registry itself does not import ToolUniverse. The isolated
provider process exposes ToolUniverse's compact discovery/info/execute surface;
operator sync expands selected leaves into canonical descriptors, and runtime
dispatch maps an exact locked leaf back through `execute_tool`.

The reviewed support record binds the upstream repository commit/tag, PyPI
wheel and sdist, Apache-2.0 license file, upstream dependency lock, compact tool
contract, and a canonical digest of all 3,542 non-cache files in the installed
package. Both sync and runtime verify that complete tree and the exact
shell-free `tooluniverse.smcp_server:run_stdio_server` callable. Version ranges,
dynamic installation, an altered package tree, and a different entry point fail
closed.

Tool selection uses declarative category/type profiles rather than per-leaf
wrappers. An ARI-side category filter is applied even when ToolUniverse's CLI
loads a broader background set, and runtime additionally permits only leaf names
in the active `CATALOG.lock`. Dynamic MCP loaders, agentic/composition/code
execution, credential-requiring leaves, ambiguous/unreviewed profiles, and
invalid schemas are quarantined. ToolUniverse v1.3.1's known property-level
`required: true` dialect is deterministically converted to the standard parent
`required` array and recorded in provenance; other invalid schema forms are not
repaired.

Argument validation always uses the locked canonical schema. Unknown fields,
wrong JSON types, and missing required fields fail in record mode; upstream
coercion is disabled, and explicit `null` is rejected because v1.3.1 silently
removes it. ToolUniverse result caching, persistence, update checks, hooks, and
search are disabled. Every result records collection/wheel/provider/leaf-spec
identity and `upstream_cache: disabled`; ARI cassette/EAR is the only replay
authority. Collection trust is capped below leaf replay or scientific
validation, so importing ToolUniverse never scientifically admits its leaves.

Bulk updates always produce a pending catalog diff. Changes to input schema,
output schema, or defaults are grouped by stable provider/leaf identity and
cannot be approved with ordinary `--approve`; they also require the explicit
`--approve-schema-changes` flag. This keeps running experiments on their old
lock and makes large collection upgrades reviewable.

## OpenROAD profile adapter

OpenROAD-MCP is integrated through the same source/descriptor/broker contracts,
but its upstream interactive tools are never canonical leaves. A reviewed
experiment profile is the leaf. Its execution identity includes a fixed command
sequence, exact input workspace, OpenROAD/ORFS commits and executable/image
digests, PDK and standard-cell library identity/license scope, architecture,
threads, seed, declared outputs, and metric contracts.

Only `request_id` crosses the invocation boundary. The adapter rejects arbitrary
Tcl/shell, caller paths, cwd and environment; its flat brace-list grammar cannot
perform Tcl substitution. Inputs are re-digested after copying to an isolated
run workspace. Output discovery is declaration-based: filesystem scanning is
used only to reject undeclared or symlinked files. Metrics carry a numeric value,
unit, corner, mode, stage, source-report digest, and JSON pointer. Exact golden
and replay fixture files are validated before a source is admitted.

The upstream process remains connected for the whole interactive session. A
sentinel command queued after each fixed flow command prevents the upstream
short output-lull heuristic from being treated as completion. All terminal paths
terminate the session; interruption cannot resume an ephemeral local MCP session
and therefore fails closed. Each run has a deterministic idempotent handle and a
fresh workspace, while parallel profiles may use independent sessions.

Completed outputs and success/failure/cancel transcripts are stored
content-addressably. Provider-returned artifact references are an internal
adapter protocol: the broker removes the reserved field and independently checks
safe digest-prefixed names, symlink absence, size, and SHA-256 before adding them
to `ResultEnvelopeV1`. Record/replay keeps those references without contacting
the provider. Profiles sharing the same design inputs and PDK/library use one
independence group, so version disagreement is not counted as independent
scientific evidence.

## Record, replay, and EAR

Record mode stores exact normalized arguments, catalog and policy digests,
selection reason, rejected alternatives, raw response digest or artifact, and
the normalized result. Replay uses the same cassette key and matching catalog
without starting a provider. `{checkpoint}/ear/catalog/` contains `CATALOG.lock`,
value-free provenance, cassettes, and content-addressed raw artifacts; the
default EAR curator includes this directory.

## Operator procedure

```bash
cd ari-skill-tool-registry
python src/sync_catalog.py                 # create or write pending review
python src/sync_catalog.py --approve       # only after reviewing the diff
python src/sync_catalog.py --approve --approve-schema-changes  # schema review
python scripts/verify_tooluniverse.py --help
python scripts/verify_openroad.py --help
python scripts/sync_contracts.py           # CI drift check
pytest -q
```

Never add a hand-written production record per leaf, expose leaf schemas directly
as LLM tools, refresh the catalog during a run, dispatch a bare name, return raw
provider-shaped results, or register static fixtures in production. Those paths
are excluded by the contract and regression suite.
