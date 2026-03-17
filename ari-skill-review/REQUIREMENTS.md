# ari-skill-review Requirements

## Overview

MCP Server for review comment analysis and rebuttal generation.

## MCP Tools

### parse_review(review_text: str) -> dict
Parses review comments into structured form (concerns, questions, suggestions).

### generate_rebuttal(review_text: str, paper_text: str) -> dict
Generates a point-by-point rebuttal to review comments using LLM.

### check_rebuttal(rebuttal_text: str, review_text: str) -> dict
Checks the completeness and appropriateness of a rebuttal.

## Design

- `parse_review` is deterministic (regex + rule-based)
- `generate_rebuttal` and `check_rebuttal` use LLM (post-BFTS only)
