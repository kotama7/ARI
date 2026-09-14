# ari-skill-benchmark

Deterministic scientific summaries, statistical inference, and run comparison.
The server makes no LLM calls and delegates every figure to
`ari-skill-plot:render_figure`.

## MCP tools

| Tool | Contract | Purpose |
|---|---|---|
| `analyze_results` | `AnalysisRequestV1` | Unit-bearing summary statistics and mean confidence intervals |
| `statistical_test` | `StatisticalTestRequestV1` | Paired/unpaired tests, effect sizes, confidence intervals, assumptions, and corrected p-values |
| `compare_runs` | `RunComparisonRequestV1` | Rankings plus environment, replicate, and provenance differences |

All tools return `AnalysisResultV1`. Public models are available from
`ari.public.analysis`, with generated JSON Schemas under
`ari-core/ari/schemas/`.

## Inputs and provenance

Samples can be inline observations or a typed `csv`, `json`, or `npy` source.
A file source must name a closed `WorkspaceRefV1`, a safe relative path, an
expected SHA-256 digest, a numeric value column when needed, and optional
replicate/pair/backend/environment identity columns. NumPy object arrays and
pickle loading are prohibited.

Every metric has an explicit unit. Empty samples, all-missing samples, unit
mismatches, and paired-length mismatches fail. Missing and non-finite values are
either rejected or dropped according to `missing_policy`; dropping is reported
in the result.

`AnalysisResultV1` records the resolved input digest, Python/NumPy/SciPy
versions, counts, effect size, confidence interval, assumption diagnostics, and
the pre-registration `analysis_plan_digest` when supplied. Multiple comparisons
must select Bonferroni, Holm, or Benjamini-Hochberg correction.

## Artifacts

An optional `artifact_target` writes deterministic `result.json` and
`table.csv` files through a closed workspace. The paths are keyed by the
resolved input digest and returned with byte digests and media types.

## Example

```json
{
  "tool": "statistical_test",
  "args": {
    "request": {
      "schema_version": "ari.statistical-test-request/v1",
      "comparisons": [{
        "comparison_id": "candidate-vs-baseline",
        "group_a": {
          "metric_id": "latency",
          "unit": "ms",
          "observations": [{"value": 8.1}, {"value": 8.4}, {"value": 8.2}]
        },
        "group_b": {
          "metric_id": "latency",
          "unit": "ms",
          "observations": [{"value": 10.1}, {"value": 9.8}, {"value": 10.0}]
        },
        "test_family": "welch_t"
      }]
    }
  }
}
```

## Development

```bash
PYTHONPATH=../ari-core pytest tests -q
```

See [the analysis contract](../docs/reference/analysis_contract.md) for the
normative statistical and migration rules.
