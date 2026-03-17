# ari-skill-web Requirements

## Overview

MCP skill server for web search and page fetching.

**Design Principle P2 compliant: No LLM calls. Fully deterministic.**

## Tools

### web_search(query, n=5)
- Provider: DuckDuckGo (via `ddgs` library)
- No API key required
- Returns: `results: list[{title, url, snippet}]`

### fetch_url(url, max_chars=8000)
- Fetches an HTTP(S) URL and extracts readable text
- Uses BeautifulSoup for HTML cleaning
- Returns: `{text, title, url}`

### search_arxiv(query, max_results=5)
- Direct arXiv search (faster than survey() in ari-skill-idea)
- Supports arXiv query syntax: `ti:`, `au:`, `abs:`
- Returns: `papers: list[{title, authors, abstract, url, published}]`

## Integration with Pipeline

The `search_related_work` pipeline stage calls `search_arxiv` directly.
The query is pre-built by `_extract_keywords_from_nodes()` in `pipeline.py`
(which reads `nodes_tree.json`). The web skill itself has no knowledge of BFTS
node structures — keyword extraction is the pipeline's responsibility.

## Dependencies

- `ddgs` — DuckDuckGo search (no API key)
- `httpx` — HTTP client
- `beautifulsoup4` — HTML text extraction
- `arxiv` — arXiv API client

## Tests

```bash
pytest tests/ -q  # 6 passed
```
