# ari-skill-web/src

- `server.py` exposes the MCP tools and provider adapters.
- `retrieval.py` normalizes `RetrievalRecordV1` values and implements
  content-addressed record/replay.
- `network_policy.py` implements pinned-address HTTP fetching, redirect
  revalidation, and response limits.

Deterministic retrieval paths do not call a model. The explicit reranker and
legacy iterative collector are declared stochastic in `skill.yaml`.
