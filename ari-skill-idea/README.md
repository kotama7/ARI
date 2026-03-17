# ari-skill-idea

MCP skill for literature survey and idea generation.

**Design Principle P2: Survey is deterministic (arXiv + Semantic Scholar API only).**  
`generate_ideas` uses an LLM (pre-BFTS phase only — not inside the search loop).

## Tools

| Tool | Description | LLM |
|---|---|---|
| `survey` | Survey prior work (arXiv + Semantic Scholar) | None |
| `make_metric_spec` | Generate MetricSpec from experiment file | None |
| `generate_ideas` | Generate research ideas (pre-BFTS) | Yes |

## Tests

```bash
pytest tests/ -q
# 9 passed
```
