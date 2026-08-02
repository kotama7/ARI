# ari-skill-web

Provider-neutral web and literature retrieval for ARI. The canonical tools emit
`RetrievalRecordV1` records inside a digest-bound `SurveySnapshotV1`; they do not
decide whether a source is scientifically relevant.

## Canonical tools

| Tool | Role |
|---|---|
| `search_papers` | Search one pinned Semantic Scholar, arXiv, or AlphaXiv provider |
| `web_search` | Search DuckDuckGo |
| `fetch_url` | Fetch untrusted text through the URL security policy |
| `walk_citations` | Traverse a bounded Semantic Scholar citation graph |
| `rerank_retrieval_records` | Explicit optional LLM reranker with model provenance |

`search_arxiv`, `search_semantic_scholar`, and `set_retrieval_backend` are
compatibility aliases retained until the P6 removal gate. New callers should
pass `provider` to `search_papers`. `collect_references_iterative` is a legacy
stochastic composition and is no longer used by the default paper pipeline.

## Live, record, and replay

- `live` calls one provider and returns a non-reproducible snapshot without
  writing artifacts.
- `record` requires `ARI_CHECKPOINT_DIR`. It writes a content-addressed raw
  cassette, optional raw body, and immutable normalized snapshot.
- `replay` requires the returned checkpoint-relative `snapshot_ref`, performs
  no network call, verifies every artifact digest and call parameter, and
  returns the exact recorded normalized records.

Provider failure is explicit. A call never changes from Semantic Scholar to
arXiv or accepts a partially successful composite provider behind the caller's
back.

## URL security

`fetch_url` accepts only HTTP(S) on ports 80/443. It rejects userinfo and every
DNS answer that is private, loopback, link-local, or otherwise non-global; pins
the validated IP for the socket; revalidates each redirect; rejects HTTPS
downgrades; and enforces redirect, byte, and content-type limits. Returned page
text is labelled as untrusted external data.

See [the retrieval contract](../docs/reference/retrieval_contract.md) for the
wire format, artifact layout, and consumer rules.

## Environment

| Variable | Purpose |
|---|---|
| `ARI_CHECKPOINT_DIR` | Required root for `record` and `replay` |
| `ARI_RETRIEVAL_BACKEND` | Legacy default pinned provider |
| `ARI_ALPHAXIV_ENDPOINT` | AlphaXiv MCP endpoint |
| `SEMANTIC_SCHOLAR_API_KEY` / `S2_API_KEY` | Optional Semantic Scholar credential |
| `ARI_LLM_MODEL`, `ARI_LLM_API_BASE` | Used only by explicit stochastic tools |

## Verification

```bash
pytest -q ari-skill-web/tests
ruff check ari-skill-web/src ari-skill-web/tests
python scripts/check_skill_manifests.py
```
