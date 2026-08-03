# ari-skill-web requirements

## Responsibility

The Skill owns retrieval, provider normalization, provenance, record/replay,
URL safety, and bounded citation traversal. Scientific source selection and
idea generation are separate responsibilities.

## Required behavior

1. Every canonical result uses `RetrievalRecordV1` and `SurveySnapshotV1`.
2. A call selects exactly one provider. Outage must be an explicit error; no
   provider fallback or partial composite success is permitted.
3. `record` requires a checkpoint and writes content-addressed raw and
   normalized artifacts. `replay` is offline and verifies snapshot, artifact,
   provider, query, operation, and parameter identity.
4. DOI, arXiv, and Semantic Scholar identities are aliases. Provider records
   remain distinct so merging does not erase lineage.
5. URL fetching must reject SSRF destinations and DNS rebinding, revalidate
   redirects, cap redirects/body size, allow only textual media, and label
   external text as untrusted.
6. Citation traversal must enforce depth, node, and request budgets, detect
   cycles, and return an explicit bounded partial result when a budget ends.
7. Deterministic retrieval must never call an LLM. The separate reranker must
   record model, API identity, prompt, input, and output digests.
8. Idea and paper consumers must accept verified snapshot references. A typed
   result without a recorded reference cannot downgrade to inline paper data.

## Dependencies

- `ari-core` — public research and workspace contracts
- `ddgs` — DuckDuckGo adapter
- `arxiv` — arXiv adapter
- `httpx` — AlphaXiv MCP transport
- `beautifulsoup4` — HTML-to-text extraction
- `litellm` — explicit stochastic compatibility/reranking tools only

## Gates

```bash
pytest -q ari-skill-web/tests
python scripts/check_skill_manifests.py
python scripts/snapshot_contracts.py --surface mcp --check
```
