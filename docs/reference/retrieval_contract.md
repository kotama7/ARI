---
sources:
  - path: ari-core/ari/research_contract.py
    role: implementation
  - path: ari-skill-web/src/retrieval.py
    role: implementation
  - path: ari-skill-web/src/network_policy.py
    role: implementation
  - path: ari-skill-web/src/server.py
    role: implementation
  - path: ari-core/config/workflow.yaml
    role: config
last_verified: 2026-08-07
---

# Retrieval contract and network policy

ARI separates source acquisition from scientific adoption. `ari-skill-web`
retrieves and normalizes evidence; Idea, evaluator, and paper components decide
how that evidence may be used.

## Public records

Every canonical retrieval result has schema `ari.retrieval-result/v1` and
contains:

- `records`: provider-neutral `ari.retrieval-record/v1` values;
- `survey_snapshot`: the digest-bound `ari.survey-snapshot/v1` object;
- `survey_snapshot_digest` and an optional checkpoint-relative `snapshot_ref`;
- `alias_groups`, which link distinct provider records without collapsing their
  source lineage.

`RetrievalRecordV1` binds provider, provider record/version, query, retrieval
time, bibliographic fields, source URL, raw-payload digest, DOI/arXiv/S2 aliases,
license, and use restriction. The canonical ID is provider-scoped. For example,
an AlphaXiv record and an arXiv record remain distinct even when both carry the
same `arxiv:` alias.

## Execution modes

| Mode | Network | Artifact write | Meaning |
|---|---:|---:|---|
| `live` | yes | no | Current provider response; not replayable |
| `record` | yes | yes | One pinned provider plus immutable cassette/snapshot |
| `replay` | no | no | Verify and return the exact recorded normalized object |

`record` and `replay` require `ARI_CHECKPOINT_DIR`. A record writes:

```text
retrieval_cassettes/<raw-cassette-sha256>.json
retrieval_payloads/<raw-body-sha256>.bin       # when applicable
retrieval_snapshots/<snapshot-digest>.json
```

Replay verifies the snapshot's self-digest, content-addressed path, every
artifact SHA-256, provider, query, operation, parameters, normalized records,
citation edges, and warnings. The recorded snapshot object is returned without
changing its digest; `execution_mode: replay` describes the current operation.

A provider outage raises an explicit provider error. `record` never switches to
another provider, and the removed `both` mode cannot turn a partial provider
failure into an apparently complete result. To query multiple providers, issue
separate pinned calls and merge their records by aliases in a higher-level
broker while retaining all origins.

## URL fetch policy

`fetch_url`:

1. accepts only HTTP(S) and ports 80/443, without URL userinfo;
2. resolves the hostname once, rejects the request if any answer is non-global,
   and connects to the validated IP while preserving TLS SNI;
3. applies the same checks to every redirect and rejects HTTPS downgrade;
4. enforces redirect, declared/actual byte, and textual content-type limits;
5. stores the raw body in record mode and prefixes extracted text as untrusted
   external data.

This closes direct SSRF, mixed-answer DNS, validation/use rebinding, redirect,
and oversized-body paths. Source text is data, never a tool or system prompt.

## Citation traversal and ranking

`walk_citations` has independent depth, node, and provider-request budgets plus
cycle detection. Exhaustion returns `partial: true`, a reason, retained records,
and only edges whose endpoints are retained.

`search_papers`, `web_search`, `fetch_url`, and `walk_citations` never call an
LLM. `rerank_retrieval_records` is a separate stochastic tool and records model,
API-base identity, temperature, prompt digest, input digest, and raw-output
digest. Multi-query collection is composed explicitly above this boundary.

## Consumer rule

Idea generation accepts `survey_snapshot_ref`; paper generation resolves the
`snapshot_ref` in a recorded retrieval result. Both use the common verified
snapshot loader. A typed retrieval result without a recorded reference cannot
silently downgrade to caller-supplied inline papers. Public retrieval writers
emit only canonical `records`.

See also [Research contracts](research_contracts.md) and
[Execution contract](execution_contract.md).
