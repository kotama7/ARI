# ari-skill-evaluator

MCP skill for experiment result evaluation and metric extraction.

**Role: data extractor, not a judge.**  Returns
`(metrics, has_real_data, extractor_code)` so the orchestrator can
score nodes — it does not produce a scalar score itself (P3 multi-
objective evaluation principle).

## Metric extraction flow

1. The agent calls `make_artifact_extractor(metric_spec)` with the
   experiment's expected metric keyword (e.g. `GFlops/s`).
2. The skill asks an LLM to write a small Python function that pulls
   that metric out of the node's stdout / log / CSV.
3. `evaluate(node_dir, expected_metrics)` runs the extractor against
   the artefacts and returns `metrics` plus `has_real_data` (true
   when the values look like real measurements rather than fabricated
   numbers).
4. The orchestrator combines this with rubric-driven dynamic axes to
   compute the BFTS composite score.

## Tools

| Tool | Description | LLM |
|---|---|:---:|
| `evaluate` | Score a node's artefacts against the metric spec | ✓ |
| `make_artifact_extractor` | Generate a Python extractor for a metric keyword | ✓ |

## Environment variables

| Variable | Purpose | Fallback order |
|---|---|---|
| `ARI_MODEL_EVAL` | Evaluator-specific LLM model | (none) |
| `ARI_MODEL` | ARI common model | used when `ARI_MODEL_EVAL` is unset |
| `ARI_LLM_MODEL` | Cross-skill fallback | used when both above are unset |

## P2 exception

This skill calls an LLM for both extractor synthesis and metric
parsing.  It is therefore **not** byte-deterministic; reruns may
produce slightly different extractor code.  See
`docs/PHILOSOPHY.md#p2-exceptions` for the project's stance on
allowed P2 deviations.

## Tests

```bash
pytest tests/ -q
```

## See also

- `docs/skills.md#ari-skill-evaluator` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
- `docs/reference/environment_variables.md` — env-var table.
