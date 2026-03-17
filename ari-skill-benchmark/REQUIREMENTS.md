# ari-skill-benchmark Requirements

## Overview

MCP Server for experiment result analysis, visualization, and statistical testing.

## MCP Tools

### analyze_results(file_path: str, format: str = "json") -> dict
Analyzes result files (CSV / JSON / npy) and returns a summary with statistics.

### compare_runs(run_ids: list, metric: str) -> dict
Compares multiple runs on a specified metric. Returns rankings and deltas.

### statistical_test(group_a: list, group_b: list, test: str = "ttest") -> dict
Runs a statistical significance test between two result groups.

## Design

- All tools are deterministic (no LLM)
- Supports CSV, JSON, NumPy array inputs
