# ari-skill-paper

MCP skill for **AI Scientist v2-style iterative paper generation**.

## Design

Implements `write_paper_iterative`: it fills the whole venue template in a single LLM call, then runs `max_revision_rounds` whole-document reflection rounds (compile + fix).  
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
- `max_revision_rounds` — whole-document reflection rounds (default: 2)

**Section layout:**  
The section layout is defined by the venue template (`FILL_*_START`/`FILL_*_END` blocks) and filled in one pass; there is no per-section generation order.

**Figure embedding:**  
Figures from `figures_manifest_json` are injected into the template context. The LLM embeds them with `\includegraphics[width=0.85\linewidth]{path}`.

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

`_build_bib_content` uses the authoritative Semantic Scholar BibTeX when a
reference carries `bibtex` + `cite_key`; otherwise it synthesizes an
`@article` entry from the metadata:

```bibtex
@article{key2024,
  author = {...},
  title  = {...},
  year   = {2024},
  note   = {...}
}
```

## All MCP tools

| Tool | Purpose |
|---|---|
| `list_venues` | Available LaTeX venues (`acm` / `neurips` / `sc` / `icpp` / `isc` / `arxiv`) |
| `get_template` | Fetch the LaTeX template for a venue |
| `generate_section` | LLM writes one section |
| `compile_paper` | `pdflatex` compile |
| `check_format` | LaTeX format validation |
| `review_section` | LLM rubric review of one section |
| `revise_section` | LLM rewrite from review feedback |
| `write_paper_iterative` | One-pass template fill + whole-document reflection rounds |
| `link_paper_claims` | Build `paper_claim_links.json` (anchors / writer_assertions / numeric_mentions consumed by the claim hard gate) |
| `paper_refine` | Anchor-preserving revision pass with math-safe underscore escaping |
| `review_compiled_paper` | Final-pass review on the compiled PDF (delegates VLM-side checks to `ari-skill-vlm`) |
| `list_rubrics` | Reviewer rubric catalogue |
| `inject_code_availability` | v0.7.0 — append the `\codedigest{...}` block |
| `merge_reviews` | v0.7.0 — combine rubric review + VLM review |

## Venue templates

`templates/` ships one subdirectory per venue, each holding `main.tex` +
`refs.bib`. `get_template(venue)` reads `templates/<venue>/`:

- `acm/`
- `arxiv/`
- `icpp/`
- `isc/`
- `neurips/`
- `sc/`

## Rubric system (v0.6+)

Reviewer rubrics are YAML files under `ARI_RUBRIC_DIR` (defaults to
`ari-core/config/reviewer_rubrics/`).  `ARI_RUBRIC` selects the
active rubric; the same file drives both BFTS scoring and the
published paper review (see
`docs/concepts/architecture.md#plan--venue-contract-v070`).

`ARI_STRICT_DYNAMIC=true` forces dynamic-axis generation even when
the rubric defines fixed axes.

## Environment variables

| Variable | Purpose |
|---|---|
| `ARI_RUBRIC_DIR` | Rubric YAML directory |
| `ARI_RUBRIC` | Active rubric id |
| `ARI_STRICT_DYNAMIC` | Force dynamic-axis generation |
| `ARI_CHECKPOINT_DIR` | Where the few-shot cache (`.ari_fewshot_cache`) lives |
| `ARI_LLM_MODEL` | Paper-generation LLM |

## settings.json fields

The skill consumes a `paper:` section from the per-checkpoint
`settings.json` (rubric override, venue default, ensemble size).
See `docs/reference/configuration.md` for the canonical schema.

## Tests

```bash
pytest tests/test_server.py -q             # MCP API
pytest tests/test_rubric.py -q             # rubric evaluation
pytest tests/test_code_availability.py -q  # \codedigest injection
```

## P2 exception

The skill calls an LLM heavily, so output is non-deterministic.
Combine with rubric-driven review + ensemble voting to dampen
variance.

## Installation

```bash
pip install -e .
```

## See also

- `docs/reference/skills.md#ari-skill-paper` — high-level summary.
- `docs/reference/mcp_tools.md` — argument signatures.
- `ari-skill-vlm` — figure / table review delegate.
