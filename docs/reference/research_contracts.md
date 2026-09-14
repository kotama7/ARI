---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-idea/src/contracts.py
    role: implementation
  - path: ari-skill-evaluator/src/server.py
    role: implementation
last_verified: 2026-08-16
---

# Research contracts

ARI freezes the scientific decision between literature retrieval and experiment
execution as three immutable records:

1. `SurveySnapshotV1` records the pinned provider, query, retrieval time,
   normalized records, citation edges, artifacts, and whether the original live
   operation is byte-reproducible.
2. `IdeaSetV1` records the model, prompt-template digests, sampling settings,
   seed, adapter/vendor revision, exact source snapshot, admitted candidates,
   and deterministic rejection reasons.
3. `ResearchContractV1` is minted from one admitted candidate. It freezes the
   hypothesis, falsification conditions, metric name, unit, direction,
   comparison scope, required evidence, citations, limitations, and source
   digests.

Each record contains a SHA-256 digest over its canonical JSON payload (excluding
the digest field itself). Parsing verifies that digest. The evaluator consumes
`ResearchContractV1` verbatim and writes the same `research_contract_digest` to
`metric_contract.json`; it does not ask an LLM to rename the metric or evidence.

`survey(mode="record")` never changes providers after an outage.
`survey(mode="replay")` reads only the requested checkpoint artifact, performs no
network call, and rejects a missing, malformed, or digest-mismatched snapshot.
Live/record snapshots are marked `byte_reproducible: false`, while the recorded
snapshot artifact can subsequently be replayed exactly.

The top-level flat `ideas`, `primary_metric`, and related fields are legacy
checkpoint projections. New consumers must use the typed records. A document
declaring `typed_schema_version: ari.research-contract/v1` but lacking an admitted
contract fails closed and cannot downgrade to legacy prose inference.

JSON Schemas are shipped under `ari-core/ari/schemas/`. The stable Skill API is
`ari.public.research_contract`.

Provider cassette layout, verified snapshot references, URL policy, and
multi-provider alias semantics are specified in the
[retrieval contract](retrieval_contract.md).
