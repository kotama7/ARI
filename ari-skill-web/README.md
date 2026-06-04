# ari-skill-web

MCP skill for web search, URL fetching, and reference-graph traversal.

**P2 status:** the skill itself does not call an LLM, but the
underlying search APIs return time-varying results.  Pin retrieval
output into the checkpoint when reproducibility matters (P5).

## Tools

| Tool | Description |
|------|-------------|
| `web_search` | DuckDuckGo web search (no API key required) |
| `fetch_url` | Fetch a URL, extract readable text and title |
| `search_arxiv` | Direct arXiv search (faster than `survey`) |
| `search_semantic_scholar` | Semantic Scholar API search |
| `collect_references_iterative` | Walk the citation graph from a seed paper |

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `ARI_RETRIEVAL_BACKEND` | Default backend (`semantic_scholar` / `arxiv` / `alphaxiv`) | `semantic_scholar` |
| `ARI_ALPHAXIV_ENDPOINT` | Endpoint for the `alphaxiv` backend | (none) |
| `ARI_LLM_MODEL` | LLM for future re-ranking (currently unused) | (none) |
| `LLM_MODEL` | Cross-skill fallback | (none) |
| `ARI_LLM_API_BASE` | LiteLLM API base override | LiteLLM default |

## Backend switching

`web_search` always uses DuckDuckGo.  `search_arxiv` and
`search_semantic_scholar` hit their respective APIs directly.  When
`survey` from `ari-skill-idea` aggregates results, it picks the
backend declared in `ARI_RETRIEVAL_BACKEND`.

## Phase availability

This skill is gated to the `paper` and `reproduce` phases (see
`config/workflow.yaml`), so it is **not** exposed during BFTS node
exploration by default — that keeps the search trajectory reproducible
(P5), since live search results are time-varying. To opt in (e.g. to let
the experiment agent track the latest literature mid-search), set
`ARI_BFTS_ALLOW_WEB=1` (or `bfts.allow_web: true`). When enabled, ARI
records a non-reproducible-trajectory marker (`bfts_web_provenance.json`)
in the checkpoint. Note: `ari-skill-idea`'s `survey` already provides a
bounded prior-work lookup at idea time regardless of this flag.

## Determinism caveat

DuckDuckGo, arXiv, and Semantic Scholar all return time-varying
results (the index moves under your feet).  For reproducibility:

- Persist the call results into the checkpoint (the orchestrator
  does this automatically via the EAR pipeline).
- Re-runs that need byte-for-byte identical results should `ari
  clone` the previously published bundle rather than re-querying
  the live APIs.

This is the P5 (reproducibility) principle — see
`docs/concepts/PHILOSOPHY.md`.

## Tests

```bash
pytest tests/test_server.py -q              # per-backend tests
pytest tests/test_collect_references.py -q  # citation walk
```

## See also

- `docs/reference/skills.md#ari-skill-web` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
