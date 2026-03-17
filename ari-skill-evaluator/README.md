# ari-skill-evaluator

MCP skill for experiment result evaluation and metric extraction.

**Role: Data extractor, not a judge.**  
Does not produce a scalar score (P3 multi-objective evaluation principle).

## Tools

| Tool | Description |
|---|---|
| `evaluate` | Extract metrics from artifact text; return has_real_data + metrics dict |
| `make_artifact_extractor` | Return Python extractor code for a given metric keyword |

## Tests

```bash
pytest tests/ -q
# 6 passed
```
