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

This allows future ToolUniverse-like collections, OpenROAD flows, quantum
simulators, or other MCP bundles to coexist without embedding package-specific
routing logic in the agent. A direct stdio MCP source needs no custom leaf code.
A non-stdio collection needs one `CatalogSource` plus one `ProviderAdapter`, with
contract, supply-chain, record/replay, and scientific conformance fixtures.

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
python scripts/sync_contracts.py           # CI drift check
pytest -q
```

Never add a hand-written production record per leaf, expose leaf schemas directly
as LLM tools, refresh the catalog during a run, dispatch a bare name, return raw
provider-shaped results, or register static fixtures in production. Those paths
are excluded by the contract and regression suite.
