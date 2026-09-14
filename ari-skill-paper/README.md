# ari-skill-paper

MCP skill for **AI Scientist v2-style iterative paper generation**.

## Design

Implements `write_paper_iterative`: it fills the whole venue template in a single LLM call, then runs `max_revision_rounds` whole-document reflection rounds (compile + fix).  
Accepts figures from `generate_figures` stage and embeds them with `\includegraphics`.  
Review-driven revision is `paper_refine`: it applies the `suggested_revisions` that `merge_reviews` emits as targeted, anchor-preserving replacements in the one manuscript — a revision entry may name a `section`, but nothing regenerates a section on its own.

## LLM Exception

This skill calls an LLM (P2 exception). Requires Ollama running on the same node.

## Tool

### `write_paper_iterative`

Writes a full LaTeX paper from experiment results.

**Key inputs:**
- `workspace_root` — closed checkpoint root that every other input path resolves under
- `science_data_path` — native `ScienceDataV1` (`science_data.json`)
- `figures_manifest_path` — native `FigureBatchV1` (`figures_manifest.json`)
- `references_path` — recorded retrieval result (`related_refs.json`)
- `ear_manifest_path` — EAR generation result (`ear_manifest.json`)
- `rubric_id` — explicit rubric id; there is no environment fallback and no guessed default
- `experiment_summary` — experiment context (`context` is accepted as an alias)
- `venue` — `neurips` / `icpp` / `sc` / `isc` / `arxiv` / `acm` (default: `arxiv`)
- `max_revision_rounds` — whole-document reflection rounds (default: 2)

**Section layout:**  
The section layout is defined by the venue template (`FILL_*_START`/`FILL_*_END` blocks) and filled in one pass; there is no per-section generation order.

**Figure embedding:**  
Figures from `figures_manifest_path` are injected into the template context. The LLM embeds them with `\includegraphics[width=0.85\linewidth]{path}`.

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
| `compile_paper` | `pdflatex` (+ `bibtex`) compile of a tex directory |
| `check_format` | Venue format validation of the compiled PDF (page limit, readable file) |
| `write_paper_iterative` | One-pass template fill + whole-document reflection rounds |
| `link_paper_claims` | Build `paper_claim_links.json` (anchors / numeric_mentions / figure_refs consumed by the claim hard gate) |
| `paper_refine` | Whole-document, anchor-preserving revision pass with math-safe underscore escaping |
| `review_compiled_paper` | Final-pass review on the compiled PDF (delegates VLM-side checks to `ari-skill-vlm`) |
| `list_rubrics` | Reviewer rubric catalogue |
| `inject_code_availability` | v0.7.0 — append the `\codedigest{...}` block |
| `merge_reviews` | v0.7.0 — combine rubric review + VLM review, and emit `suggested_revisions` for `paper_refine` |
| `finalize_paper_build` | Lock the exact evidence, reviews, compile record and claim links into `paper_build.json` |

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
| `ARI_MODEL_PAPER` | Paper writer/refiner model; falls through to `ARI_LLM_MODEL` |
| `ARI_MODEL_RUBRIC` | Independent rubric-review/panel model; falls through to `ARI_LLM_MODEL` |
| `ARI_PANEL_SEED` | Optional requested seed for rubric completions; enforcement is provider/backend dependent |
| `ARI_LLM_MODEL` | Shared fallback model |

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
