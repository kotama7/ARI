# Tool Registry Requirements

## Runtime

- Python 3.13 or newer
- `mcp`, `pydantic`, `jsonschema`, and `pyyaml`
- an immutable reviewed `CATALOG.lock`; the committed default is empty
- an optional ARI checkpoint for artifacts and record/replay evidence

The component is default-off. Enabling it does not enable any leaf provider;
only sources present in the reviewed lock can execute.

## Required invariants

- The public MCP surface contains exactly `discover`, `describe`, `invoke`,
  `get_status`, and `get_result`.
- Runtime accepts only an exact opaque `tool_ref`; bare names never dispatch.
- Runtime does not import `sources.yaml`, sync providers, alter admission, or
  replace its active snapshot.
- Production configuration accepts generic direct `stdio-mcp` sources only.
  `StaticCatalogSource` and `StaticProviderAdapter` are injection seams for
  conformance tests, not selectable production kinds.
- Launchers execute no shell string and forward no undeclared parent
  environment or embedded credentials.
- Every leaf has a visible source-to-provider-to-tool origin chain. Cycles,
  excessive depth, missing leaf identity, source failure, and identity drift are
  quarantined or fail closed.
- Provider responses are normalized to `ari.result-envelope/v1`; large raw
  content becomes a content-addressed artifact.
- Record/replay cassettes contain no credential values and bind exact arguments,
  catalog, policy, selection evidence, raw response, and normalized result.
- Exact duplicate identities may collapse. Semantic near-matches remain
  distinct; scientific equivalence requires reviewed units, semantics, backend
  and data lineage, and method identity evidence.

## Source admission

A source owner must provide an immutable provider digest and value-free evidence.
`callable` requires protocol conformance, provider pinning, launcher verification,
and permitted capabilities. `reproducible` additionally requires dependency
pinning and a replay fixture digest. `scientifically_admitted` additionally
requires validation evidence, limitations, semantics, units, and method identity.

Source updates are operator-only. Unapproved changes produce pending lock/index
files and a review diff. Approval must be explicit and occurs outside an active
run.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_CHECKPOINT_DIR` | Writes lock, provenance, cassettes, and raw artifacts under `ear/catalog` |
| `ARI_TOOL_REGISTRY_LOCK` | Selects a reviewed lock at process startup |
| `ARI_TOOL_REGISTRY_INDEX` | Selects the derived index matching that lock |
| `ARI_TOOL_REGISTRY_CASSETTES` | Selects a credential-free replay store |

The manifest also permits only the fixed platform/TLS variables needed by the
isolated stdio process. Provider credentials are not supported by the generic
adapter until a value-free credential-scope bridge is admitted and tested.
