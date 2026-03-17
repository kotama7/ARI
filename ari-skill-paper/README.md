# ari-skill-paper

MCP skill for **AI Scientist v2-style iterative paper generation**.

## Design

Implements `write_paper_iterative`: a loop that generates → reviews → revises each section.  
Accepts figures from `generate_figures` stage and embeds them with `\includegraphics`.

## LLM Exception

This skill calls an LLM (P2 exception). Requires Ollama running on the same node.

## Tool

### `write_paper_iterative`

Writes a full LaTeX paper from experiment results.

**Key inputs:**
- `experiment_summary` — BFTS experiment context (must contain `<!-- metric_keyword: X -->` comment)
- `refs_json` — JSON string from `related_refs.json`
- `figures_manifest_json` — JSON string from `figures_manifest.json`
- `nodes_json_path` — path to `nodes_tree.json`
- `venue` — `arxiv` / `neurips` / `icml`
- `max_revision_rounds` — per-section revision rounds (default: 2)

**Sections order (generation):**  
`experiment → related_work → method → introduction → conclusion → abstract → title`

**Sections order (assembly in paper):**  
`introduction → related_work → method → experiment → conclusion`

**Figure embedding:**  
Figures from `figures_manifest_json` are injected into the context for experiment, method, and introduction sections. The LLM embeds them with `\includegraphics[width=0.8\linewidth]{path}`.

**Output:** `full_paper.tex` + `refs.bib`

## Experiment Summary Format

To enable dynamic metric keyword extraction, include an HTML comment:

```
<!-- metric_keyword: MFLOPS -->
<!-- min_expected_metric: 50000 -->
```

Without these, the skill falls back to generic terms.

## Design Principles in Prompts

All prompts include the **reproducibility principle**:  
> "Describe the experimental environment using reproducible technical specifications (e.g. processor architecture, core count, compiler version) rather than deployment-specific identifiers."

This prevents cluster names, organization names, and job IDs from appearing in the paper.

## BibTeX

Citations use `@misc` format (appropriate for arXiv preprints):

```bibtex
@misc{key2024,
  author = {...},
  title  = {...},
  year   = {2024},
  note   = {arXiv preprint}
}
```

## Installation

```bash
pip install -e .
```
