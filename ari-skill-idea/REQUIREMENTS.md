# ari-skill-idea Requirements

## Overview

MCP Server for research idea generation, literature survey, and gap analysis.

## Design

- `survey` and `make_metric_spec` are fully deterministic (no LLM)
- `generate_ideas` uses LLM only in pre-BFTS phase (outside the search loop)
- Survey uses TF-IDF-style keyword scoring over arXiv + Semantic Scholar results

## MCP Tools

### survey(query: str, max_results: int = 10) -> dict
Surveys related prior work. Returns titles, abstracts, and relevance scores.

### make_metric_spec(experiment_file: str) -> dict
Parses experiment Markdown to extract metric_keyword, scoring_guide,
and min_expected_metric. Returns a MetricSpec dict.

### generate_ideas(goal: str, survey_results: list, n_ideas: int = 3) -> dict
Generates research hypotheses using LLM. Called once before BFTS starts.
