# ari-skill-web

MCP skill for web search and page fetching.

**Design Principle P2 compliant: No LLM calls. Fully deterministic.**

## Tools

| Tool | Description |
|------|-------------|
|  | DuckDuckGo web search. No API key needed. |
|  | Fetch a web page and extract readable text. |
|  | Direct arXiv search (faster than survey()). |

## Tests

```bash
pytest tests/ -q  # 6 passed
```
