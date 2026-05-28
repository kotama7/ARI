# ari-skill-web/src

MCP server package for the web skill — web search, URL fetching, and
citation-graph traversal (P2: no LLM, but search APIs are time-varying). No
`__init__.py`; `server.py` is the entry point.

## Contents

- `README.md` — this file.
- `server.py` — the only module; exposes `web_search`, `fetch_url`, `search_arxiv`, `search_semantic_scholar`, `collect_references_iterative`.

## See also

- The skill root `README.md` and the `server.py` module docstring for the tools & outward interface.
