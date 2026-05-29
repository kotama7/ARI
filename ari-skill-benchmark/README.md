# ari-skill-benchmark

Statistical analysis, visualisation, and hypothesis testing as MCP
tools.  Fully deterministic (P2-safe): every tool reads numeric
inputs and returns numeric outputs without invoking an LLM.

## MCP tools

| Tool | Purpose | LLM |
|---|---|:---:|
| `analyze_results` | Compute summary statistics (mean / std / quantiles, ...) from a result file (CSV / JSON / npy) | ✗ |
| `plot` | Render a matplotlib figure from a fixed schema | ✗ |
| `statistical_test` | Hypothesis test (`t_test`, `mann_whitney_u`, `paired_t_test`, ...) | ✗ |

### `analyze_results`

| Field | Meaning |
|---|---|
| `result_path` | Path to the input file (CSV / JSON / npy) |
| `metrics` (optional) | Subset of metric names; defaults to every column |

Returns `{"<metric>": {"mean": ..., "std": ..., "min": ..., "max": ..., "p25": ..., "p50": ..., "p75": ...}}`.

### `plot`

| Field | Meaning |
|---|---|
| `data_path` | Input file |
| `figure_spec` | Dict with keys `kind` (`line` / `bar` / `scatter` / `hist`), `x`, `y`, `groupby`, `title`, ... |
| `output_path` | PNG / PDF target |

Returns `{"figure_path": "...", "size_bytes": ...}`.

### `statistical_test`

| Field | Meaning |
|---|---|
| `test` | `t_test` / `mann_whitney_u` / `paired_t_test` / ... |
| `sample_a`, `sample_b` | Numeric arrays |
| `alpha` (optional) | Significance level (default 0.05) |

Returns `{"statistic": ..., "p_value": ..., "significant": bool}`.

## Determinism

All three tools are byte-deterministic for given inputs.  No LLM
calls; all randomness is seeded at the matplotlib level (figures use
the `Agg` backend with no GUI dependency).

## Environment variables

None.  The skill reads only its tool arguments.

## Dependencies

- `numpy >= 1.26`
- `scipy >= 1.11`
- `matplotlib >= 3.8`
- `pandas >= 2.0`
- `mcp >= 1.0`

## Example

```json
{
  "tool": "analyze_results",
  "args": {
    "result_path": "results.json",
    "metrics": ["GFlops/s"]
  }
}
```

## Development

```bash
pytest tests/ -q
```

## Compatibility

P2 (determinism) compliant: same inputs, same outputs.

## See also

- `docs/reference/skills.md` — high-level summary in the master skill index.
- `docs/reference/mcp_tools.md` — argument signatures.
