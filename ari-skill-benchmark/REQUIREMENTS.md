# ari-skill-benchmark Requirements (v0.2)

## Overview

MCP server for deterministic experiment summaries, statistical inference, and
provenance-aware run comparison. Figure rendering belongs exclusively to
`ari-skill-plot`.

## MCP Tools

### analyze_results(request: AnalysisRequestV1) -> AnalysisResultV1
Analyzes unit-bearing inline samples or digest-bound CSV / JSON / npy sources.
Missing-value policy, confidence level, pre-registration digest, and artifact
target are explicit.

### statistical_test(request: StatisticalTestRequestV1) -> AnalysisResultV1
Runs paired/unpaired parametric or rank tests. Returns sample counts, effect
size, confidence interval, assumptions, p-value, and corrected p-value.

### compare_runs(request: RunComparisonRequestV1) -> AnalysisResultV1
Ranks scalar runs while retaining environment compatibility, shared-substrate
caveats, replicate identity, and provenance differences.

## Design

- All tools are deterministic and make no LLM calls.
- Public requests and results use `ari.public.analysis` v1 contracts.
- Source files are closed-workspace paths bound to expected SHA-256 digests.
- JSON and CSV artifacts are content addressed by the resolved input digest.
- `plot` and the matplotlib/pandas dependencies were removed in v0.2.
