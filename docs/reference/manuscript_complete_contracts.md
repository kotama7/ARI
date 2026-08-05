# Manuscript Complete V1 contracts

All normative documents reject unknown fields, use safe checkpoint-relative
paths, canonical JSON SHA-256 identities, and validate their advertised digest
on read. Generated JSON Schemas live in `ari-core/ari/schemas/` and are checked
with:

```bash
PYTHONPATH=ari-core python scripts/sync_manuscript_schemas.py --check
```

| Document | Schema version | Permanent role |
|---|---|---|
| requirement profile | `ari.manuscript-requirement-profile/v1` | requirements, applicability and severity |
| exploration snapshot | `ari.manuscript-exploration-snapshot/v1` | complete node/artifact inventory and scientific winner |
| omission manifest | `ari.manuscript-omission-manifest/v1` | conservation of included plus omitted inventory |
| context | `ari.manuscript-context/v1` | deterministic requirement-oriented projection |
| readiness | `ari.manuscript-readiness/v1` | per-requirement status and authoring/publication verdicts |
| section brief bundle | `ari.manuscript-section-brief-bundle/v1` | bounded, lane-aware writer input with no silent required omission |
| authoring binding | `ari.manuscript-authoring-binding/v1` | exact profile/context/readiness/brief and target build |
| segment record | `ari.manuscript-segment-record/v1` | resumable workflow input/output transaction |
| repair request/plan | `ari.research-repair-request/v1`, `ari.research-repair-plan/v1` | fixed action, authority and cumulative budget |
| publication decision | `ari.manuscript-publication-decision/v1` | six independent gate verdicts bound to one build |
| publication lock | `ari.manuscript-publication-lock/v1` | final fresh decision/build/PDF interlock |
| transition | `ari.manuscript-transition/v1` | append-only state hash chain |

## Digest lineage

The normative chain is:

```text
profile + source files/nodes
  → snapshot
  → context + omission manifest
  → readiness
  → section briefs
  → authoring binding
  → PaperBuildV1
  → PublicationDecisionV1
  → PublicationLockV1
```

Changing any parent invalidates downstream reuse. The finalizer re-hashes the
snapshot sources, every nested `PaperArtifactV1`, all five manuscript inputs,
the reproduction result, and the final PDF before a lock is written.

## Status semantics

Requirement status is exactly `satisfied`, `not_applicable`, `unavailable`, or
`missing`. `unavailable` is evidence about resolver availability, not success.
Authoring is blocked by authoring-critical `missing|unavailable`; publication
is blocked by every unresolved publication-critical requirement.

The top-level publication decision is publishable only if the applicable
`manuscript_readiness`, `claim_evidence`, `assurance`, `build_compile`,
`reproduction`, and `freshness` sub-verdicts do not fail. The model validator
recomputes this logical AND.

## PaperBuild relationship

The legacy `PaperBuildV1` remains the paper build contract. Under enforce, its
input artifact set additionally contains `manuscript-profile`,
`manuscript-context`, `manuscript-readiness`, `section-briefs`, and
`manuscript-authoring-binding`. `PaperBuildV1.status=finalized` alone does not
mean Manuscript Complete publication is permitted; `PublicationLockV1` is the
final interlock.

Stable read types and fixed compiler helpers are exported from
`ari.public.manuscript`; mutable coordinator internals are not public API.
