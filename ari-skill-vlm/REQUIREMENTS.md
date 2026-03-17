# ari-skill-vlm Requirements

## Overview

MCP Server for reviewing figures and tables using a Vision Language Model (VLM).
Automatically evaluates figure quality in academic papers.

## MCP Tools

### review_figure(image_path: str, context: str = "") -> dict
Reviews a figure using VLM. Returns quality assessment and suggestions.

### review_table(table_tex: str, context: str = "") -> dict
Reviews a LaTeX table for clarity and correctness.

## Design

- Uses qwen2.5vl or equivalent VLM via Ollama
- Called in post-BFTS pipeline only
