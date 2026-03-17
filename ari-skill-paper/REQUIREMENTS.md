# ari-skill-paper Requirements

## Overview

MCP Server for LaTeX paper writing assistance.
Manages academic templates, section generation, and format review.

## Design

- Called only in the post-BFTS pipeline (not inside the BFTS search loop)
- `generate_section` searches `nodes_tree.json` for relevant evidence (keyword-based)
- Default venue: arXiv (no page limit). Conference venues enforce their constraints.
- `<think>` tags from LLM output are stripped automatically.

## Tech Stack

- Python 3.11+
- FastMCP
- litellm (LLM calls for generation and review)

## Tool Specifications

### generate_section(section: str, goal: str, artifacts: str, venue: str = "arxiv", nodes_json_path: str = "") -> dict
Generates a LaTeX section. Enriches context with up to 8 matching nodes from the tree.

### review_section(section_tex: str, venue: str = "arxiv") -> dict
Reviews the generated section for clarity, correctness, and venue compliance.
