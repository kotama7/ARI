# ari-skill-paper-re Requirements

## Overview

MCP Server that parses papers (LaTeX / plain text), extracts numeric claims,
and quantitatively evaluates reproducibility by comparing with experimental results.

Design Principle P2 compliant: **No LLM calls. Fully deterministic.**

## Tech Stack

- Python 3.11+
- FastMCP
- regex (numeric claim extraction patterns)

## Tool Specifications

### extract_claims(paper_text: str, max_claims: int = 50) -> dict
Extracts numeric claims using regex patterns common in academic papers.
Returns a list of `{value, unit, context}` dicts.

### compare_with_results(claims: list, actual_metrics: dict, tolerance_pct: float = 10.0) -> dict
Compares extracted claims against measured metrics within a tolerance window.

### reproducibility_report(paper_text: str, actual_metrics: dict, paper_title: str = "", tolerance_pct: float = 10.0) -> dict
Generates a complete reproducibility report with verdict (REPRODUCED / PARTIAL / NOT_REPRODUCED).
